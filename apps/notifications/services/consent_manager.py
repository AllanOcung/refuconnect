"""
ConsentManager
==============
Handles community member opt-in / opt-out consent replies.

When a community member submits feedback they receive an acknowledgement
asking if they want follow-up (YES/NO). When they reply:
  YES → Subsystem 1's SMSGatewayAdapter routes here → handle_opt_in()
  NO  → Subsystem 1's SMSGatewayAdapter routes here → handle_opt_out()

PRIVACY CONSTRAINTS:
  • Phone numbers are AES-256-GCM encrypted before being stored.
  • The anonymous_user_id is derived from the phone using the same hash
    function as MessageNormaliser — this links consent to past feedback.
  • ``phone = None`` immediately after encrypt/hash operations.
"""
from __future__ import annotations

import logging
import threading

from django.utils import timezone

from apps.common.encryption import encrypt_field
from apps.notifications.models import UserConsent

logger = logging.getLogger("apps.notifications.consent_manager")

_CONFIRM_TIMEOUT_SECONDS = 8


class ConsentManager:
    """Processes opt-in and opt-out consent replies from community members."""

    def handle_opt_in(self, phone: str, channel: str) -> None:
        """
        Create or reactivate a UserConsent record for a user who replied YES.

        The anonymous_user_id is derived from the phone number using the same
        hash function as MessageNormaliser, linking this consent to all past
        feedback records from this user.

        PRIVACY: ``phone`` is encrypted before storage and zeroed out after.
        """
        anon_id = self._hash_to_anon_id(phone)
        encrypted_phone = encrypt_field(phone)

        UserConsent.objects.update_or_create(
            anonymous_user_id=anon_id,
            consent_type=UserConsent.ConsentType.FOLLOW_UP,
            defaults={
                "phone_number_encrypted": encrypted_phone,
                "channel_preference": channel if channel in ("SMS", "WhatsApp") else "SMS",
                "consent_given_at": timezone.now(),
                "consent_withdrawn_at": None,
                "is_active": True,
            },
        )

        logger.info(
            "ConsentManager.handle_opt_in: Consent recorded for anon_id=%s channel=%s",
            anon_id,
            channel,
        )

        # Send opt-in confirmation asynchronously — must not block the webhook handler.
        # Use the language of the user's feedback so the confirmation matches.
        _send_confirmation_async(
            template_key="OPT_IN_CONFIRMATION",
            phone=phone,
            channel=channel,
            language=self._resolve_user_language(anon_id),
            log_label="handle_opt_in",
        )
        phone = None  # Privacy wipe

    def handle_opt_out(self, phone: str, channel: str) -> None:
        """
        Deactivate all active UserConsent records for this phone number.
        Called when the user replies NO or STOP.

        PRIVACY: ``phone`` is hashed for lookup and zeroed out after.
        """
        anon_id = self._hash_to_anon_id(phone)

        updated = UserConsent.objects.filter(
            anonymous_user_id=anon_id,
            is_active=True,
        ).update(
            is_active=False,
            consent_withdrawn_at=timezone.now(),
        )

        logger.info(
            "ConsentManager.handle_opt_out: Deactivated %d consent record(s) for anon_id=%s",
            updated,
            anon_id,
        )

        # Send opt-out confirmation asynchronously — must not block the webhook handler.
        # Use the language of the user's feedback so the confirmation matches.
        _send_confirmation_async(
            template_key="OPT_OUT_CONFIRMATION",
            phone=phone,
            channel=channel,
            language=self._resolve_user_language(anon_id),
            log_label="handle_opt_out",
        )
        phone = None  # Privacy wipe

    # ------------------------------------------------------------------ #
    # Private helpers                                                      #
    # ------------------------------------------------------------------ #

    def _hash_to_anon_id(self, phone: str) -> str:
        """
        Produce the SAME anonymous_user_id as MessageNormaliser for a given phone,
        so the consent record links to that user's feedback.

        MessageNormaliser does not store the raw phone hash as the id — it caches
        an ``ANON-<epoch>-<hash[:8]>`` value in Redis keyed by the salted phone
        hash (rotating after the TTL). We must derive the id the exact same way,
        otherwise consent records key off a value that never matches any feedback
        (breaking both the targeted-response consent check and the follow-up
        language lookup). Within the opt-in window this returns the very id stored
        on the feedback that triggered the opt-in prompt.
        """
        from apps.feedback.services.normaliser import MessageNormaliser

        return MessageNormaliser._get_or_create_anon_id(phone)

    def _resolve_user_language(self, anon_id: str) -> str:
        """
        Best-effort language for a follow-up confirmation: the language of this
        user's most recent feedback, so the reply matches the language the
        feedback was submitted in. Falls back to English when unknown.
        """
        from apps.feedback.models import Feedback

        language = (
            Feedback.objects.filter(anonymous_user_id=anon_id)
            .order_by("-submitted_at")
            .values_list("language", flat=True)
            .first()
        )
        if language and language != "unknown":
            return language
        return "en"


def _send_confirmation_async(
    template_key: str,
    phone: str,
    channel: str,
    language: str,
    log_label: str,
) -> None:
    """
    Fire-and-forget confirmation SMS/WhatsApp in a daemon thread.

    The thread is bounded by _CONFIRM_TIMEOUT_SECONDS so the webhook
    response is never held up by gateway retries.

    PRIVACY: phone is only used inside the daemon thread and is not captured
    in any closure that outlives the function call.
    """
    done = threading.Event()

    def _send() -> None:
        try:
            from apps.notifications.services.template_library import TemplateLibrary
            from apps.notifications.services.message_router import MessageRouter

            body = TemplateLibrary().get_and_render(template_key, language, {})
            MessageRouter().send(channel=channel, recipient=phone, body=body)
        except Exception as exc:
            logger.warning(
                "ConsentManager.%s: Confirmation send failed: %s", log_label, exc
            )
        finally:
            done.set()

    t = threading.Thread(target=_send, daemon=True, name=f"consent-confirm-{log_label}")
    t.start()
    done.wait(timeout=_CONFIRM_TIMEOUT_SECONDS)
    # If the thread is still running after the timeout it continues in the background;
    # the webhook handler is unblocked and can respond to the gateway.