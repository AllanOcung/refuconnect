"""
Serializers for the notifications app.
"""
from __future__ import annotations

from rest_framework import serializers

from apps.notifications.models import Broadcast, MessageTemplate, Notification, UserConsent


# ─── Notification ─────────────────────────────────────────────────────────────

class NotificationSerializer(serializers.ModelSerializer):
    """Read serializer for Notification records."""

    sent_by_full_name = serializers.CharField(
        source="sent_by_user.full_name", read_only=True, default=None
    )

    class Meta:
        model = Notification
        fields = [
            "notification_id",
            "message_type",
            "content",
            "delivery_language",
            "channel",
            "delivery_status",
            "sent_by_full_name",
            "retry_count",
            "sent_at",
            "delivered_at",
            "read_at",
        ]
        read_only_fields = fields


class FeedbackResponseSerializer(serializers.ModelSerializer):
    """Serializer for targeted-response notifications on a specific feedback."""

    sent_by_full_name = serializers.CharField(
        source="sent_by_user.full_name", read_only=True, default=None
    )

    class Meta:
        model = Notification
        fields = [
            "notification_id",
            "sent_by_full_name",
            "content",
            "delivery_language",
            "delivery_status",
            "sent_at",
            "delivered_at",
            "read_at",
        ]
        read_only_fields = fields


# ─── Templates ────────────────────────────────────────────────────────────────

class MessageTemplateSerializer(serializers.ModelSerializer):
    """Read/write serializer for MessageTemplate — used by admin CRUD endpoints."""

    created_by_email = serializers.CharField(
        source="created_by.email", read_only=True, default=None
    )

    class Meta:
        model = MessageTemplate
        fields = [
            "template_id",
            "template_key",
            "language",
            "body",
            "is_active",
            "is_system",
            "created_by_email",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["template_id", "is_system", "created_by_email", "created_at", "updated_at"]

    def validate(self, attrs):
        # Prevent changing template_key or language on update (unique_together enforced by DB)
        return attrs


class MessageTemplateUpdateSerializer(serializers.ModelSerializer):
    """PATCH serializer — only body and is_active can be updated."""

    class Meta:
        model = MessageTemplate
        fields = ["body", "is_active"]


# ─── Broadcasts ───────────────────────────────────────────────────────────────

class BroadcastListSerializer(serializers.ModelSerializer):
    """Compact serializer for broadcast list view."""

    created_by_full_name = serializers.CharField(
        source="created_by.full_name", read_only=True, default=None
    )

    class Meta:
        model = Broadcast
        fields = [
            "broadcast_id",
            "message_type",
            "status",
            "total_recipients",
            "sent_count",
            "failed_count",
            "created_by_full_name",
            "created_at",
            "scheduled_at",
            "completed_at",
        ]
        read_only_fields = fields


class BroadcastDetailSerializer(serializers.ModelSerializer):
    """Full broadcast detail including all fields."""

    created_by_full_name = serializers.CharField(
        source="created_by.full_name", read_only=True, default=None
    )

    class Meta:
        model = Broadcast
        fields = "__all__"
        read_only_fields = [
            "broadcast_id", "status", "started_at", "completed_at",
            "total_recipients", "sent_count", "delivered_count", "failed_count",
            "created_at", "updated_at",
        ]


class BroadcastCreateSerializer(serializers.Serializer):
    """Input serializer for POST /api/v1/broadcasts/."""

    message_type = serializers.ChoiceField(choices=Broadcast.MessageType.choices)
    body_en = serializers.CharField()
    target_type = serializers.ChoiceField(choices=Broadcast.TargetType.choices)
    target_params = serializers.DictField(default=dict)
    channels = serializers.ListField(
        child=serializers.ChoiceField(choices=["SMS", "WhatsApp"]),
        min_length=1,
    )
    languages = serializers.ListField(
        child=serializers.CharField(max_length=10),
        min_length=1,
    )
    schedule_at = serializers.DateTimeField(required=False, allow_null=True, default=None)


class BroadcastProgressSerializer(serializers.ModelSerializer):
    """Live progress polling serializer."""

    class Meta:
        model = Broadcast
        fields = ["broadcast_id", "status", "total_recipients", "sent_count", "failed_count"]
        read_only_fields = fields


class BroadcastEstimateSerializer(serializers.Serializer):
    """Input serializer for GET /api/v1/broadcasts/estimate/."""

    target_type = serializers.ChoiceField(choices=Broadcast.TargetType.choices)
    target_params = serializers.DictField(default=dict)


# ─── Send response ────────────────────────────────────────────────────────────

class SendResponseSerializer(serializers.Serializer):
    """Input validation for POST /api/v1/feedback/{id}/respond/."""

    message_body = serializers.CharField(max_length=2000)
    language_override = serializers.CharField(max_length=10, required=False, allow_null=True, default=None)


# ─── Consent ──────────────────────────────────────────────────────────────────

class UserConsentSerializer(serializers.ModelSerializer):
    """Read serializer for UserConsent — never exposes the encrypted phone number."""

    class Meta:
        model = UserConsent
        fields = [
            "consent_id",
            "anonymous_user_id",
            "consent_type",
            "channel_preference",
            "is_active",
            "consent_given_at",
            "consent_withdrawn_at",
        ]
        read_only_fields = fields