from __future__ import annotations

from django.db import models
from django.utils import timezone


class AIModelLog(models.Model):

    class ModelType(models.TextChoices):
        TOPIC_CLASSIFIER = "topic_classifier", "Topic Classifier"
        SENTIMENT_ANALYSER = "sentiment_analyser", "Sentiment Analyser"
        LANGUAGE_DETECTOR = "language_detector", "Language Detector"

    model_log_id = models.AutoField(primary_key=True)
    model_type = models.CharField(
        max_length=50,
        choices=ModelType.choices,
        db_index=True,
    )
    model_version = models.CharField(max_length=32)
    trained_at = models.DateTimeField(default=timezone.now)
    trained_by = models.CharField(max_length=100)
    deployed = models.BooleanField(default=False)

    accuracy_english = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    accuracy_swahili = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    accuracy_local_lang = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)

    training_samples = models.IntegerField(default=0)
    validation_samples = models.IntegerField(default=0)
    correction_records_used = models.IntegerField(default=0)
    training_data_summary = models.TextField(blank=True)

    bias_test_results = models.JSONField(default=dict, null=True, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        db_table = "rc_ai_model_log"
        verbose_name = "AI Model Log"
        verbose_name_plural = "AI Model Logs"
        ordering = ["-trained_at"]
        indexes = [
            models.Index(fields=["model_type", "trained_at"], name="idx_ailog_type_date"),
        ]

    def __str__(self) -> str:
        status = "deployed" if self.deployed else "not deployed"
        return f"{self.model_type} v{self.model_version} ({status})"


class ThemeCluster(models.Model):

    cluster_id = models.AutoField(primary_key=True)
    week_start_date = models.DateField(db_index=True)
    cluster_index = models.IntegerField()
    cluster_label = models.CharField(max_length=256)
    feedback_count = models.IntegerField(default=0)
    dominant_sentiment = models.CharField(max_length=32, blank=True)
    top_keywords = models.JSONField(
        default=list,
        help_text="Top TF-IDF keywords for this cluster.",
    )
    generated_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "rc_theme_cluster"
        verbose_name = "Theme Cluster"
        verbose_name_plural = "Theme Clusters"
        unique_together = ("week_start_date", "cluster_index")
        ordering = ["-week_start_date", "-feedback_count"]
        indexes = [
            models.Index(fields=["week_start_date"], name="idx_cluster_week"),
        ]

    def __str__(self) -> str:
        return f"[{self.week_start_date}] Cluster {self.cluster_index}: {self.cluster_label} ({self.feedback_count} items)"


class FeedbackCluster(models.Model):
   

    feedback = models.ForeignKey(
        "feedback.Feedback",
        on_delete=models.CASCADE,
        related_name="cluster_assignments",
    )
    cluster = models.ForeignKey(
        ThemeCluster,
        on_delete=models.CASCADE,
        related_name="feedback_assignments",
    )
    week_start_date = models.DateField(db_index=True)
    assigned_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "rc_feedback_cluster"
        verbose_name = "Feedback Cluster Assignment"
        verbose_name_plural = "Feedback Cluster Assignments"
        unique_together = ("feedback", "week_start_date")

    def __str__(self) -> str:
        return f"Feedback#{self.feedback_id} → Cluster#{self.cluster_id} ({self.week_start_date})"