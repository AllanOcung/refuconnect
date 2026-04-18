from django.contrib import admin

from .models import AIModelLog, FeedbackCluster, ThemeCluster


@admin.register(AIModelLog)
class AIModelLogAdmin(admin.ModelAdmin):
    list_display = (
        "model_log_id", "model_type", "model_version",
        "trained_by", "trained_at", "deployed",
        "accuracy_english", "accuracy_swahili", "accuracy_local_lang",
        "correction_records_used",
    )
    list_filter = ("model_type", "deployed")
    readonly_fields = ("model_log_id", "trained_at", "bias_test_results")
    ordering = ("-trained_at",)


@admin.register(ThemeCluster)
class ThemeClusterAdmin(admin.ModelAdmin):
    list_display = (
        "cluster_id", "week_start_date", "cluster_index",
        "cluster_label", "feedback_count", "dominant_sentiment", "generated_at",
    )
    list_filter = ("week_start_date", "dominant_sentiment")
    readonly_fields = ("cluster_id", "generated_at")
    ordering = ("-week_start_date", "-feedback_count")


@admin.register(FeedbackCluster)
class FeedbackClusterAdmin(admin.ModelAdmin):
    list_display = ("feedback_id", "cluster", "week_start_date", "assigned_at")
    list_filter = ("week_start_date",)
    raw_id_fields = ("feedback", "cluster")
    readonly_fields = ("assigned_at",)
    ordering = ("-assigned_at",)