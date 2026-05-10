"""
C-21: BroadcastManager
=======================
Manages the full lifecycle of broadcast campaigns including audience targeting,
pre-translation, batched dispatch, and progress tracking.

PRIVACY CONSTRAINTS (non-negotiable):
  • Phone numbers must NEVER be passed as Celery task arguments — they would be
    stored in the Redis result backend in plaintext.
  • The dispatch_broadcast task receives only broadcast_id and decrypts phone
    numbers itself during execution.
  • Every decrypted phone is zeroed (recipient = None) immediately after send().

IDEMPOTENCY:
  • dispatch_broadcast checks broadcast.status before doing any work.
  • If status is already 'Completed' or 'Sending', it returns immediately
    to prevent duplicate sends on Celery worker crash + retry.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Optional

from django.core.cache import cache
from django.utils import timezone

from apps.notifications.models import Broadcast, Notification, UserConsent

logger = logging.getLogger("apps.notifications.broadcast_manager")

_BATCH_SIZE = 100
_BATCH_DELAY_SECONDS = 2


def _get_supported_languages() -> list[str]:
    """Return the list of languages configured for broadcasts."""
    import os
    raw = os.environ.get("SUPPORTED_BROADCAST_LANGUAGES", "en,sw,lg,ar,so,fr")
    return [lang.strip() for lang in raw.split(",") if lang.strip()]


def resolve_broadcast_recipients(broadcast: Broadcast):
    """
    Return the UserConsent queryset matching the broadcast's targeting criteria.
    Extracted as a standalone function so dispatch_broadcast (Celery task) can
    call it without importing the full BroadcastManager class.
    """
    from apps.feedback.models import Feedback, FeedbackCategory

    target_type = broadcast.target_type

    if target_type == Broadcast.TargetType.ALL:
        return UserConsent.objects.filter(
            is_active=True,
            consent_type=UserConsent.ConsentType.FOLLOW_UP,
        )

    if target_type == Broadcast.TargetType.BY_LOCATION:
        settlement = broadcast.target_location or ""
        anon_ids = (
            Feedback.objects.filter(location__icontains=settlement)
            .values_list("anonymous_user_id", flat=True)
            .distinct()
        )
        return UserConsent.objects.filter(
            anonymous_user_id__in=anon_ids,
            is_active=True,
            consent_type=UserConsent.ConsentType.FOLLOW_UP,
        )

    if target_type == Broadcast.TargetType.BY_CATEGORY:
        category_id = broadcast.target_category_id
        since = timezone.now() - timedelta(days=broadcast.target_days)
        anon_ids = (
            FeedbackCategory.objects.filter(
                category_id=category_id,
                feedback__submitted_at__gte=since,
            )
            .values_list("feedback__anonymous_user_id", flat=True)
            .distinct()
        )
        return UserConsent.objects.filter(
            anonymous_user_id__in=anon_ids,
            is_active=True,
            consent_type=UserConsent.ConsentType.FOLLOW_UP,
        )

    if target_type == Broadcast.TargetType.BY_FEEDBACK_IDS:
        feedback_ids = broadcast.target_feedback_ids or []
        anon_ids = (
            Feedback.objects.filter(feedback_id__in=feedback_ids)
            .values_list("anonymous_user_id", flat=True)
        )
        return UserConsent.objects.filter(
            anonymous_user_id__in=anon_ids,
            is_active=True,
            consent_type=UserConsent.ConsentType.FOLLOW_UP,
        )

    # Should never reach here — model validation enforces choices
    logger.error("resolve_broadcast_recipients: Unknown target_type '%s'", target_type)
    return UserConsent.objects.none()


class NoBroadcastRecipientsError(Exception):
    """Raised when no opted-in recipients match the broadcast target criteria."""


class BroadcastManager:
    """Manages creation, scheduling, and dispatch of broadcast campaigns."""

    def create_broadcast(
        self,
        message_type: str,
        body_en: str,
        target_type: str,
        target_params: dict,
        channels: list,
        languages: list,
        schedule_at: Optional[datetime] = None,
        user=None,
    ) -> Broadcast:
        """
        Validate recipients, create a Broadcast record, and trigger dispatch.

        Parameters
        ----------
        message_type:  'YSWD' or 'General_Announcement'
        body_en:       Message body in English.
        target_type:   'all' | 'by_location' | 'by_category' | 'by_feedback_ids'
        target_params: Dict with keys matching the target_type (see spec).
        channels:      List of channels, e.g. ['SMS', 'WhatsApp']
        languages:     List of BCP-47 language codes, e.g. ['en', 'sw']
        schedule_at:   If None, dispatch immediately.
        user:          The User who created the broadcast.

        Returns
        -------
        The created Broadcast record.

        Raises
        ------
        NoBroadcastRecipientsError – if no opted-in users match the criteria.
        """
        from apps.notifications.tasks import dispatch_broadcast

        # Build a temporary Broadcast-like object to reuse resolve_broadcast_recipients
        # without saving to the DB yet, so we can validate recipient count first.
        # We use a lightweight approach: create a partial instance, resolve, then save.
        broadcast = Broadcast(
            created_by=user,
            message_type=message_type,
            body_en=body_en,
            target_type=target_type,
            scheduled_at=schedule_at,
        )

        # Populate target fields from target_params
        if target_type == Broadcast.TargetType.BY_LOCATION:
            broadcast.target_location = target_params.get("settlement", "")
        elif target_type == Broadcast.TargetType.BY_CATEGORY:
            broadcast.target_category_id = target_params.get("category_id")
            broadcast.target_days = target_params.get("days", 30)
        elif target_type == Broadcast.TargetType.BY_FEEDBACK_IDS:
            broadcast.target_feedback_ids = target_params.get("feedback_ids", [])

        # Validate recipients before saving
        consents = resolve_broadcast_recipients(broadcast)
        if consents.count() == 0:
            raise NoBroadcastRecipientsError(
                "No opted-in recipients match the target criteria."
            )

        # Save the broadcast record
        broadcast.status = Broadcast.Status.SCHEDULED
        broadcast.total_recipients = consents.count()
        broadcast.save()

        # Audit log
        try:
            from apps.common.audit import AuditAction, log_audit_event
            log_audit_event(
                user=user,
                action=AuditAction.NOTIFICATION_SENT,
                feedback=None,
                field_changed="broadcast_created",
                new_value=f"broadcast_id={broadcast.pk} type={message_type} target={target_type}",
            )
        except Exception as exc:
            logger.warning("BroadcastManager.create_broadcast: Audit log failed: %s", exc)

        # Dispatch immediately or schedule via Celery Beat
        if schedule_at is None or schedule_at <= timezone.now():
            dispatch_broadcast.delay(broadcast.broadcast_id)
        else:
            dispatch_broadcast.apply_async(
                args=[broadcast.broadcast_id],
                eta=schedule_at,
            )

        return broadcast

    def estimate_recipients(
        self,
        target_type: str,
        target_params: dict,
    ) -> int:
        """
        Pre-flight check: return estimated recipient count without creating anything.
        Used by the frontend to show 'Estimated recipients: N' before confirming.
        """
        # Build a temporary (unsaved) Broadcast instance for resolve logic
        broadcast = Broadcast(
            target_type=target_type,
            target_days=target_params.get("days", 30),
        )
        if target_type == Broadcast.TargetType.BY_LOCATION:
            broadcast.target_location = target_params.get("settlement", "")
        elif target_type == Broadcast.TargetType.BY_CATEGORY:
            broadcast.target_category_id = target_params.get("category_id")
        elif target_type == Broadcast.TargetType.BY_FEEDBACK_IDS:
            broadcast.target_feedback_ids = target_params.get("feedback_ids", [])

        return resolve_broadcast_recipients(broadcast).count()