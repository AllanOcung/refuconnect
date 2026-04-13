from rest_framework import serializers
from .models import AIModelLog, ThemeCluster


class AIModelLogSerializer(serializers.ModelSerializer):
    class Meta:
        model = AIModelLog
        fields = [
            "model_log_id", "model_type", "model_version",
            "training_data_summary", "accuracy_english",
            "accuracy_swahili", "accuracy_local_lang",
            "bias_test_results", "trained_by", "trained_at",
        ]
        read_only_fields = ["model_log_id"]


class ThemeClusterSerializer(serializers.ModelSerializer):
    class Meta:
        model = ThemeCluster
        fields = [
            "cluster_id", "week_start_date", "cluster_label",
            "feedback_count", "avg_sentiment", "top_keywords", "generated_at",
        ]
        read_only_fields = ["cluster_id", "generated_at"]
