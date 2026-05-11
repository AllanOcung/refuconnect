"""
C-20: ResponseComposer
======================
Handles NGO staff composing and sending targeted replies to individual
feedback items. Only works for community members who have explicitly opted in
to follow-up contact (their encrypted phone number is in UserConsent).

PRIVACY CONSTRAINTS (non-negotiable):
  • Decrypted phone numbers exist in memory only for the duration of the send call.
  • ``recipient = None`` immediately after MessageRouter.send() returns.
  • The decrypted number must never appear in a log line, a DB field, a Celery
    task argument, or any variable that persists beyond the send call.
"""
from __future__ import annotations

import logging

from django.utils import timezone

from apps.common.audit import log_audit_event
from apps.common.encryption import decrypt_field
from apps.common.exceptions import ConsentNotFoundError
from apps.notifications.models import Notification, UserConsent
from apps.notifications.services.message_router import MessageRouter

logger = logging.getLogger("apps.notifications.response_composer")

_MAX_BODY_CHARS = 640
_TRUNCATION_SUFFIX = "..."


class FeedbackNotFoundError(Exception):
    """Raised when the requested Feedback record does not exist."""


class ResponseComposer:
    """Composes and dispatches targeted NGO-staff responses to individual feedback."""

    def send_response(
        self,
        feedback_id: int,
        message_body: str,
        language_override: str | None = None,
        user=None,
    ) -> dict:
        """
        Compose and send a targeted response to the opted-in community member
        who submitted a specific feedback record.

        Parameters
        ----------
        feedback_id:       PK of the Feedback record to respond to.
        message_body:      Response text in English (will be translated if needed).
        language_override: Force a specific delivery language (BCP-47 code).
        user:              The NGO staff User record initiating the response.

        Returns
        -------
        {'status': 'Sent'|'Failed', 'notification_id': int}

        Raises
        ------
        FeedbackNotFoundError    – Feedback record does not exist.
        ConsentNotFoundError     – No active follow_up consent for this submission.
        """
        from apps.feedback.models import Feedback

        # 1. Fetch Feedback
        try:
            feedback = Feedback.objects.get(pk=feedback_id)
        except Feedback.DoesNotExist:
            raise FeedbackNotFoundError(
                f"Feedback #{feedback_id} does not exist."
            )

        # 2. Check consent
        consent = UserConsent.objects.filter(
            anonymous_user_id=feedback.anonymous_user_id,
            consent_type=UserConsent.ConsentType.FOLLOW_UP,
            is_active=True,
        ).first()

        if consent is None:
            raise ConsentNotFoundError(
                "This submission was anonymous. Use broadcast updates to "
                "communicate with all opted-in users instead."
            )

        # 3. Determine target language
        target_lang = language_override or feedback.language or "en"

        # 4. Translate if needed
        translated_body = self._translate(message_body, target_lang)

        # 5. Enforce SMS length limit
        if len(translated_body) > _MAX_BODY_CHARS:
            translated_body = translated_body[: _MAX_BODY_CHARS - len(_TRUNCATION_SUFFIX)] + _TRUNCATION_SUFFIX
            logger.warning(
                "ResponseComposer.send_response: Response truncated for feedback_id=%d",
                feedback_id,
            )

        # 6. Decrypt recipient phone — IN MEMORY ONLY, never log or store
        recipient = decrypt_field(consent.phone_number_encrypted)

        # 7. Create Notification record (status=Queued)
        notification = Notification.objects.create(
            feedback_id=feedback_id,
            sent_by_user=user,
            message_type=Notification.MessageType.TARGETED_RESPONSE,
            channel=consent.channel_preference,
            content=translated_body,
            delivery_language=target_lang,
            delivery_status=Notification.DeliveryStatus.QUEUED,
        )

        # 8. Send
        result = MessageRouter().send(
            channel=consent.channel_preference,
            recipient=recipient,
            body=translated_body,
            notification_record=notification,
        )

        # 9. IMMEDIATELY zero out the decrypted number
        recipient = None  # noqa: F841  — intentional privacy wipe

        # 10. Audit log
        try:
            from apps.common.audit import AuditAction
            log_audit_event(
                user=user,
                action=AuditAction.NOTIFICATION_SENT,
                feedback=feedback,
                field_changed="targeted_response",
                new_value=f"notification_id={notification.pk} lang={target_lang}",
            )
        except Exception as exc:
            logger.warning(
                "ResponseComposer.send_response: Audit log failed: %s", exc
            )

        # 11. Return result
        return {
            "status": result["status"],
            "notification_id": notification.pk,
        }

    # ------------------------------------------------------------------ #
    # Private helpers                                                      #
    # ------------------------------------------------------------------ #

    def _translate(self, text: str, target_lang: str) -> str:
        """
        Translate ``text`` from English to ``target_lang``.
        Falls back to the original text if translation fails or is not needed.
        """
        if target_lang == "en":
            return text
        try:
            from apps.nlp.services.translation_service import TranslationService  # type: ignore[import]
            return TranslationService().translate_text(text, source="en", target=target_lang)
        except Exception as exc:
            logger.warning(
                "ResponseComposer._translate: Translation to '%s' failed: %s — "
                "falling back to English.",
                target_lang,
                exc,
            )
            return text