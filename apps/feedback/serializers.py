from rest_framework import serializers

from .models import Alert, Category, Feedback, FeedbackCategory, FeedbackMedia, Sentiment


class SentimentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Sentiment
        fields = ["sentiment_id", "sentiment_label", "display_colour"]


class CategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = Category
        fields = ["category_id", "category_name", "description", "is_active"]


class FeedbackCategorySerializer(serializers.ModelSerializer):
    category_name = serializers.ReadOnlyField(source="category.category_name")

    class Meta:
        model = FeedbackCategory
        fields = [
            "fc_id",
            "category",
            "category_name",
            "confidence_score",
            "is_ai_assigned",
            "assigned_at",
        ]


class FeedbackMediaSerializer(serializers.ModelSerializer):
    class Meta:
        model = FeedbackMedia
        fields = [
            "media_id",
            "media_type",
            "storage_path",
            "file_size_bytes",
            "transcript_text",
            "created_at",
        ]


class AlertSerializer(serializers.ModelSerializer):
    class Meta:
        model = Alert
        fields = [
            "alert_id",
            "feedback",
            "priority_level",
            "description",
            "status",
            "acknowledged_by",
            "acknowledged_at",
            "created_at",
        ]
        read_only_fields = ["alert_id", "created_at"]


class FeedbackListSerializer(serializers.ModelSerializer):
    """Lightweight serializer for list views."""

    sentiment_label = serializers.ReadOnlyField(source="sentiment.sentiment_label")

    class Meta:
        model = Feedback
        fields = [
            "feedback_id",
            "channel",
            "language",
            "urgency_level",
            "status",
            "is_flagged",
            "is_duplicate",
            "sentiment_label",
            "location",
            "submitted_at",
        ]


class FeedbackDetailSerializer(serializers.ModelSerializer):
    """Full serializer for create / retrieve operations."""

    sentiment_label = serializers.ReadOnlyField(source="sentiment.sentiment_label")
    categories = FeedbackCategorySerializer(
        source="feedback_categories", many=True, read_only=True
    )
    media_files = FeedbackMediaSerializer(many=True, read_only=True)

    class Meta:
        model = Feedback
        fields = [
            "feedback_id",
            "anonymous_user_id",
            "message_text",
            "message_text_en",
            "language",
            "language_confidence",
            "sentiment",
            "sentiment_label",
            "sentiment_confidence",
            "urgency_level",
            "channel",
            "location",
            "status",
            "is_flagged",
            "flag_reason",
            "is_duplicate",
            "submitted_at",
            "processed_at",
            "reviewed_by",
            "reviewed_at",
            "categories",
            "media_files",
        ]
        read_only_fields = [
            "feedback_id",
            "message_text_en",
            "language",
            "language_confidence",
            "sentiment",
            "sentiment_label",
            "sentiment_confidence",
            "status",
            "is_duplicate",
            "processed_at",
        ]


class SMSInboundSerializer(serializers.Serializer):
    """Validates Africa's Talking inbound SMS webhook."""

    from_number = serializers.CharField(source="from", max_length=20)
    text = serializers.CharField()
    to = serializers.CharField(max_length=20, required=False, default="")
    date = serializers.CharField(required=False, default="")
    linkId = serializers.CharField(required=False, default="")  # noqa: N815


class USSDInboundSerializer(serializers.Serializer):
    """Validates Africa's Talking inbound USSD webhook."""

    sessionId = serializers.CharField()  # noqa: N815
    phoneNumber = serializers.CharField()  # noqa: N815
    text = serializers.CharField(allow_blank=True, default="")
    serviceCode = serializers.CharField()  # noqa: N815
    networkCode = serializers.CharField(required=False, default="")  # noqa: N815


class WhatsAppInboundSerializer(serializers.Serializer):
    """Validates the outer WhatsApp webhook envelope."""

    object = serializers.CharField()
    entry = serializers.ListField(child=serializers.DictField())

    def validate_object(self, value: str) -> str:
        if value != "whatsapp_business_account":
            raise serializers.ValidationError(
                "Unexpected webhook object type."
            )
        return value
