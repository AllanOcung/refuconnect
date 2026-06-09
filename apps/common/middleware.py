from __future__ import annotations

import logging

from django.conf import settings
from django.core.cache import cache
from django.utils import timezone

logger = logging.getLogger(__name__)


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


class LastSeenMiddleware:
    """
    Update ``User.last_seen_at`` on authenticated requests, throttled so we
    never write more than once per minute per user.  Uses ``.update()`` to
    bypass auto_now and pre/post-save signals.
    """

    THROTTLE_SECONDS = 60

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        user = getattr(request, "user", None)
        if user is not None and getattr(user, "is_authenticated", False):
            self._touch(user.pk)
        return response

    def _touch(self, user_id) -> None:
        cache_key = f"last_seen:{user_id}"
        try:
            if cache.get(cache_key):
                return  # within throttle window
            # Set the cache flag first so we don't double-write on concurrent requests.
            cache.set(cache_key, "1", timeout=self.THROTTLE_SECONDS)
        except Exception:
            logger.exception("last_seen cache check failed; skipping update")
            return

        try:
            # Deferred import to avoid loading the model at app-startup time.
            from apps.dashboard.models import User as DashboardUser  # noqa: PLC0415

            DashboardUser.objects.filter(pk=user_id).update(
                last_seen_at=timezone.now()
            )
        except Exception:
            logger.exception("last_seen update failed for user_id=%s", user_id)
