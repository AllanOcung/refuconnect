"""
Feedback app Celery tasks.

Tasks
-----
trigger_nlp_pipeline          — Hand off a new Feedback to the NLP pipeline.
archive_old_feedback          — Periodic archival of processed feedback.
assemble_multipart_sms        — Finalise a multi-part SMS when TTL expires.
retry_failed_acknowledgement  — Exponential-backoff ack retry for SMS/WhatsApp.

Security note
-------------
Phone numbers are NEVER stored in Celery args or logged.  All tasks work
exclusively with feedback_id, anonymous_user_id, channel names, and reference_ids.
"""
from __future__ import annotations

import json
import logging
from datetime import timedelta

from celery import shared_task
from django.core.cache import cache
from django.utils import timezone

logger = logging.getLogger("refuconnect.feedback.tasks")

MAX_FEEDBACK_AGE_DAYS = 365

# Countdown values for retry_failed_acknowledgement (seconds per attempt index)
_ACK_RETRY_COUNTDOWNS = [30, 120, 300]


# ── Existing tasks ─────────────────────────────────────────────────────────────

@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def trigger_nlp_pipeline(self, feedback_id: int) -> None:
    """
    Entry-point task: hand off a newly created Feedback record to the NLP pipeline.

    Kept in the feedback app so channel views don't import directly from nlp.
    The pipeline runs once per execution; on failure the task reschedules via a
    non-blocking ``self.retry`` and, once retries are exhausted, marks the
    record 'ProcessingFailed' and alerts ops.
    """
    try:
        from apps.nlp.pipeline.consumer import process_feedback

        process_feedback(feedback_id)
    except Exception as exc:
        logger.exception(
            "NLP pipeline failed for feedback_id=%s (attempt %s)",
            feedback_id,
            self.request.retries + 1,
        )
        if self.request.retries < self.max_retries:
            raise self.retry(exc=exc)

        from apps.nlp.tasks import _mark_processing_failed

        _mark_processing_failed(feedback_id)


@shared_task
def archive_old_feedback() -> dict:
    """
    Periodic task: move fully processed feedback older than MAX_FEEDBACK_AGE_DAYS
    to 'Archived' status.

    Scheduled daily via Celery Beat.
    """
    from apps.feedback.models import Feedback

    cutoff = timezone.now() - timedelta(days=MAX_FEEDBACK_AGE_DAYS)
    updated = Feedback.objects.filter(
        status="Processed",
        processed_at__lt=cutoff,
    ).update(status="Archived")

    logger.info("Archived %d old feedback records.", updated)
    return {"archived": updated}


# ── New tasks (C-01 multi-part SMS, C-04 ack retry) ───────────────────────────

@shared_task(bind=True, max_retries=0)
def assemble_multipart_sms(self, assembly_key: str) -> None:
    """
    Finalise a multi-part SMS message when the assembly TTL expires.

    This task is enqueued with a ``countdown`` equal to the Redis TTL so it
    fires once we give up waiting for additional parts.  If all parts arrived
    early the adapter's ``_assemble_multipart()`` method will have already
    called the normaliser — this task only fires for *incomplete* assemblies
    (some parts lost in transit) and processes whatever arrived.

    The Redis state dict has the shape::

        {
          "parts": {"1": "...", "2": "..."},
          "channel": "SMS",
          "received_at": "<ISO-8601>",
          "language_hint": "en",          # optional
          "pre_category": None,           # always None for SMS
        }

    The ``sender_enc`` field (AES-256-GCM-encrypted phone) is stored as a
    separate Redis key ``{assembly_key}:sender`` to keep it off the JSON
    payload.

    Parameters
    ----------
    assembly_key:
        Redis key used by the SMSWebhookView's ``_assemble_multipart()`` method.
        Format: ``sms:mp:{sha256(phone+linkId)}``.
    """
    state_json: bytes | None = cache.get(assembly_key)
    if state_json is None:
        logger.debug(
            "assemble_multipart_sms: key=%s not found in cache (already assembled or expired)",
            assembly_key,
        )
        return

    try:
        state: dict = json.loads(state_json) if isinstance(state_json, (bytes, str)) else state_json
    except (TypeError, json.JSONDecodeError):
        state = state_json if isinstance(state_json, dict) else {}

    parts: dict = state.get("parts", {})
    if not parts:
        logger.warning("assemble_multipart_sms: key=%s has no parts — discarding", assembly_key)
        cache.delete(assembly_key)
        return

    # Sort parts by part-number index and join
    assembled_text = " ".join(
        parts[k] for k in sorted(parts.keys(), key=lambda x: int(x))
    )

    # Retrieve the encrypted sender from its separate Redis key
    sender_enc: str | None = cache.get(f"{assembly_key}:sender")
    sender: str = ""
    if sender_enc:
        try:
            from apps.common.encryption import decrypt_field
            sender = decrypt_field(sender_enc)
        except Exception:
            logger.exception(
                "assemble_multipart_sms: Failed to decrypt sender for key=%s — using empty sender",
                assembly_key,
            )

    raw_message = {
        "channel": state.get("channel", "SMS"),
        "sender": sender,
        "body": assembled_text,
        "received_at": state.get("received_at"),
        "language_hint": state.get("language_hint"),
        "pre_category": state.get("pre_category"),
    }

    # Clean up Redis
    cache.delete(assembly_key)
    cache.delete(f"{assembly_key}:sender")

    logger.info(
        "assemble_multipart_sms: Assembled %d part(s) from key=%s — forwarding to normaliser",
        len(parts),
        assembly_key,
    )

    try:
        from apps.feedback.services.normaliser import MessageNormaliser
        feedback_id = MessageNormaliser().process(raw_message)
        logger.info(
            "assemble_multipart_sms: Created feedback_id=%d from key=%s",
            feedback_id,
            assembly_key,
        )
    except Exception:
        logger.exception(
            "assemble_multipart_sms: Normaliser failed for key=%s — message lost",
            assembly_key,
        )


