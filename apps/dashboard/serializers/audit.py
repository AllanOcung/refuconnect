from __future__ import annotations

from rest_framework import serializers

from apps.dashboard.models import AuditLog

class AuditTrailSerializer(serializers.ModelSerializer):
    user_email = serializers.CharField(source="user.email", read_only=True, default=None)

    class Meta:
        model = AuditLog
        fields = [
            "log_id",
            "user_email",
            "action",
            "field_changed",
            "old_value",
            "new_value",
            "created_at",
        ]


class AuditLogSerializer(serializers.ModelSerializer):
    user_email = serializers.CharField(source="user.email", read_only=True, default=None)
    feedback_id = serializers.IntegerField(
        source="feedback.feedback_id", read_only=True, allow_null=True
    )

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
