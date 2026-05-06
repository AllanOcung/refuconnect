from __future__ import annotations

from rest_framework import serializers

from apps.dashboard.models import User


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = [
            "user_id",
            "full_name",
            "email",
            "role",
            "status",
            "organisation",
            "preferred_language",
            "receive_alerts",
            "alert_phone",
            "last_login_at",
            "created_at",
        ]
        read_only_fields = ["user_id", "last_login_at", "created_at"]


class UserInviteSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["full_name", "email", "role", "organisation"]


class FeedbackReviewedBySerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["full_name"]
