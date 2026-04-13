"""
Feedback app models — the central hub of RefuConnect.

Models in this file:
  Sentiment       — lookup table (seeded: Positive, Neutral, Negative, Uncertain)
  Category        — lookup table (11 seeded categories)
  Feedback        — core entity, one row per submission
  FeedbackCategory— M2M junction with confidence scores
  FeedbackMedia   — attachments (images, voice notes, documents)
  Alert           — high-urgency alert derived from a Feedback record
"""
from __future__ import annotations

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models


# ─── Sentiment ───────────────────────────────────────────────────────────────


class Sentiment(models.Model):
    """
    Lookup table for sentiment labels.
    Seeded values: Positive, Neutral, Negative, Uncertain.
    """

    sentiment_id = models.AutoField(primary_key=True)
    sentiment_label = models.CharField(max_length=15, unique=True)
    display_colour = models.CharField(
        max_length=7,
        help_text="Hex colour code, e.g. #28a745",
    )

    class Meta:
        db_table = "rc_sentiment"
        verbose_name = "Sentiment"
        verbose_name_plural = "Sentiments"
        ordering = ["sentiment_label"]

    def __str__(self) -> str:
        return self.sentiment_label


# ─── Category ────────────────────────────────────────────────────────────────


class Category(models.Model):
    """Lookup table for feedback topic categories."""

    category_id = models.AutoField(primary_key=True)
    category_name = models.CharField(max_length=60, unique=True)
    description = models.TextField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "rc_category"
        verbose_name = "Category"
        verbose_name_plural = "Categories"
        ordering = ["category_name"]

    def __str__(self) -> str:
        return self.category_name


# ─── Feedback ────────────────────────────────────────────────────────────────


