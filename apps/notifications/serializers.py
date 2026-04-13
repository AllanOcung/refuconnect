"""
Serializers for the notifications app.
"""
from __future__ import annotations

from rest_framework import serializers

from apps.notifications.models import Notification, UserConsent


class NotificationSerializer(serializers.ModelSerializer):
    """Read serializer for Notification records."""

    sent_by_email = serializers.CharField(source="sent_by.email", read_only=True, default=None)
    related_feedback_id = serializers.IntegerField(
        source="related_feedback.feedback_id", read_only=True, default=None
    )

    class Meta:
        model = Notification
        fields = [
            "notification_id",
            "message_type",
            "message_body",
            "delivery_status",
            "sent_by_email",
            "related_feedback_id",
            "created_at",
        ]
        read_only_fields = fields


class UserConsentSerializer(serializers.ModelSerializer):
    """Serialiser for UserConsent — never exposes encrypted phone number."""

    class Meta:
        model = UserConsent
        fields = [
            "consent_id",
            "anonymous_user_id",
            "consent_type",
            "channel_preference",
            "language_preference",
            "is_active",
            "consented_at",
        ]
        read_only_fields = ["consent_id", "consented_at"]


class SendAcknowledgementSerializer(serializers.Serializer):
    """Input validation for sending an acknowledgement."""

    feedback_id = serializers.IntegerField()
    language = serializers.CharField(max_length=5, default="en")


class SendBroadcastSerializer(serializers.Serializer):
    """Input validation for creating a broadcast."""

    message = serializers.CharField(max_length=1600)
    channel = serializers.ChoiceField(choices=UserConsent.ChannelPreference.choices)
    language = serializers.CharField(max_length=5, default="en")
    message_type = serializers.ChoiceField(
        choices=Notification.MessageType.choices,
        default=Notification.MessageType.BROADCAST_GENERAL,
    )
    broadcast_type = serializers.ChoiceField(
        choices=["broadcast_general", "broadcast_yswd"],
        default="broadcast_general",
    )
