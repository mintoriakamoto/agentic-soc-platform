from apps.settings.runtime_config import refresh_if_stale


class RuntimeConfigFreshnessMiddleware:
    """Adopt configuration changed by another process before handling a request.

    Runtime config is cached per process, so without this only the gunicorn worker that served
    the settings change would see it — sibling workers would keep using stale credentials until
    they recycled. This costs one cache read per request and only clears caches when the shared
    generation counter has actually moved.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        refresh_if_stale()
        return self.get_response(request)
