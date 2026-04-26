"""
NLP app models:
  AIModelLog      — versioned log of trained AI model snapshots
  ThemeCluster    — weekly auto-generated topic clusters
  FeedbackCluster — junction: Feedback ↔ ThemeCluster mappings
"""
from __future__ import annotations

from django.db import models


class AIModelLog(models.Model):
    """Records each training run for auditability and bias tracking."""

    class ModelType(models.TextChoices):
        SENTIMENT = "sentiment", "Sentiment Analyser"
        TOPIC_CLASSIFIER = "topic_classifier", "Topic Classifier"
        LANGUAGE_DETECTOR = "language_detector", "Language Detector"

    model_log_id = models.AutoField(primary_key=True)
    model_type = models.CharField(
        max_length=50,
        choices=ModelType.choices,
        db_index=True,
    )
    model_version = models.CharField(max_length=20)
    training_data_summary = models.TextField()
    accuracy_english = models.DecimalField(
        max_digits=5, decimal_places=2, null=True, blank=True
    )
    accuracy_swahili = models.DecimalField(
        max_digits=5, decimal_places=2, null=True, blank=True
    )
    accuracy_local_lang = models.DecimalField(
        max_digits=5, decimal_places=2, null=True, blank=True
    )
    bias_test_results = models.JSONField(null=True, blank=True)
    trained_by = models.CharField(max_length=100)
    trained_at = models.DateTimeField()

    class Meta:
        db_table = "rc_ai_model_log"
        verbose_name = "AI Model Log"
        verbose_name_plural = "AI Model Logs"
        ordering = ["-trained_at"]
        indexes = [
            models.Index(fields=["model_type", "trained_at"], name="idx_ailog_type_date"),
        ]

    def __str__(self) -> str:
        return f"{self.model_type} v{self.model_version} — trained {self.trained_at:%Y-%m-%d}"


class ThemeCluster(models.Model):
    """
    Auto-generated weekly topic clusters derived from feedback messages.
    ``top_keywords`` is a PostgreSQL ARRAY of VARCHAR(50).
    """

    cluster_id = models.AutoField(primary_key=True)
    week_start_date = models.DateField(db_index=True)
    cluster_label = models.CharField(max_length=100)
    feedback_count = models.IntegerField(default=0)
    avg_sentiment = models.CharField(max_length=15, null=True, blank=True)
    top_keywords = models.JSONField(
        default=list,
        help_text="Top TF-IDF keywords for this cluster.",
    )
    generated_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "rc_theme_cluster"
        verbose_name = "Theme Cluster"
        verbose_name_plural = "Theme Clusters"
        ordering = ["-week_start_date", "-feedback_count"]
        indexes = [
            models.Index(fields=["week_start_date"], name="idx_cluster_week"),
        ]

    def __str__(self) -> str:
        return f"[{self.week_start_date}] {self.cluster_label} ({self.feedback_count} items)"


class FeedbackCluster(models.Model):
    """
    Junction table mapping individual Feedback records to weekly ThemeCluster assignments.
    Enables filtering feedback by cluster on the dashboard.
    """

    feedback = models.ForeignKey(
        "feedback.Feedback",
        on_delete=models.CASCADE,
        db_index=True,
        help_text="The feedback record assigned to this cluster.",
    )
    cluster = models.ForeignKey(
        ThemeCluster,
        on_delete=models.CASCADE,
        db_index=True,
        help_text="The theme cluster this feedback belongs to.",
    )
    week_start_date = models.DateField(
        db_index=True,
        help_text="Denormalised week start date for efficient filtering.",
    )
    assigned_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "rc_feedback_cluster"
        verbose_name = "Feedback Cluster"
        verbose_name_plural = "Feedback Clusters"
        ordering = ["-assigned_at"]
        indexes = [
            models.Index(
                fields=["week_start_date"], name="idx_fdbk_cluster_week"
            ),
            models.Index(
                fields=["feedback", "week_start_date"],
                name="idx_fdbk_cluster_composite",
            ),
        ]
        unique_together = [("feedback", "week_start_date")]

    def __str__(self) -> str:
        return f"Feedback #{self.feedback.feedback_id} → {self.cluster.cluster_label}"
