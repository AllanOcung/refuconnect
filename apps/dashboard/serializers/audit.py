from __future__ import annotations

from rest_framework import serializers

from apps.dashboard.models import AuditLog


class AuditLogMixin:
    audit_action = None

    def log_action(
        self,
        request,
        feedback=None,
        field_changed=None,
        old_value=None,
        new_value=None,
    ):
        from apps.common.audit import log_audit_event

        if self.audit_action:
            log_audit_event(
                user=request.user,
                action=self.audit_action,
                feedback=feedback,
                field_changed=field_changed,
                old_value=str(old_value) if old_value is not None else None,
                new_value=str(new_value) if new_value is not None else None,
                request=request,
            )


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