class Feedback(models.Model):
    """Central hub entity — one row per community feedback submission."""

    class Channel(models.TextChoices):
        SMS = "SMS", "SMS"
        USSD = "USSD", "USSD"
        WHATSAPP = "WhatsApp", "WhatsApp"

    class UrgencyLevel(models.TextChoices):
        LOW = "Low", "Low"
        MEDIUM = "Medium", "Medium"
        HIGH = "High", "High"

    class Status(models.TextChoices):
        NEW = "New", "New"
        PROCESSING = "Processing", "Processing"
        PROCESSED = "Processed", "Processed"
        PROCESSING_FAILED = "ProcessingFailed", "Processing Failed"
        ARCHIVED = "Archived", "Archived"

    feedback_id = models.AutoField(primary_key=True)
    anonymous_user_id = models.CharField(max_length=100, db_index=True)
    message_text = models.TextField()
    message_text_en = models.TextField(null=True, blank=True)
    language = models.CharField(max_length=10, default="unknown", db_index=True)
    language_confidence = models.DecimalField(
        max_digits=4,
        decimal_places=3,
        null=True,
        blank=True,
        validators=[MinValueValidator(0), MaxValueValidator(1)],
    )
    sentiment = models.ForeignKey(
        Sentiment,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="feedbacks",
        db_index=True,
    )
    sentiment_confidence = models.DecimalField(
        max_digits=4,
        decimal_places=3,
        null=True,
        blank=True,
        validators=[MinValueValidator(0), MaxValueValidator(1)],
    )
    urgency_level = models.CharField(
        max_length=10,
        choices=UrgencyLevel.choices,
        default=UrgencyLevel.LOW,
        db_index=True,
    )
    channel = models.CharField(
        max_length=10,
        choices=Channel.choices,
        db_index=True,
    )
    location = models.CharField(max_length=100, null=True, blank=True, db_index=True)
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.NEW,
        db_index=True,
    )
    is_flagged = models.BooleanField(default=False)
    flag_reason = models.CharField(max_length=60, null=True, blank=True)
    is_duplicate = models.BooleanField(default=False)
    submitted_at = models.DateTimeField(db_index=True)
    processed_at = models.DateTimeField(null=True, blank=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="reviewed_feedbacks",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "rc_feedback"
        verbose_name = "Feedback"
        verbose_name_plural = "Feedback"
        ordering = ["-submitted_at"]
        indexes = [
            models.Index(fields=["submitted_at"], name="idx_fb_submitted_at"),
            models.Index(
                fields=["channel", "status"], name="idx_fb_channel_status"
            ),
            models.Index(
                fields=["urgency_level", "status"], name="idx_fb_urgency_status"
            ),
            models.Index(
                fields=["anonymous_user_id"], name="idx_fb_anon_user"
            ),
        ]

    def __str__(self) -> str:
        return (
            f"Feedback #{self.feedback_id} "
            f"[{self.channel}] [{self.status}] — {self.submitted_at:%Y-%m-%d}"
        )


# ─── FeedbackCategory ────────────────────────────────────────────────────────


class FeedbackCategory(models.Model):
    """M2M junction between Feedback and Category, augmented with AI confidence."""

    fc_id = models.AutoField(primary_key=True)
    feedback = models.ForeignKey(
        Feedback,
        on_delete=models.CASCADE,
        related_name="feedback_categories",
        db_index=True,
    )
    category = models.ForeignKey(
        Category,
        on_delete=models.RESTRICT,
        related_name="feedback_categories",
        db_index=True,
    )
    confidence_score = models.DecimalField(
        max_digits=4,
        decimal_places=3,
        validators=[MinValueValidator(0), MaxValueValidator(1)],
    )
    is_ai_assigned = models.BooleanField(default=True)
    assigned_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "rc_feedback_category"
        verbose_name = "Feedback Category"
        verbose_name_plural = "Feedback Categories"
        unique_together = [("feedback", "category")]
        indexes = [
            models.Index(fields=["feedback"], name="idx_fc_feedback"),
            models.Index(fields=["category"], name="idx_fc_category"),
        ]

    def __str__(self) -> str:
        return f"Feedback #{self.feedback_id} → {self.category.category_name}"


# ─── FeedbackMedia ───────────────────────────────────────────────────────────


class FeedbackMedia(models.Model):
    """Attachments uploaded alongside a feedback submission."""

    class MediaType(models.TextChoices):
        IMAGE = "image", "Image"
        VOICE_NOTE = "voice_note", "Voice Note"
        DOCUMENT = "document", "Document"

    media_id = models.AutoField(primary_key=True)
    feedback = models.ForeignKey(
        Feedback,
        on_delete=models.CASCADE,
        related_name="media_files",
        db_index=True,
    )
    media_type = models.CharField(max_length=20, choices=MediaType.choices)
    storage_path = models.TextField()
    file_size_bytes = models.IntegerField()
    transcript_text = models.TextField(null=True, blank=True)
    extracted_text = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "rc_feedback_media"
        verbose_name = "Feedback Media"
        verbose_name_plural = "Feedback Media"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["feedback"], name="idx_fmedia_feedback"),
        ]

    def __str__(self) -> str:
        return f"{self.media_type} for Feedback #{self.feedback_id}"


# ─── Alert ───────────────────────────────────────────────────────────────────


class Alert(models.Model):
    """
    High-urgency alert derived from a single Feedback record (OneToOne).
    Created automatically by the NLP pipeline when urgency_level == 'High'
    or the feedback is flagged.
    """

    class Priority(models.TextChoices):
        LOW = "Low", "Low"
        MEDIUM = "Medium", "Medium"
        HIGH = "High", "High"

    class AlertStatus(models.TextChoices):
        OPEN = "Open", "Open"
        ACKNOWLEDGED = "Acknowledged", "Acknowledged"
        RESOLVED = "Resolved", "Resolved"

    alert_id = models.AutoField(primary_key=True)
    feedback = models.OneToOneField(
        Feedback,
        on_delete=models.CASCADE,
        related_name="alert",
    )
    priority_level = models.CharField(
        max_length=10,
        choices=Priority.choices,
    )
    description = models.TextField(null=True, blank=True)
    status = models.CharField(
        max_length=20,
        choices=AlertStatus.choices,
        default=AlertStatus.OPEN,
    )
    acknowledged_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="acknowledged_alerts",
    )
    acknowledged_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "rc_alert"
        verbose_name = "Alert"
        verbose_name_plural = "Alerts"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status", "priority_level"], name="idx_alert_status_priority"),
        ]

    def __str__(self) -> str:
        return (
            f"Alert #{self.alert_id} [{self.priority_level}] "
            f"[{self.status}] — Feedback #{self.feedback_id}"
        )
