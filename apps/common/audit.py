"""
Centralised audit logging.

Import and call ``log_audit_event`` everywhere instead of creating AuditLog
records directly.  This ensures consistent IP/user-agent capture and makes
it easy to swap the storage backend in the future.

Standard action constants are provided as module-level strings so callers
can use ``from apps.common.audit import AuditAction`` rather than bare strings.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from django.http import HttpRequest
    from apps.dashboard.models import AuditLog, User
    from apps.feedback.models import Feedback

logger = logging.getLogger(__name__)


class AuditAction:
    LOGIN = "LOGIN"
    LOGOUT = "LOGOUT"
    LOGIN_FAILED = "LOGIN_FAILED"
    FEEDBACK_VIEWED = "FEEDBACK_VIEWED"
    FEEDBACK_EDITED = "FEEDBACK_EDITED"
    REPORT_EXPORTED = "REPORT_EXPORTED"
    USER_CREATED = "USER_CREATED"
    USER_MODIFIED = "USER_MODIFIED"
    USER_DELETED = "USER_DELETED"
    CONFIG_CHANGED = "CONFIG_CHANGED"
    NOTIFICATION_SENT = "NOTIFICATION_SENT"
    ACCOUNT_LOCKED = "ACCOUNT_LOCKED"
    PASSWORD_RESET = "PASSWORD_RESET"
    RESPONSE_SENT = "RESPONSE_SENT"
    BROADCAST_CREATED = "BROADCAST_CREATED"
    ALERT_ACKNOWLEDGED = "ALERT_ACKNOWLEDGED"
    ALERT_RESOLVED = "ALERT_RESOLVED"
    # User-management & security (Tier-2 polish)
    PROFILE_UPDATED = "PROFILE_UPDATED"
    PASSWORD_CHANGED = "PASSWORD_CHANGED"
    MFA_ENABLED = "MFA_ENABLED"
    MFA_DISABLED = "MFA_DISABLED"
    MFA_BACKUP_CODES_GENERATED = "MFA_BACKUP_CODES_GENERATED"
    BACKUP_CODE_USED = "BACKUP_CODE_USED"
    SESSIONS_REVOKED = "SESSIONS_REVOKED"
    INVITE_RESENT = "INVITE_RESENT"
    INVITE_REVOKED = "INVITE_REVOKED"
    BULK_INVITE_CREATED = "BULK_INVITE_CREATED"


def _get_client_ip(request: "HttpRequest") -> Optional[str]:
    """Extract the real client IP, respecting common reverse-proxy headers."""
    x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
    if x_forwarded_for:
        # Take the leftmost (original client) address
        return x_forwarded_for.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")


def log_audit_event(
    user: Optional["User"],
    action: str,
    feedback: Optional["Feedback"] = None,
    field_changed: Optional[str] = None,
    old_value: Optional[str] = None,
    new_value: Optional[str] = None,
    request: Optional["HttpRequest"] = None,
    target_user: Optional["User"] = None,
) -> None:
    """
    Write a single row to the AuditLog table.

    Parameters
    ----------
    user:
        The authenticated user performing the action (``None`` for system/anonymous).
    action:
        One of the ``AuditAction`` constants, or a custom 60-char action string.
    feedback:
        Related ``Feedback`` instance, if applicable.
    field_changed:
        The model field that changed (for edit events).
    old_value:
        Serialised previous value.
    new_value:
        Serialised new value.
    request:
        The Django ``HttpRequest``.  When supplied, IP address and user-agent
        are extracted automatically.
    target_user:
        The user this event was performed *on* (the subject), if different from
        ``user`` (the actor). Used to power per-user activity timelines.
    """
    # Deferred import to avoid circular import at module load time
    from apps.dashboard.models import AuditLog  # noqa: PLC0415

    ip_address: Optional[str] = None
    user_agent: Optional[str] = None

    if request is not None:
        ip_address = _get_client_ip(request)
        raw_ua = request.META.get("HTTP_USER_AGENT", "")
        # Truncate to match GenericIPAddressField/TextField constraints
        user_agent = raw_ua[:2048] if raw_ua else None

    try:
        AuditLog.objects.create(
            user=user,
            target_user=target_user,
            feedback=feedback,
            action=action[:60],
            field_changed=field_changed[:60] if field_changed else None,
            old_value=old_value,
            new_value=new_value,
            ip_address=ip_address,
            user_agent=user_agent,
        )
    except Exception:
        # Audit logging must never crash the calling request
        logger.exception(
            "Failed to write audit log: user=%s action=%s",
            getattr(user, "user_id", None),
            action,
        )