@shared_task(bind=True, max_retries=3)
def retry_failed_acknowledgement(
    self,
    feedback_id: int,
    channel: str,
    language: str,
    reference_id: str,
) -> None:
    """
    Retry sending an acknowledgement message with exponential backoff.

    Retry schedule (countdown in seconds):
      Attempt 0 → 30 s
      Attempt 1 → 120 s
      Attempt 2 → 300 s

    After 3 failed attempts the task stops retrying and logs an error audit
    event so dashboard operators are notified.

    Parameters
    ----------
    feedback_id:  PK of the Feedback record that needs acknowledgement.
    channel:      'SMS' | 'WhatsApp' (USSD never uses this task).
    language:     ISO 639-1 code for the acknowledgement template.
    reference_id: Human-readable reference for the feedback record.
    """
    # SECURITY: feedback_id and reference_id are safe to log.  No phone/sender.
    attempt = self.request.retries
    logger.info(
        "retry_failed_acknowledgement: feedback_id=%d channel=%s attempt=%d/%d",
        feedback_id,
        channel,
        attempt,
        self.max_retries,
    )

    try:
        from apps.notifications.services.message_router import route_notification
        from apps.notifications.services.response_composer import compose_acknowledgement
        from apps.feedback.models import Feedback
        from apps.notifications.models import Notification, UserConsent

        feedback = Feedback.objects.get(pk=feedback_id)
        consent = UserConsent.objects.filter(
            anonymous_user_id=feedback.anonymous_user_id,
            is_active=True,
        ).first()

        if consent is None:
            logger.info(
                "retry_failed_acknowledgement: No active consent for feedback_id=%d — aborting",
                feedback_id,
            )
            return

        msg_body = compose_acknowledgement(feedback, language=language, reference_id=reference_id)
        notification = Notification.objects.create(
            feedback=feedback,
            message_type=Notification.MessageType.ACKNOWLEDGEMENT,
            content=msg_body,
            delivery_language=language,
            channel=channel,
            delivery_status=Notification.DeliveryStatus.QUEUED,
        )
        success = route_notification(notification)
        if success:
            logger.info(
                "retry_failed_acknowledgement: Succeeded for feedback_id=%d on attempt=%d",
                feedback_id,
                attempt,
            )
            return

        raise RuntimeError("route_notification returned False")

    except Feedback.DoesNotExist:
        logger.error(
            "retry_failed_acknowledgement: feedback_id=%d not found — aborting", feedback_id
        )
        return

    except Exception as exc:
        if attempt < self.max_retries:
            countdown = _ACK_RETRY_COUNTDOWNS[min(attempt, len(_ACK_RETRY_COUNTDOWNS) - 1)]
            logger.warning(
                "retry_failed_acknowledgement: feedback_id=%d failed (attempt=%d) — "
                "retrying in %ds error=%s",
                feedback_id,
                attempt,
                countdown,
                exc,
            )
            raise self.retry(exc=exc, countdown=countdown)

        # All retries exhausted
        logger.error(
            "retry_failed_acknowledgement: Exhausted retries for feedback_id=%d — "
            "acknowledgement permanently failed",
            feedback_id,
        )
        try:
            from apps.common.audit import AuditAction, log_audit_event
            from apps.feedback.models import Feedback
            fb = Feedback.objects.get(pk=feedback_id)
            log_audit_event(
                user=None,
                action=AuditAction.NOTIFICATION_SENT,
                feedback=fb,
                field_changed="acknowledgement",
                new_value=f"FAILED_ALL_RETRIES refno={reference_id}",
            )
        except Exception:
            pass  # audit failure must not re-raise
