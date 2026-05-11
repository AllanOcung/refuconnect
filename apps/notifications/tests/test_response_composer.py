"""
tests/test_response_composer.py — fixed version
"""
from __future__ import annotations
from unittest.mock import MagicMock, patch
from django.test import TestCase
from django.utils import timezone
from apps.common.exceptions import ConsentNotFoundError
from apps.notifications.models import Notification, UserConsent
from apps.notifications.services.response_composer import (
    FeedbackNotFoundError,
    ResponseComposer,
)


def make_feedback(anon_id="anon_rc_001", language="en"):
    from apps.feedback.models import Feedback
    return Feedback.objects.create(
        anonymous_user_id=anon_id,
        message_text="Test feedback message",
        channel="SMS",
        language=language,
        submitted_at=timezone.now(),
    )


def make_consent(feedback, channel="SMS", encrypted_phone=None):
    if encrypted_phone is None:
        from apps.common.encryption import encrypt_field
        encrypted_phone = encrypt_field("+256700000001")
    return UserConsent.objects.create(
        anonymous_user_id=feedback.anonymous_user_id,
        phone_number_encrypted=encrypted_phone,
        consent_type=UserConsent.ConsentType.FOLLOW_UP,
        channel_preference=channel,
        consent_given_at=timezone.now(),
        is_active=True,
    )


class TestResponseComposer(TestCase):

    # Patch MessageRouter where it is *instantiated* — inside the method
    ROUTER_PATH = "apps.notifications.services.response_composer.MessageRouter"

    @patch(ROUTER_PATH)
    def test_send_response_to_opted_in_user_succeeds(self, MockRouter):
        MockRouter.return_value.send.return_value = {"status": "Sent", "gateway_message_id": "X1"}
        fb = make_feedback()
        make_consent(fb)
        result = ResponseComposer().send_response(fb.pk, "We heard you.")
        self.assertEqual(result["status"], "Sent")
        self.assertIn("notification_id", result)

    def test_send_response_to_nonexistent_feedback_raises_error(self):
        with self.assertRaises(FeedbackNotFoundError):
            ResponseComposer().send_response(99999, "Hello")

    def test_send_response_without_consent_raises_error(self):
        fb = make_feedback(anon_id="anon_no_consent")
        with self.assertRaises(ConsentNotFoundError):
            ResponseComposer().send_response(fb.pk, "Hello")

    @patch(ROUTER_PATH)
    def test_message_translated_to_recipient_language(self, MockRouter):
        MockRouter.return_value.send.return_value = {"status": "Sent", "gateway_message_id": "X2"}
        fb = make_feedback(language="sw")
        make_consent(fb)
        with patch("apps.notifications.services.response_composer.ResponseComposer._translate",
                   return_value="Translated text") as mock_translate:
            ResponseComposer().send_response(fb.pk, "We heard you.")
            mock_translate.assert_called_once_with("We heard you.", "sw")

    @patch(ROUTER_PATH)
    def test_language_override_used_when_provided(self, MockRouter):
        MockRouter.return_value.send.return_value = {"status": "Sent", "gateway_message_id": "X3"}
        fb = make_feedback(language="en")
        make_consent(fb)
        with patch("apps.notifications.services.response_composer.ResponseComposer._translate",
                   return_value="Luganda text") as mock_translate:
            ResponseComposer().send_response(fb.pk, "Hello", language_override="lg")
            mock_translate.assert_called_once_with("Hello", "lg")

    @patch(ROUTER_PATH)
    def test_message_truncated_at_640_chars(self, MockRouter):
        MockRouter.return_value.send.return_value = {"status": "Sent", "gateway_message_id": "X4"}
        fb = make_feedback()
        make_consent(fb)
        long_message = "A" * 700
        ResponseComposer().send_response(fb.pk, long_message)
        notif = Notification.objects.filter(
            feedback=fb,
            message_type=Notification.MessageType.TARGETED_RESPONSE,
        ).first()
        self.assertIsNotNone(notif)
        self.assertLessEqual(len(notif.content), 640)
        self.assertTrue(notif.content.endswith("..."))

    @patch(ROUTER_PATH)
    def test_decrypted_phone_not_stored_or_logged(self, MockRouter):
        MockRouter.return_value.send.return_value = {"status": "Sent", "gateway_message_id": "X5"}
        fb = make_feedback()
        make_consent(fb)
        import logging
        logger = logging.getLogger("apps.notifications.response_composer")
        with patch.object(logger, "warning") as mock_warn, \
             patch.object(logger, "error") as mock_err:
            ResponseComposer().send_response(fb.pk, "Hello")
            for call in mock_warn.call_args_list + mock_err.call_args_list:
                for arg in call.args:
                    self.assertNotIn("256700000001", str(arg))

    @patch(ROUTER_PATH)
    def test_audit_log_written_on_response_sent(self, MockRouter):
        MockRouter.return_value.send.return_value = {"status": "Sent", "gateway_message_id": "X6"}
        fb = make_feedback()
        make_consent(fb)
        with patch("apps.notifications.services.response_composer.log_audit_event") as mock_audit:
            ResponseComposer().send_response(fb.pk, "We heard you.")
            mock_audit.assert_called_once()

    @patch(ROUTER_PATH)
    def test_notification_record_created_before_dispatch(self, MockRouter):
        MockRouter.return_value.send.return_value = {"status": "Sent", "gateway_message_id": "X7"}
        fb = make_feedback()
        make_consent(fb)
        ResponseComposer().send_response(fb.pk, "Hello")
        notif = Notification.objects.filter(
            feedback=fb,
            message_type=Notification.MessageType.TARGETED_RESPONSE,
        ).first()
        self.assertIsNotNone(notif)
        self.assertEqual(notif.delivery_language, "en")