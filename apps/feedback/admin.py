from django.contrib import admin

from .models import Alert, Category, Feedback, FeedbackCategory, FeedbackMedia, Sentiment


@admin.register(Sentiment)
class SentimentAdmin(admin.ModelAdmin):
    list_display = ["sentiment_id", "sentiment_label", "display_colour"]
    search_fields = ["sentiment_label"]


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ["category_id", "category_name", "is_active", "created_at"]
    list_filter = ["is_active"]
    search_fields = ["category_name"]


class FeedbackCategoryInline(admin.TabularInline):
    model = FeedbackCategory
    extra = 0
    readonly_fields = ["assigned_at"]


class FeedbackMediaInline(admin.TabularInline):
    model = FeedbackMedia
    extra = 0
    readonly_fields = ["created_at"]


@admin.register(Feedback)
class FeedbackAdmin(admin.ModelAdmin):
    list_display = [
        "feedback_id",
        "channel",
        "language",
        "urgency_level",
        "status",
        "is_flagged",
        "is_duplicate",
        "submitted_at",
    ]
    list_filter = ["channel", "status", "urgency_level", "is_flagged", "is_duplicate", "language"]
    search_fields = ["anonymous_user_id", "message_text", "location"]
    readonly_fields = [
        "feedback_id",
        "submitted_at",
        "processed_at",
        "language",
        "language_confidence",
        "message_text_en",
    ]
    inlines = [FeedbackCategoryInline, FeedbackMediaInline]
    date_hierarchy = "submitted_at"


@admin.register(Alert)
class AlertAdmin(admin.ModelAdmin):
    list_display = ["alert_id", "feedback", "priority_level", "status", "created_at"]
    list_filter = ["status", "priority_level"]
    readonly_fields = ["alert_id", "created_at"]
