"""
Celery tasks for the notifications app.

Tasks
-----
dispatch_broadcast          – Sends a broadcast campaign in batches (C-21).
check_scheduled_broadcasts  – Every-minute Beat task: triggers due broadcasts.
retry_failed_notifications  – Every-30-min Beat task: retries failed Notifications.
cleanup_expired_consents    – Daily Beat task: deactivates old consent records.
send_notification_task      – Legacy single-notification send task (kept for
                              backwards compat with existing retry_failed_acknowledgement
                              in feedback/tasks.py).

PRIVACY CONSTRAINTS (non-negotiable):
  • Celery task arguments must NEVER contain phone numbers — they are stored
    in the Redis result backend in plaintext.
  • dispatch_broadcast receives only broadcast_id and decrypts phone numbers
    itself during execution.
"""
from __future__ import annotations

import logging
import time

from celery import shared_task
from django.conf import settings
from django.core.cache import cache
from django.utils import timezone

logger = logging.getLogger("apps.notifications.tasks")

_BATCH_DELAY = int(getattr(settings, "BROADCAST_BATCH_DELAY_SECONDS", 2))
_BATCH_SIZE = int(getattr(settings, "BROADCAST_BATCH_SIZE", 100))
_NOTIFICATION_MAX_RETRIES = int(getattr(settings, "NOTIFICATION_MAX_RETRIES", 3))
_CONSENT_RETENTION_DAYS = int(getattr(settings, "CONSENT_RETENTION_DAYS", 30))


# ─── Broadcast dispatch ───────────────────────────────────────────────────────

@shared_task(bind=True)
def dispatch_broadcast(self, broadcast_id: int) -> None:
    """
    Dispatch a broadcast campaign to all matching recipients in batches.

    Idempotency guard: if the broadcast is already 'Completed' or 'Sending'
    (e.g. due to a Celery worker crash and retry), return immediately to
    prevent duplicate sends.

    Pre-translates all required languages and caches them in Redis so that
    translations survive worker restarts mid-dispatch.

    PRIVACY: Phone numbers are decrypted here, used once, then zeroed out.
    They are NEVER stored in task args or any persistent store.
    """
    from apps.common.encryption import decrypt_field
    from apps.notifications.models import Broadcast, Notification, UserConsent
    from apps.notifications.services.broadcast_manager import resolve_broadcast_recipients
    from apps.notifications.services.message_router import MessageRouter

    try:
        broadcast = Broadcast.objects.get(broadcast_id=broadcast_id)
    except Broadcast.DoesNotExist:
        logger.error("dispatch_broadcast: broadcast_id=%d not found.", broadcast_id)
        return

    # Idempotency guard
    if broadcast.status in (Broadcast.Status.COMPLETED, Broadcast.Status.SENDING):
        logger.info(
            "dispatch_broadcast: broadcast_id=%d already %s — skipping.",
            broadcast_id,
            broadcast.status,
        )
        return

    broadcast.status = Broadcast.Status.SENDING
    broadcast.started_at = timezone.now()
    broadcast.save(update_fields=["status", "started_at"])

    # Resolve recipients
    consents = resolve_broadcast_recipients(broadcast)

    # Pre-translate into all required languages; cache in Redis
    supported_langs = _get_supported_languages()
    translations: dict[str, str] = {}

    for lang in supported_langs:
        cache_key = f"broadcast:{broadcast_id}:translation:{lang}"
        cached = cache.get(cache_key)
        if cached:
            translations[lang] = cached
        else:
            if lang == "en":
                translations["en"] = broadcast.body_en
            else:
                try:
                    from apps.nlp.services.translation_service import TranslationService  # type: ignore[import]
                    translations[lang] = TranslationService().translate_text(
                        broadcast.body_en, source="en", target=lang
                    )
                except Exception as exc:
                    logger.warning(
                        "dispatch_broadcast: Translation to '%s' failed: %s — using English.",
                        lang,
                        exc,
                    )
                    translations[lang] = broadcast.body_en
            try:
                cache.set(cache_key, translations[lang], timeout=86400)
            except Exception as exc:
                logger.warning(
                    "dispatch_broadcast: Redis cache set for lang='%s' failed: %s", lang, exc
                )

    router = MessageRouter()
    sent = 0
    failed = 0
    broadcast_channels = broadcast.channels or ["SMS", "WhatsApp"]

    # Process in batches using consent_id list so we can paginate safely
    consent_ids = list(consents.values_list("consent_id", flat=True))

    for batch_start in range(0, len(consent_ids), _BATCH_SIZE):
        batch_ids = consent_ids[batch_start : batch_start + _BATCH_SIZE]
        batch = list(UserConsent.objects.filter(consent_id__in=batch_ids))

        # One query per batch: resolve each recipient's preferred language from
        # their most recent feedback submission.
        from apps.feedback.models import Feedback
        anon_ids = [c.anonymous_user_id for c in batch]
        lang_map = dict(
            Feedback.objects.filter(anonymous_user_id__in=anon_ids)
            .order_by("anonymous_user_id", "-submitted_at")
            .distinct("anonymous_user_id")
            .values_list("anonymous_user_id", "language")
        )

        for consent in batch:
            # Pick message body in the closest available language
            lang = _pick_language(consent, translations, lang_map)
            body = translations.get(lang, translations.get("en", broadcast.body_en))

            # Decrypt phone — IN MEMORY ONLY, never log or store
            try:
                recipient = decrypt_field(consent.phone_number_encrypted)
            except Exception as exc:
                logger.error(
                    "dispatch_broadcast: Decryption failed for consent_id=%d: %s",
                    consent.consent_id,
                    exc,
                )
                failed += 1
                continue

            channel = (
                consent.channel_preference
                if consent.channel_preference in broadcast_channels
                else broadcast_channels[0]
            )

            # Create notification record
            notification = Notification.objects.create(
                feedback=None,  # broadcast not tied to a single feedback
                sent_by_user=broadcast.created_by,
                message_type=(
                    Notification.MessageType.BROADCAST_YSWD
                    if broadcast.message_type == Broadcast.MessageType.YSWD
                    else Notification.MessageType.BROADCAST_GENERAL
                ),
                channel=channel,
                content=body,
                delivery_language=lang,
                delivery_status=Notification.DeliveryStatus.QUEUED,
            )

            result = router.send(
                channel=channel,
                recipient=recipient,
                body=body,
                notification_record=notification,
            )

            # Privacy wipe immediately after send
            recipient = None  # noqa: F841

            if result["status"] == "Sent":
                sent += 1
            else:
                failed += 1

        # Update progress after each batch
        broadcast.sent_count = sent
        broadcast.failed_count = failed
        broadcast.save(update_fields=["sent_count", "failed_count"])

        # Respect gateway rate limits
        if batch_start + _BATCH_SIZE < len(consent_ids):
            time.sleep(_BATCH_DELAY)

    broadcast.status = Broadcast.Status.COMPLETED
    broadcast.completed_at = timezone.now()
    broadcast.save(update_fields=["status", "completed_at"])

    logger.info(
        "dispatch_broadcast: broadcast_id=%d completed — sent=%d failed=%d",
        broadcast_id,
        sent,
        failed,
    )


