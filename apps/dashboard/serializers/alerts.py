from __future__ import annotations

from rest_framework import serializers

from apps.dashboard.models import User
from apps.feedback.models import Alert, Feedback


class AlertFeedbackSnippetSerializer(serializers.ModelSerializer):
    message_text_en = serializers.SerializerMethodField()
    categories = serializers.SerializerMethodField()

    class Meta:
        model = Feedback
        fields = ["channel", "location", "urgency_level", "message_text_en", "categories"]

    def get_message_text_en(self, obj):
        return (obj.message_text_en or obj.message_text or "")[:80]

    def get_categories(self, obj):
        return [
            fc.category.category_name
            for fc in obj.feedback_categories.all()
            if fc.category_id
        ]


class AlertAcknowledgedBySerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["full_name"]


class AlertSerializer(serializers.ModelSerializer):
    feedback_id = serializers.IntegerField(source="feedback.feedback_id", read_only=True)
    acknowledged_by = AlertAcknowledgedBySerializer(read_only=True)
    feedback = AlertFeedbackSnippetSerializer(read_only=True)

    class Meta:
        model = Alert
        fields = [
            "alert_id",
            "feedback_id",
            "priority_level",
            "description",
            "status",
            "created_at",
            "acknowledged_by",
            "acknowledged_at",
            "feedback",
        ]
        read_only_fields = fields
