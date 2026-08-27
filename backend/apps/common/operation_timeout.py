import threading
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError

from django.conf import settings
from django.db import close_old_connections
from rest_framework.exceptions import APIException


class OperationTimeoutError(APIException):
    status_code = 504
    default_detail = "Operation timed out."
    default_code = "operation_timeout"


class OperationCapacityError(APIException):
    status_code = 503
    default_detail = "Too many slow operations in flight. Try again shortly."
    default_code = "operation_capacity"


MAX_CONCURRENT_OPERATIONS = 16

_executor = ThreadPoolExecutor(max_workers=MAX_CONCURRENT_OPERATIONS, thread_name_prefix="asp-operation")

# A timed-out future keeps running — cancel() cannot interrupt a thread that already started, and
# a hung SIEM or LLM call holds its worker until the upstream gives up. Without this gate those
# threads silently fill the pool and later submissions queue past their own timeout with no
# feedback. Counting in-flight work lets a saturated pool answer 503 instead of hanging.
_slots = threading.BoundedSemaphore(MAX_CONCURRENT_OPERATIONS)


def _run_with_db_cleanup(func, args, kwargs):
    close_old_connections()
    try:
        return func(*args, **kwargs)
    finally:
        close_old_connections()
        # Released here, not by the caller: the slot is occupied until the work truly ends, which
        # for a timed-out call is later than the caller stops waiting.
        _slots.release()


def run_with_operation_timeout(operation: str, func, *args, timeout_seconds: float | None = None, **kwargs):
    timeout = float(timeout_seconds if timeout_seconds is not None else settings.SYNC_OPERATION_TIMEOUT_SECONDS)
    if not _slots.acquire(blocking=False):
        raise OperationCapacityError(
            f"{operation} rejected: all {MAX_CONCURRENT_OPERATIONS} operation slots are busy."
        )
    try:
        future = _executor.submit(_run_with_db_cleanup, func, args, kwargs)
    except BaseException:
        _slots.release()
        raise

    try:
        return future.result(timeout=timeout)
    except FutureTimeoutError as exc:
        raise OperationTimeoutError(f"{operation} timed out after {timeout:g} seconds.") from exc
