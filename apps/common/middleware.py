from __future__ import annotations

from django.conf import settings
from django.core.cache import cache
from django.utils import timezone


class SessionInactivityMiddleware:
    """Expose a warning header when an authenticated dashboard session is idle."""

    def __init__(self, get_response):
        self.get_response = get_response
        self.timeout_seconds = int(
            getattr(settings, "SESSION_INACTIVITY_TIMEOUT", 900)
        )

    def __call__(self, request):
        should_warn = False
        user = getattr(request, "user", None)
        if (
            request.path.startswith("/api/v1/")
            and user is not None
            and user.is_authenticated
        ):
            cache_key = f"dashboard:last_activity:{user.pk}"
            now_ts = int(timezone.now().timestamp())
            last_ts = cache.get(cache_key)
            should_warn = bool(last_ts and now_ts - int(last_ts) > self.timeout_seconds)
            cache.set(cache_key, now_ts, timeout=self.timeout_seconds * 2)

        response = self.get_response(request)
        if should_warn:
            response["X-Session-Expiring"] = "true"
        return response
