"""
Serializers for the dashboard app.
"""
from __future__ import annotations

from rest_framework import serializers

from apps.dashboard.models import AuditLog, User
from apps.feedback.models import Alert


class UserSerializer(serializers.ModelSerializer):
    """Read serializer for User objects."""

    class Meta:
        model = User
        fields = [
            "user_id",
            "email",
            "full_name",
            "role",
            "status",
            "organisation",
            "created_at",
            "last_login_at",
        ]
        read_only_fields = ["user_id", "created_at"]


class UserCreateSerializer(serializers.ModelSerializer):
    """Create serializer — accepts password, enforces minimum length."""

    password = serializers.CharField(write_only=True, min_length=12)

    class Meta:
        model = User
        fields = ["email", "full_name", "role", "organisation", "password"]

    def create(self, validated_data):
        password = validated_data.pop("password")
        user = User(**validated_data)
        user.set_password(password)
        user.status = User.Status.ACTIVE
        user.save()
        return user


class AuditLogSerializer(serializers.ModelSerializer):
    """Read-only serialiser for AuditLog entries."""

    user_email = serializers.CharField(source="user.email", read_only=True, default=None)
    feedback_id = serializers.IntegerField(source="feedback.feedback_id", read_only=True, default=None)

    class Meta:
        model = AuditLog
        fields = [
            "log_id",
            "user_email",
            "action",
            "feedback_id",
            "field_changed",
            "old_value",
            "new_value",
            "ip_address",
            "user_agent",
            "created_at",
        ]
        read_only_fields = fields


class AlertSerializer(serializers.ModelSerializer):
    """Serialiser for Alert objects."""

    feedback_id = serializers.IntegerField(source="feedback.feedback_id", read_only=True)
    acknowledged_by_email = serializers.CharField(
        source="acknowledged_by.email", read_only=True, default=None
    )

    class Meta:
        model = Alert
        fields = [
            "alert_id",
            "feedback_id",
            "priority",
            "alert_status",
            "alert_message",
            "acknowledged_by_email",
            "created_at",
        ]
        read_only_fields = fields
