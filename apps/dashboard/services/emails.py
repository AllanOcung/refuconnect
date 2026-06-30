"""
Transactional email helpers for the dashboard app.

Each function renders matching ``.html`` + ``.txt`` templates and sends the
message via ``EmailMultiAlternatives`` so HTML-aware clients see the branded
version and plain-text fallbacks remain readable.

All sends are ``fail_silently=True`` — email failure must never block the
user-facing request.  Capture issues via the SMTP error logs in the worker /
web container instead.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string

if TYPE_CHECKING:
    from apps.dashboard.models import User

logger = logging.getLogger(__name__)

INVITE_EXPIRY_DAYS = 7
PASSWORD_RESET_EXPIRY_HOURS = 1


def _send_branded_email(
    subject: str,
    to: str,
    template_base: str,
    context: dict,
) -> bool:
    """
    Render `emails/{template_base}.html` + `.txt`, send as multipart.
    Returns True on send, False on error (never raises).
    """
    try:
        text_body = render_to_string(f"emails/{template_base}.txt", context)
        html_body = render_to_string(f"emails/{template_base}.html", context)
    except Exception:
        logger.exception("Failed to render email template '%s'", template_base)
        return False

    msg = EmailMultiAlternatives(
        subject=subject,
        body=text_body,
        from_email=None,  # defaults to settings.DEFAULT_FROM_EMAIL
        to=[to],
    )
    msg.attach_alternative(html_body, "text/html")
    try:
        msg.send(fail_silently=False)
        return True
    except Exception:
        logger.exception("Failed to deliver '%s' email to %s", template_base, to)
        return False


def send_invitation_email(
    user: "User",
    inviter: "User",
    token: str,
) -> bool:
    """Send the 'You've been invited to RefuConnect' email."""
    invite_url = (
        f"{settings.DASHBOARD_URL.rstrip('/')}/accept-invite?token={token}"
    )
    context = {
        "invitee_name": user.full_name,
        "inviter_name": inviter.full_name if inviter else "An administrator",
        "role_display": user.get_role_display(),
        "invite_url": invite_url,
        "expires_in_days": INVITE_EXPIRY_DAYS,
    }
    return _send_branded_email(
        subject="You've been invited to RefuConnect",
        to=user.email,
        template_base="invitation",
        context=context,
    )


def send_password_reset_email(user: "User", token: str) -> bool:
    """Send the 'Reset your password' email with a clickable link."""
    reset_url = (
        f"{settings.DASHBOARD_URL.rstrip('/')}/reset-password?token={token}"
    )
    context = {
        "user_name": user.full_name,
        "reset_url": reset_url,
        "expires_in_hours": PASSWORD_RESET_EXPIRY_HOURS,
    }
    return _send_branded_email(
        subject="Reset your RefuConnect password",
        to=user.email,
        template_base="password_reset",
        context=context,
    )


def send_urgent_alert_email(user: "User", feedback) -> bool:
    """
    Notify an NGO staff member that a high-urgency feedback needs review.

    ``feedback`` is a Feedback instance; we use the English text when available
    so the alert is readable regardless of the original language.
    """
    feedback_url = (
        f"{settings.DASHBOARD_URL.rstrip('/')}/feedback/{feedback.feedback_id}"
    )
    message = (getattr(feedback, "message_text_en", None) or feedback.message_text or "").strip()
    if len(message) > 300:
        message = message[:300].rstrip() + "…"
    context = {
        "user_name": user.full_name,
        "feedback_id": feedback.feedback_id,
        "channel": feedback.channel,
        "location": feedback.location or "Unknown",
        "submitted_at": feedback.submitted_at,
        "message_excerpt": message,
        "feedback_url": feedback_url,
    }
    return _send_branded_email(
        subject=f"Urgent feedback #{feedback.feedback_id} needs attention",
        to=user.email,
        template_base="urgent_alert",
        context=context,
    )


def send_account_locked_email(user: "User") -> bool:
    """Send the 'Your account has been locked' email."""
    context = {
        "user_name": user.full_name,
        "support_email": getattr(settings, "SUPPORT_EMAIL", ""),
    }
    return _send_branded_email(
        subject="Your RefuConnect account has been locked",
        to=user.email,
        template_base="account_locked",
        context=context,
    )
