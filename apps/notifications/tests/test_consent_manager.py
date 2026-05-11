from __future__ import annotations

from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from apps.common.encryption import decrypt_field
from apps.notifications.models import UserConsent
from apps.notifications.services.consent_manager import ConsentManager


class TestConsentManager(TestCase):
    PHONE = "+256700000111"

    def setUp(self):
        self.manager = ConsentManager()

    @patch("apps.notifications.services.message_router.MessageRouter.send")
    @patch("apps.notifications.services.template_library.TemplateLibrary.get_and_render")
    def test_opt_in_creates_consent_with_encrypted_phone(self, mock_get_and_render, mock_send):
        mock_get_and_render.return_value = "Opt-in saved"
        mock_send.return_value = {"status": "Sent", "gateway_message_id": "gw-1"}

        self.manager.handle_opt_in(self.PHONE, "SMS")

        anon_id = self.manager._hash_to_anon_id(self.PHONE)
        consent = UserConsent.objects.get(
            anonymous_user_id=anon_id,
            consent_type=UserConsent.ConsentType.FOLLOW_UP,
        )

        self.assertTrue(consent.is_active)
        self.assertEqual(consent.channel_preference, "SMS")
        self.assertNotEqual(consent.phone_number_encrypted, self.PHONE)
        self.assertEqual(decrypt_field(consent.phone_number_encrypted), self.PHONE)

    @patch("apps.notifications.services.message_router.MessageRouter.send")
    @patch("apps.notifications.services.template_library.TemplateLibrary.get_and_render")
    def test_opt_in_reactivates_withdrawn_consent(self, mock_get_and_render, mock_send):
        mock_get_and_render.return_value = "Opt-in saved"
        mock_send.return_value = {"status": "Sent", "gateway_message_id": "gw-2"}

        anon_id = self.manager._hash_to_anon_id(self.PHONE)
        UserConsent.objects.create(
            anonymous_user_id=anon_id,
            phone_number_encrypted="placeholder",
            consent_type=UserConsent.ConsentType.FOLLOW_UP,
            channel_preference="SMS",
            consent_given_at=timezone.now(),
            consent_withdrawn_at=timezone.now(),
            is_active=False,
        )

        self.manager.handle_opt_in(self.PHONE, "WhatsApp")

        consent = UserConsent.objects.get(
            anonymous_user_id=anon_id,
            consent_type=UserConsent.ConsentType.FOLLOW_UP,
        )
        self.assertTrue(consent.is_active)
        self.assertEqual(consent.channel_preference, "WhatsApp")
        self.assertIsNone(consent.consent_withdrawn_at)
        self.assertEqual(decrypt_field(consent.phone_number_encrypted), self.PHONE)

    @patch("apps.notifications.services.message_router.MessageRouter.send")
    @patch("apps.notifications.services.template_library.TemplateLibrary.get_and_render")
    def test_opt_out_deactivates_active_consents(self, mock_get_and_render, mock_send):
        mock_get_and_render.return_value = "Opt-out saved"
        mock_send.return_value = {"status": "Sent", "gateway_message_id": "gw-3"}

        anon_id = self.manager._hash_to_anon_id(self.PHONE)
        UserConsent.objects.create(
            anonymous_user_id=anon_id,
            phone_number_encrypted="enc-1",
            consent_type=UserConsent.ConsentType.FOLLOW_UP,
            channel_preference="SMS",
            consent_given_at=timezone.now(),
            is_active=True,
        )
        UserConsent.objects.create(
            anonymous_user_id=anon_id,
            phone_number_encrypted="enc-2",
            consent_type=UserConsent.ConsentType.SURVEY,
            channel_preference="SMS",
            consent_given_at=timezone.now(),
            is_active=True,
        )

        self.manager.handle_opt_out(self.PHONE, "SMS")

        self.assertFalse(
            UserConsent.objects.filter(anonymous_user_id=anon_id, is_active=True).exists()
        )
        self.assertEqual(
            UserConsent.objects.filter(anonymous_user_id=anon_id, consent_withdrawn_at__isnull=False).count(),
            2,
        )

    @patch("apps.notifications.services.message_router.MessageRouter.send")
    @patch("apps.notifications.services.template_library.TemplateLibrary.get_and_render")
    def test_opt_in_sends_confirmation_message(self, mock_get_and_render, mock_send):
        mock_get_and_render.return_value = "You are now opted in"
        mock_send.return_value = {"status": "Sent", "gateway_message_id": "gw-4"}

        self.manager.handle_opt_in(self.PHONE, "SMS")

        mock_get_and_render.assert_called_once_with("OPT_IN_CONFIRMATION", "en", {})
        mock_send.assert_called_once_with(
            channel="SMS", recipient=self.PHONE, body="You are now opted in"
        )
