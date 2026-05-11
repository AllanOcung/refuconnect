"""
tests/test_delivery_tracker.py
Tests for DeliveryTracker callback handling.
"""
from __future__ import annotations
from unittest.mock import MagicMock, patch
import pytest
from django.test import TestCase
from apps.notifications.models import Notification
from apps.notifications.services.delivery_tracker import DeliveryTracker


class TestDeliveryTracker(TestCase):

    def test_sms_success_callback_sets_delivered_status(self):
        notif = Notification.objects.create(
            message_type=Notification.MessageType.ACKNOWLEDGEMENT,
            channel=Notification.Channel.SMS,
            content="Hello",
            delivery_language="en",
            delivery_status=Notification.DeliveryStatus.SENT,
            gateway_message_id="ATXid_abc123",
        )

        tracker = DeliveryTracker()
        tracker.handle_sms_delivery_callback({
            "id": "ATXid_abc123",
            "status": "Success",
            "phoneNumber": "+256700000001",
            "networkCode": "63902",
            "failureReason": None,
            "retryCount": "0",
        })

        notif.refresh_from_db()
        self.assertEqual(notif.delivery_status, Notification.DeliveryStatus.DELIVERED)
        self.assertIsNotNone(notif.delivered_at)

    def test_sms_failed_callback_sets_failed_status(self):
        notif = Notification.objects.create(
            message_type=Notification.MessageType.ACKNOWLEDGEMENT,
            channel=Notification.Channel.SMS,
            content="Hello",
            delivery_language="en",
            delivery_status=Notification.DeliveryStatus.SENT,
            gateway_message_id="ATXid_xyz789",
        )

        tracker = DeliveryTracker()
        tracker.handle_sms_delivery_callback({
            "id": "ATXid_xyz789",
            "status": "Failed",
            "phoneNumber": "+256700000002",
            "networkCode": "63902",
            "failureReason": "Invalid number",
            "retryCount": "2",
        })

        notif.refresh_from_db()
        self.assertEqual(notif.delivery_status, Notification.DeliveryStatus.FAILED)

    def test_whatsapp_delivered_callback_sets_delivered_at(self):
        notif = Notification.objects.create(
            message_type=Notification.MessageType.TARGETED_RESPONSE,
            channel=Notification.Channel.WHATSAPP,
            content="Hello",
            delivery_language="en",
            delivery_status=Notification.DeliveryStatus.SENT,
            gateway_message_id="wamid.delivered123",
        )

        tracker = DeliveryTracker()
        tracker.handle_whatsapp_status_callback({
            "id": "wamid.delivered123",
            "status": "delivered",
            "timestamp": "1700000000",
            "recipient_id": "256700000003",
        })

        notif.refresh_from_db()
        self.assertEqual(notif.delivery_status, Notification.DeliveryStatus.DELIVERED)
        self.assertIsNotNone(notif.delivered_at)

    def test_whatsapp_read_callback_sets_read_at(self):
        notif = Notification.objects.create(
            message_type=Notification.MessageType.TARGETED_RESPONSE,
            channel=Notification.Channel.WHATSAPP,
            content="Hello",
            delivery_language="en",
            delivery_status=Notification.DeliveryStatus.DELIVERED,
            gateway_message_id="wamid.read456",
        )

        tracker = DeliveryTracker()
        tracker.handle_whatsapp_status_callback({
            "id": "wamid.read456",
            "status": "read",
            "timestamp": "1700000000",
            "recipient_id": "256700000004",
        })

        notif.refresh_from_db()
        self.assertEqual(notif.delivery_status, Notification.DeliveryStatus.READ)
        self.assertIsNotNone(notif.read_at)

    def test_unknown_gateway_id_logs_warning_and_returns(self):
        tracker = DeliveryTracker()
        
        with self.assertLogs("apps.notifications.delivery_tracker", level="WARNING") as cm:
            tracker.handle_sms_delivery_callback({
                "id": "UNKNOWN_ID",
                "status": "Success",
                "phoneNumber": "+256700000005",
            })
        
        self.assertTrue(any("No Notification found" in msg for msg in cm.output))

    @patch("apps.notifications.services.delivery_tracker.DeliveryTracker._handle_permanent_failure")
    def test_permanent_failure_triggers_handler(self, mock_handler):
        notif = Notification.objects.create(
            message_type=Notification.MessageType.ACKNOWLEDGEMENT,
            channel=Notification.Channel.SMS,
            content="Hello",
            delivery_language="en",
            delivery_status=Notification.DeliveryStatus.SENT,
            gateway_message_id="ATXid_fail",
        )

        tracker = DeliveryTracker()
        tracker.handle_sms_delivery_callback({
            "id": "ATXid_fail",
            "status": "Rejected",
            "phoneNumber": "+256700000006",
        })

        mock_handler.assert_called_once()