"""
tests/test_broadcast_manager.py
Tests for BroadcastManager broadcast creation and recipient targeting.
"""
from __future__ import annotations
from unittest.mock import MagicMock, patch
import pytest
from django.test import TestCase
from django.utils import timezone
from apps.notifications.models import Broadcast, UserConsent
from apps.notifications.services.broadcast_manager import BroadcastManager, NoBroadcastRecipientsError
from apps.common.encryption import encrypt_field


class TestBroadcastManager(TestCase):

    def setUp(self):
        from django.contrib.auth import get_user_model
        User = get_user_model()
        self.user = User.objects.create_user(
            email="staff@test.com", full_name="Staff", password="x"
        )

    def test_create_broadcast_all_recipients(self):
        # Create some opted-in users
        for i in range(3):
            UserConsent.objects.create(
                anonymous_user_id=f"anon_{i}",
                consent_type=UserConsent.ConsentType.FOLLOW_UP,
                phone_number_encrypted=encrypt_field(f"+256700000{i:03d}"),
                channel_preference="SMS",
                consent_given_at=timezone.now(),
                is_active=True,
            )

        manager = BroadcastManager()
        broadcast = manager.create_broadcast(
            message_type="YSWD",
            body_en="Test broadcast",
            target_type="all",
            target_params={},
            channels=["SMS"],
            languages=["en"],
            user=self.user,
        )

        self.assertEqual(broadcast.total_recipients, 3)
        self.assertEqual(broadcast.status, Broadcast.Status.SCHEDULED)

    def test_create_broadcast_with_no_recipients_raises_error(self):
        manager = BroadcastManager()
        
        with self.assertRaises(NoBroadcastRecipientsError):
            manager.create_broadcast(
                message_type="YSWD",
                body_en="Test broadcast",
                target_type="all",
                target_params={},
                channels=["SMS"],
                languages=["en"],
                user=self.user,
            )

    def test_create_broadcast_by_location_filters_correctly(self):
        from apps.feedback.models import Feedback
        
        # Create feedback from Bidibidi
        fb1 = Feedback.objects.create(
            anonymous_user_id="anon_bidibidi_1",
            location="Bidibidi Zone 1",
            channel="SMS",
            message_text="Feedback",
            submitted_at=timezone.now(),
        )
        
        # Create opted-in user for that feedback
        UserConsent.objects.create(
            anonymous_user_id="anon_bidibidi_1",
            consent_type=UserConsent.ConsentType.FOLLOW_UP,
            phone_number_encrypted=encrypt_field("+256700000001"),
            channel_preference="SMS",
            consent_given_at=timezone.now(),
            is_active=True,
        )

        manager = BroadcastManager()
        broadcast = manager.create_broadcast(
            message_type="YSWD",
            body_en="Bidibidi broadcast",
            target_type="by_location",
            target_params={"settlement": "Bidibidi"},
            channels=["SMS"],
            languages=["en"],
            user=self.user,
        )

        self.assertEqual(broadcast.total_recipients, 1)

    def test_scheduled_broadcast_not_dispatched_immediately(self):
        UserConsent.objects.create(
            anonymous_user_id="anon_1",
            consent_type=UserConsent.ConsentType.FOLLOW_UP,
            phone_number_encrypted=encrypt_field("+256700000001"),
            channel_preference="SMS",
            consent_given_at=timezone.now(),
            is_active=True,
        )

        manager = BroadcastManager()
        future_time = timezone.now() + timezone.timedelta(hours=1)

        with patch("apps.notifications.tasks.dispatch_broadcast") as mock_task:
            broadcast = manager.create_broadcast(
                message_type="YSWD",
                body_en="Scheduled broadcast",
                target_type="all",
                target_params={},
                channels=["SMS"],
                languages=["en"],
                schedule_at=future_time,
                user=self.user,
            )

        self.assertEqual(broadcast.status, Broadcast.Status.SCHEDULED)
        # Verify apply_async was called (scheduled task)
        mock_task.apply_async.assert_called_once()

    def test_immediate_broadcast_triggers_celery_task(self):
        UserConsent.objects.create(
            anonymous_user_id="anon_1",
            consent_type=UserConsent.ConsentType.FOLLOW_UP,
            phone_number_encrypted=encrypt_field("+256700000001"),
            channel_preference="SMS",
            consent_given_at=timezone.now(),
            is_active=True,
        )

        manager = BroadcastManager()

        with patch("apps.notifications.tasks.dispatch_broadcast") as mock_task:
            broadcast = manager.create_broadcast(
                message_type="YSWD",
                body_en="Immediate broadcast",
                target_type="all",
                target_params={},
                channels=["SMS"],
                languages=["en"],
                user=self.user,
            )

        # Verify delay() was called (immediate task)
        mock_task.delay.assert_called_once()

    def test_estimate_returns_recipient_count_without_creating_record(self):
        UserConsent.objects.create(
            anonymous_user_id="anon_1",
            consent_type=UserConsent.ConsentType.FOLLOW_UP,
            phone_number_encrypted=encrypt_field("+256700000001"),
            channel_preference="SMS",
            consent_given_at=timezone.now(),
            is_active=True,
        )
        UserConsent.objects.create(
            anonymous_user_id="anon_2",
            consent_type=UserConsent.ConsentType.FOLLOW_UP,
            phone_number_encrypted=encrypt_field("+256700000002"),
            channel_preference="SMS",
            consent_given_at=timezone.now(),
            is_active=True,
        )

        manager = BroadcastManager()
        count = manager.estimate_recipients(
            target_type="all",
            target_params={},
        )

        self.assertEqual(count, 2)
        # Verify no Broadcast was created
        self.assertEqual(Broadcast.objects.count(), 0)