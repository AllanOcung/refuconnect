from __future__ import annotations

from rest_framework import serializers

from apps.dashboard.models import User


class InvitedBySerializer(serializers.ModelSerializer):
    """Minimal nested representation of the inviter on a User payload."""

    class Meta:
        model = User
        fields = ["user_id", "full_name", "email"]


class UserSerializer(serializers.ModelSerializer):
    mfa_enabled = serializers.SerializerMethodField()
    invited_by = InvitedBySerializer(read_only=True)

    class Meta:
        model = User
        fields = [
            "user_id",
            "full_name",
            "email",
            "role",
            "status",
            "organisation",
            "job_title",
            "avatar_url",
            "preferred_language",
            "receive_alerts",
            "alert_phone",
            "last_login_at",
            "last_seen_at",
            "mfa_enabled",
            "mfa_enabled_at",
            "password_changed_at",
            "invited_by",
            "created_at",
        ]
        read_only_fields = [
            "user_id",
            "email",
            "last_login_at",
            "last_seen_at",
            "mfa_enabled",
            "mfa_enabled_at",
            "password_changed_at",
            "invited_by",
            "created_at",
        ]

    def get_mfa_enabled(self, obj: User) -> bool:
        return bool(obj.mfa_secret)


class UserInviteSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["full_name", "email", "role", "organisation"]


class FeedbackReviewedBySerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["full_name"]


class ChangePasswordSerializer(serializers.Serializer):
    current_password = serializers.CharField(write_only=True)
    new_password = serializers.CharField(write_only=True)

    def validate_new_password(self, value: str) -> str:
        # Imported here to avoid circular import at module load.
        from apps.common.passwords import PASSWORD_POLICY_DETAIL, is_password_valid

        if not is_password_valid(value):
            raise serializers.ValidationError(PASSWORD_POLICY_DETAIL)
        return value
