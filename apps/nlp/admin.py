from django.contrib import admin
from .models import AIModelLog, ThemeCluster


@admin.register(AIModelLog)
class AIModelLogAdmin(admin.ModelAdmin):
    list_display = ["model_log_id", "model_type", "model_version", "trained_by", "trained_at"]
    list_filter = ["model_type"]
    readonly_fields = ["model_log_id"]
    ordering = ["-trained_at"]


@admin.register(ThemeCluster)
class ThemeClusterAdmin(admin.ModelAdmin):
    list_display = ["cluster_id", "week_start_date", "cluster_label", "feedback_count", "generated_at"]
    list_filter = ["week_start_date"]
    readonly_fields = ["cluster_id", "generated_at"]
    ordering = ["-week_start_date", "-feedback_count"]