# ─── Scheduled broadcast checker ─────────────────────────────────────────────

@shared_task
def check_scheduled_broadcasts() -> None:
    """
    Runs every minute via Celery Beat.
    Finds broadcasts with scheduled_at <= now() and status='Scheduled'
    and triggers dispatch_broadcast for each.
    """
    from apps.notifications.models import Broadcast

    due = Broadcast.objects.filter(
        status=Broadcast.Status.SCHEDULED,
        scheduled_at__lte=timezone.now(),
    )

    count = 0
    for broadcast in due:
        dispatch_broadcast.delay(broadcast.broadcast_id)
        count += 1

    if count:
        logger.info("check_scheduled_broadcasts: Triggered %d broadcast(s).", count)


# ─── Retry failed notifications ───────────────────────────────────────────────

@shared_task
def retry_failed_notifications() -> int:
    """
    Runs every 30 minutes via Celery Beat.
    Finds Notification records with delivery_status='Failed' and retry_count < max.
    Notifications older than 24 hours are not retried.
    """
    from datetime import timedelta
    from apps.notifications.models import Notification
    from apps.notifications.services.message_router import MessageRouter
    from apps.common.encryption import decrypt_field
    from apps.notifications.models import UserConsent

    cutoff = timezone.now() - timedelta(hours=24)

    failed_notifications = Notification.objects.filter(
        delivery_status=Notification.DeliveryStatus.FAILED,
        retry_count__lt=_NOTIFICATION_MAX_RETRIES,
        sent_at__gte=cutoff,
    ).select_related("feedback")

    router = MessageRouter()
    retried = 0

    for notification in failed_notifications:
        # Find the consent record to get the encrypted phone and channel
        if notification.feedback_id is None:
            # Broadcast notification — skip individual retry
            continue

        try:
            from apps.notifications.models import UserConsent as UC
            consent = UC.objects.filter(
                anonymous_user_id=notification.feedback.anonymous_user_id,
                is_active=True,
                consent_type=UC.ConsentType.FOLLOW_UP,
            ).first()

            if consent is None:
                continue

            recipient = decrypt_field(consent.phone_number_encrypted)

            notification.delivery_status = Notification.DeliveryStatus.QUEUED
            notification.save(update_fields=["delivery_status"])

            router.send(
                channel=notification.channel,
                recipient=recipient,
                body=notification.content,
                notification_record=notification,
            )

            # Privacy wipe
            recipient = None  # noqa: F841
            retried += 1

        except Exception as exc:
            logger.error(
                "retry_failed_notifications: Failed to retry notification_id=%d: %s",
                notification.notification_id,
                exc,
            )

    logger.info("retry_failed_notifications: Retried %d notification(s).", retried)
    return retried


