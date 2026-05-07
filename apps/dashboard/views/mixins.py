from __future__ import annotations

from apps.common.audit import log_audit_event


def get_client_ip(request) -> str | None:
    x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
    if x_forwarded_for:
        return x_forwarded_for.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")


class AuditLogMixin:
    """Reusable dashboard audit mixin for API views."""

    audit_action = None

    def log_action(
        self,
        request,
        feedback=None,
        field_changed=None,
        old_value=None,
        new_value=None,
    ):
        if not self.audit_action:
            return
        # log_audit_event derives IP and user-agent from request metadata.
        log_audit_event(
            user=request.user,
            action=self.audit_action,
            feedback=feedback,
            field_changed=field_changed,
            old_value=str(old_value) if old_value is not None else None,
            new_value=str(new_value) if new_value is not None else None,
            request=request,
        )
