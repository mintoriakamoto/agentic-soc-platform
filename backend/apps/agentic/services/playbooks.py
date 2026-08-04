import logging
import uuid
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.agentic.runtime.base import BasePlaybook
from apps.agentic.runtime.loader import discover_script_class, iter_overlaid_python_scripts
from apps.inbox.notifications import notify_playbook_completion
from apps.playbooks.models import Playbook, PlaybookJobStatus

logger = logging.getLogger(__name__)


def default_playbook_scripts_dir():
    return Path(settings.BASE_DIR) / "playbooks"


def default_custom_playbook_scripts_dir():
    return Path(settings.CUSTOM_DIR) / "playbooks"


def default_playbook_script_dirs():
    return [default_playbook_scripts_dir(), default_custom_playbook_scripts_dir()]


def _normalize_tags(value):
    if isinstance(value, str):
        raw_tags = [value]
    elif isinstance(value, (list, tuple, set)):
        raw_tags = value
    else:
        raw_tags = []

    tags = []
    seen = set()
    for item in raw_tags:
        tag = str(item).strip()
        if tag and tag not in seen:
            tags.append(tag)
            seen.add(tag)
    return tags


def scan_playbook_definitions(*, scripts_dir=None, scripts_dirs=None):
    if scripts_dirs is not None and scripts_dir is not None:
        raise ValueError("Use scripts_dir or scripts_dirs, not both.")
    paths = (
        iter_overlaid_python_scripts(*(scripts_dirs or default_playbook_script_dirs()))
        if scripts_dir is None
        else iter_overlaid_python_scripts(scripts_dir)
    )
    definitions = []
    errors = []
    for path in paths:
        try:
            definition = discover_script_class(
                path,
                class_name="Playbook",
                base_class=BasePlaybook,
            )
        except Exception:
            logger.exception("Failed to load playbook definition from %s", path)
            errors.append({"path": str(path), "error": "Failed to load playbook definition."})
            continue
        if definition is not None:
            definitions.append(definition)
    return definitions, errors


def _playbook_definitions(scripts_dir=None):
    definitions, _errors = scan_playbook_definitions(scripts_dir=scripts_dir)
    return definitions


def list_playbook_definitions(*, include_path=False, scripts_dir=None):
    definitions = []
    for item in _playbook_definitions(scripts_dir=scripts_dir):
        data = {
            "name": item.name,
            "description": getattr(item.script_class, "DESC", ""),
            "tags": _normalize_tags(getattr(item.script_class, "TAGS", [])),
        }
        if include_path:
            data["path"] = str(item.path)
        definitions.append(data)
    return definitions


def find_playbook_class(name, *, scripts_dir=None):
    for definition in _playbook_definitions(scripts_dir=scripts_dir):
        if definition.name == name:
            return definition.script_class
    raise LookupError(f"Playbook script not found: {name}")


@transaction.atomic
def create_pending_playbook_run(*, name, case, user=None, user_input=""):
    known_names = {item["name"] for item in list_playbook_definitions()}
    if name not in known_names:
        raise ValueError(f"Unknown playbook definition: {name}")

    playbook = Playbook(
        case=case,
        name=name,
        user=user if getattr(user, "is_authenticated", False) else None,
        user_input=user_input or "",
        job_status=PlaybookJobStatus.PENDING,
    )
    playbook.full_clean()
    playbook.save()
    return playbook


@transaction.atomic
def claim_pending_playbook_run():
    playbook = (
        Playbook.objects
        .select_for_update(skip_locked=True)
        .filter(job_status=PlaybookJobStatus.PENDING)
        .order_by("created_at")
        .first()
    )
    if playbook is None:
        return None

    playbook.job_status = PlaybookJobStatus.RUNNING
    playbook.job_id = str(uuid.uuid4())
    playbook.remark = ""
    playbook.started_at = timezone.now()
    playbook.save(update_fields=["job_status", "job_id", "remark", "started_at", "updated_at"])
    return playbook


def reap_stale_playbook_runs():
    """Fail runs whose worker died mid-execution.

    Nothing else moves a row out of Running, so without this a killed worker leaves the run
    stuck there forever — never retried, never surfaced.
    """
    cutoff = timezone.now() - timedelta(seconds=settings.JOB_LEASE_TIMEOUT_SECONDS)
    # started_at is null for runs claimed before it existed; updated_at is when they were claimed,
    # so it reaps that backlog too.
    expired = Q(started_at__lt=cutoff) | Q(started_at__isnull=True, updated_at__lt=cutoff)
    stale = Playbook.objects.filter(expired, job_status=PlaybookJobStatus.RUNNING)
    reaped = 0
    for playbook in stale.iterator():
        with transaction.atomic():
            locked = Playbook.objects.select_for_update(skip_locked=True).filter(
                expired,
                pk=playbook.pk,
                job_status=PlaybookJobStatus.RUNNING,
            ).first()
            if locked is None:
                continue
            locked.job_status = PlaybookJobStatus.FAILED
            locked.remark = "Playbook run abandoned: no worker completed it within the lease window."
            locked.save(update_fields=["job_status", "remark", "updated_at"])
            reaped += 1
            logger.warning("Reaped abandoned playbook run: pk=%s started_at=%s", locked.pk, locked.started_at)
        notify_playbook_completion(locked)
    return reaped


@transaction.atomic
def mark_playbook_success(playbook, remark):
    locked = Playbook.objects.select_for_update().get(pk=playbook.pk)
    if locked.job_status != PlaybookJobStatus.RUNNING:
        raise ValueError(f"Playbook must be Running before success, got {locked.job_status}")
    locked.job_status = PlaybookJobStatus.SUCCESS
    locked.remark = remark
    locked.save(update_fields=["job_status", "remark", "updated_at"])
    notify_playbook_completion(locked)
    return locked


@transaction.atomic
def mark_playbook_failed(playbook, error):
    locked = Playbook.objects.select_for_update().get(pk=playbook.pk)
    if locked.job_status != PlaybookJobStatus.RUNNING:
        raise ValueError(f"Playbook must be Running before failure, got {locked.job_status}")
    locked.job_status = PlaybookJobStatus.FAILED
    logger.exception("Playbook execution failed", exc_info=error)
    locked.remark = "Playbook execution failed."
    locked.save(update_fields=["job_status", "remark", "updated_at"])
    notify_playbook_completion(locked)
    return locked