# ─── Consent cleanup ──────────────────────────────────────────────────────────

@shared_task
def cleanup_expired_consents() -> int:
    """
    Runs daily at 01:00 UTC via Celery Beat.
    Deactivates UserConsent records where consent_withdrawn_at is older than
    CONSENT_RETENTION_DAYS (data retention policy).
    """
    from datetime import timedelta
    from apps.notifications.models import UserConsent

    cutoff = timezone.now() - timedelta(days=_CONSENT_RETENTION_DAYS)

    updated = UserConsent.objects.filter(
        is_active=False,
        consent_withdrawn_at__lt=cutoff,
    ).update(is_active=False)  # already False, but this lets us add future cleanup here

    # Hard-delete very old withdrawn consents if required by data-retention policy
    deleted_count, _ = UserConsent.objects.filter(
        is_active=False,
        consent_withdrawn_at__lt=cutoff,
    ).delete()

    logger.info(
        "cleanup_expired_consents: Deleted %d expired consent record(s).", deleted_count
    )
    return deleted_count


# ─── Legacy single-notification task (backwards compat) ──────────────────────

@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def send_notification_task(self, notification_id: int) -> None:
    """
    Send a single queued Notification via its preferred channel.
    Kept for backwards compatibility with feedback/tasks.py retry logic.
    """
    from apps.notifications.models import Notification, UserConsent
    from apps.notifications.services.message_router import MessageRouter
    from apps.common.encryption import decrypt_field

    try:
        notification = Notification.objects.get(pk=notification_id)
    except Notification.DoesNotExist:
        logger.error("send_notification_task: Notification %d not found.", notification_id)
        return

    if notification.delivery_status == Notification.DeliveryStatus.DELIVERED:
        return

    if notification.feedback_id is None:
        logger.warning(
            "send_notification_task: notification_id=%d has no feedback — cannot resolve recipient.",
            notification_id,
        )
        return

    try:
        consent = UserConsent.objects.filter(
            anonymous_user_id=notification.feedback.anonymous_user_id,
            is_active=True,
        ).first()

        if consent is None:
            logger.warning(
                "send_notification_task: No consent for notification_id=%d", notification_id
            )
            return

        recipient = decrypt_field(consent.phone_number_encrypted)

        result = MessageRouter().send(
            channel=notification.channel,
            recipient=recipient,
            body=notification.content,
            notification_record=notification,
        )

        recipient = None  # Privacy wipe

        if result["status"] != "Sent":
            raise RuntimeError("MessageRouter returned Failed")

    except Exception as exc:
        logger.warning(
            "send_notification_task: Delivery failed for notification_id=%d: %s — retrying.",
            notification_id,
            exc,
        )
        raise self.retry(exc=exc)


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _get_supported_languages() -> list[str]:
    import os
    raw = os.environ.get("SUPPORTED_BROADCAST_LANGUAGES", "en,sw,lg,ar,so,fr")
    return [lang.strip() for lang in raw.split(",") if lang.strip()]


def _pick_language(consent, translations: dict, lang_map: dict | None = None) -> str:
    """
    Select the best available language for a recipient.

    Uses the pre-fetched lang_map (anonymous_user_id → language from their most
    recent feedback) to pick a translated version. Falls back to English.
    """
    preferred = (lang_map or {}).get(consent.anonymous_user_id) or "en"
    if preferred in translations:
        return preferred
    return "en"