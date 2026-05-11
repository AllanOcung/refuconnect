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

from django.utils import timezone

from apps.common.encryption import encrypt_field
from apps.notifications.models import UserConsent

logger = logging.getLogger("apps.notifications.consent_manager")


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

        # Send opt-in confirmation — do NOT log recipient
        try:
            from apps.notifications.services.template_library import TemplateLibrary
            from apps.notifications.services.message_router import MessageRouter

            confirmation = TemplateLibrary().get_and_render(
                "OPT_IN_CONFIRMATION", "en", {}
            )
            MessageRouter().send(channel=channel, recipient=phone, body=confirmation)
        except Exception as exc:
            logger.warning(
                "ConsentManager.handle_opt_in: Confirmation send failed: %s", exc
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

        # Send opt-out confirmation
        try:
            from apps.notifications.services.template_library import TemplateLibrary
            from apps.notifications.services.message_router import MessageRouter

            confirmation = TemplateLibrary().get_and_render(
                "OPT_OUT_CONFIRMATION", "en", {}
            )
            MessageRouter().send(channel=channel, recipient=phone, body=confirmation)
        except Exception as exc:
            logger.warning(
                "ConsentManager.handle_opt_out: Confirmation send failed: %s", exc
            )

        phone = None  # Privacy wipe

    # ------------------------------------------------------------------ #
    # Private helpers                                                      #
    # ------------------------------------------------------------------ #

    def _hash_to_anon_id(self, phone: str) -> str:
        """
        Produce the same anonymous_user_id as MessageNormaliser for a given phone.
        Uses the same SALT and hash function, linking consent to past feedback.
        """
        from django.conf import settings
        from apps.common.utils import hash_phone_number

        return hash_phone_number(phone, settings.PHONE_HASH_SALT)