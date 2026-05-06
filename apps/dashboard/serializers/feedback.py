from __future__ import annotations

from rest_framework import serializers

from apps.dashboard.serializers.audit import AuditTrailSerializer
from apps.dashboard.serializers.users import FeedbackReviewedBySerializer
from apps.feedback.models import Alert, Category, Feedback, FeedbackCategory, FeedbackMedia
from apps.notifications.models import Notification


class SentimentNestedSerializer(serializers.Serializer):
    label = serializers.CharField(source="sentiment_label")
    colour = serializers.CharField(source="display_colour")


class FeedbackCategoryListSerializer(serializers.ModelSerializer):
    category_name = serializers.CharField(source="category.category_name", read_only=True)

    class Meta:
        model = FeedbackCategory
        fields = ["category_name", "confidence_score"]


class FeedbackCategoryDetailSerializer(serializers.ModelSerializer):
    category_name = serializers.CharField(source="category.category_name", read_only=True)

    class Meta:
        model = FeedbackCategory
        fields = [
            "category_name",
            "confidence_score",
            "is_ai_assigned",
            "assigned_at",
        ]


class FeedbackMediaDashboardSerializer(serializers.ModelSerializer):
    class Meta:
        model = FeedbackMedia
        fields = ["media_type", "transcript_text", "extracted_text"]


class NotificationDashboardSerializer(serializers.ModelSerializer):
    class Meta:
        model = Notification
        fields = ["message_type", "channel", "delivery_status", "sent_at"]


class FeedbackListSerializer(serializers.ModelSerializer):
    sentiment = SentimentNestedSerializer(read_only=True)
    categories = FeedbackCategoryListSerializer(
        source="feedback_categories", many=True, read_only=True
    )
    message_text = serializers.SerializerMethodField()
    has_media = serializers.BooleanField(read_only=True)

    class Meta:
        model = Feedback
        fields = [
            "feedback_id",
            "channel",
            "language",
            "language_confidence",
            "urgency_level",
            "status",
            "submitted_at",
            "is_duplicate",
            "is_flagged",
            "location",
            "sentiment",
            "categories",
            "message_text",
            "has_media",
        ]

    def get_message_text(self, obj):
        text = obj.message_text or ""
        return text[:100]


class FeedbackAlertSerializer(serializers.ModelSerializer):
    class Meta:
        model = Alert
        fields = ["alert_id", "status", "priority_level", "description"]


class FeedbackDetailSerializer(FeedbackListSerializer):
    categories = FeedbackCategoryDetailSerializer(
        source="feedback_categories", many=True, read_only=True
    )
    media = FeedbackMediaDashboardSerializer(
        source="media_files", many=True, read_only=True
    )
    notifications = NotificationDashboardSerializer(many=True, read_only=True)
    audit_trail = serializers.SerializerMethodField()
    alert = FeedbackAlertSerializer(read_only=True)
    reviewed_by = FeedbackReviewedBySerializer(read_only=True)

    class Meta(FeedbackListSerializer.Meta):
        fields = [
            "feedback_id",
            "channel",
            "language",
            "language_confidence",
            "urgency_level",
            "status",
            "submitted_at",
            "is_duplicate",
            "is_flagged",
            "flag_reason",
            "location",
            "sentiment",
            "sentiment_confidence",
            "categories",
            "message_text",
            "message_text_en",
            "processed_at",
            "reviewed_by",
            "reviewed_at",
            "media",
            "alert",
            "notifications",
            "audit_trail",
            "has_media",
        ]

    def get_message_text(self, obj):
        return obj.message_text or ""

    def get_audit_trail(self, obj):
        logs = obj.audit_logs.select_related("user").order_by("created_at")
        return AuditTrailSerializer(logs, many=True).data


class FeedbackUpdateSerializer(serializers.Serializer):
    urgency_level = serializers.ChoiceField(
        choices=Feedback.UrgencyLevel.choices, required=False
    )
    is_flagged = serializers.BooleanField(required=False)
    flag_reason = serializers.CharField(
        max_length=60, allow_blank=True, allow_null=True, required=False
    )
    categories = serializers.ListField(
        child=serializers.PrimaryKeyRelatedField(
            queryset=Category.objects.filter(is_active=True)
        ),
        required=False,
    )

    def validate(self, attrs):
        if not attrs:
            raise serializers.ValidationError("At least one editable field is required.")
        return attrs
