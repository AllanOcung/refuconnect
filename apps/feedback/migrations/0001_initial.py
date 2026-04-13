"""
Initial migration for the feedback app.
Creates: Sentiment, Category, Feedback, FeedbackCategory, FeedbackMedia, Alert.
Depends on dashboard.0001_initial (for the User FK on Feedback and Alert).
"""
import django.core.validators
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ("dashboard", "0001_initial"),
    ]

    operations = [
        # ── Sentiment ────────────────────────────────────────────────────────
        migrations.CreateModel(
            name="Sentiment",
            fields=[
                ("sentiment_id", models.AutoField(primary_key=True, serialize=False)),
                ("sentiment_label", models.CharField(max_length=15, unique=True)),
                ("display_colour", models.CharField(max_length=7)),
            ],
            options={
                "verbose_name": "Sentiment",
                "verbose_name_plural": "Sentiments",
                "db_table": "rc_sentiment",
                "ordering": ["sentiment_label"],
            },
        ),
        # ── Category ─────────────────────────────────────────────────────────
        migrations.CreateModel(
            name="Category",
            fields=[
                ("category_id", models.AutoField(primary_key=True, serialize=False)),
                ("category_name", models.CharField(max_length=60, unique=True)),
                ("description", models.TextField(blank=True, null=True)),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "verbose_name": "Category",
                "verbose_name_plural": "Categories",
                "db_table": "rc_category",
                "ordering": ["category_name"],
            },
        ),
        # ── Feedback ─────────────────────────────────────────────────────────
        migrations.CreateModel(
            name="Feedback",
            fields=[
                ("feedback_id", models.AutoField(primary_key=True, serialize=False)),
                ("anonymous_user_id", models.CharField(db_index=True, max_length=100)),
                ("message_text", models.TextField()),
                ("message_text_en", models.TextField(blank=True, null=True)),
                ("language", models.CharField(db_index=True, default="unknown", max_length=10)),
                (
                    "language_confidence",
                    models.DecimalField(
                        blank=True,
                        decimal_places=3,
                        max_digits=4,
                        null=True,
                        validators=[
                            django.core.validators.MinValueValidator(0),
                            django.core.validators.MaxValueValidator(1),
                        ],
                    ),
                ),
                (
                    "sentiment",
                    models.ForeignKey(
                        blank=True,
                        db_index=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="feedbacks",
                        to="feedback.sentiment",
                    ),
                ),
                (
                    "sentiment_confidence",
                    models.DecimalField(
                        blank=True,
                        decimal_places=3,
                        max_digits=4,
                        null=True,
                        validators=[
                            django.core.validators.MinValueValidator(0),
                            django.core.validators.MaxValueValidator(1),
                        ],
                    ),
                ),
                (
                    "urgency_level",
                    models.CharField(
                        choices=[("Low", "Low"), ("Medium", "Medium"), ("High", "High")],
                        db_index=True,
                        default="Low",
                        max_length=10,
                    ),
                ),
                (
                    "channel",
                    models.CharField(
                        choices=[("SMS", "SMS"), ("USSD", "USSD"), ("WhatsApp", "WhatsApp")],
                        db_index=True,
                        max_length=10,
                    ),
                ),
                ("location", models.CharField(blank=True, db_index=True, max_length=100, null=True)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("New", "New"),
                            ("Processing", "Processing"),
                            ("Processed", "Processed"),
                            ("ProcessingFailed", "Processing Failed"),
                            ("Archived", "Archived"),
                        ],
                        db_index=True,
                        default="New",
                        max_length=15,
                    ),
                ),
                ("is_flagged", models.BooleanField(default=False)),
                ("flag_reason", models.CharField(blank=True, max_length=60, null=True)),
                ("is_duplicate", models.BooleanField(default=False)),
                ("submitted_at", models.DateTimeField(db_index=True)),
                ("processed_at", models.DateTimeField(blank=True, null=True)),
                (
                    "reviewed_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="reviewed_feedbacks",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                ("reviewed_at", models.DateTimeField(blank=True, null=True)),
            ],
            options={
                "verbose_name": "Feedback",
                "verbose_name_plural": "Feedback",
                "db_table": "rc_feedback",
                "ordering": ["-submitted_at"],
            },
        ),
        migrations.AddIndex(
            model_name="feedback",
            index=models.Index(fields=["submitted_at"], name="idx_fb_submitted_at"),
        ),
        migrations.AddIndex(
            model_name="feedback",
            index=models.Index(fields=["channel", "status"], name="idx_fb_channel_status"),
        ),
        migrations.AddIndex(
            model_name="feedback",
            index=models.Index(fields=["urgency_level", "status"], name="idx_fb_urgency_status"),
        ),
        migrations.AddIndex(
            model_name="feedback",
            index=models.Index(fields=["anonymous_user_id"], name="idx_fb_anon_user"),
        ),
        # ── FeedbackCategory ─────────────────────────────────────────────────
        migrations.CreateModel(
            name="FeedbackCategory",
            fields=[
                ("fc_id", models.AutoField(primary_key=True, serialize=False)),
                (
                    "feedback",
                    models.ForeignKey(
                        db_index=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="feedback_categories",
                        to="feedback.feedback",
                    ),
                ),
                (
                    "category",
                    models.ForeignKey(
                        db_index=True,
                        on_delete=django.db.models.deletion.RESTRICT,
                        related_name="feedback_categories",
                        to="feedback.category",
                    ),
                ),
                (
                    "confidence_score",
                    models.DecimalField(
                        decimal_places=3,
                        max_digits=4,
                        validators=[
                            django.core.validators.MinValueValidator(0),
                            django.core.validators.MaxValueValidator(1),
                        ],
                    ),
                ),
                ("is_ai_assigned", models.BooleanField(default=True)),
                ("assigned_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "verbose_name": "Feedback Category",
                "verbose_name_plural": "Feedback Categories",
                "db_table": "rc_feedback_category",
                "unique_together": {("feedback", "category")},
            },
        ),
        migrations.AddIndex(
            model_name="feedbackcategory",
            index=models.Index(fields=["feedback"], name="idx_fc_feedback"),
        ),
        migrations.AddIndex(
            model_name="feedbackcategory",
            index=models.Index(fields=["category"], name="idx_fc_category"),
        ),
        # ── FeedbackMedia ────────────────────────────────────────────────────
        migrations.CreateModel(
            name="FeedbackMedia",
            fields=[
                ("media_id", models.AutoField(primary_key=True, serialize=False)),
                (
                    "feedback",
                    models.ForeignKey(
                        db_index=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="media_files",
                        to="feedback.feedback",
                    ),
                ),
                (
                    "media_type",
                    models.CharField(
                        choices=[
                            ("image", "Image"),
                            ("voice_note", "Voice Note"),
                            ("document", "Document"),
                        ],
                        max_length=20,
                    ),
                ),
                ("storage_path", models.TextField()),
                ("file_size_bytes", models.IntegerField()),
                ("transcript_text", models.TextField(blank=True, null=True)),
                ("extracted_text", models.TextField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "verbose_name": "Feedback Media",
                "verbose_name_plural": "Feedback Media",
                "db_table": "rc_feedback_media",
                "ordering": ["-created_at"],
            },
        ),
        migrations.AddIndex(
            model_name="feedbackmedia",
            index=models.Index(fields=["feedback"], name="idx_fmedia_feedback"),
        ),
        # ── Alert ────────────────────────────────────────────────────────────
        migrations.CreateModel(
            name="Alert",
            fields=[
                ("alert_id", models.AutoField(primary_key=True, serialize=False)),
                (
                    "feedback",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="alert",
                        to="feedback.feedback",
                    ),
                ),
                (
                    "priority_level",
                    models.CharField(
                        choices=[("Low", "Low"), ("Medium", "Medium"), ("High", "High")],
                        max_length=10,
                    ),
                ),
                ("description", models.TextField(blank=True, null=True)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("Open", "Open"),
                            ("Acknowledged", "Acknowledged"),
                            ("Resolved", "Resolved"),
                        ],
                        default="Open",
                        max_length=20,
                    ),
                ),
                (
                    "acknowledged_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="acknowledged_alerts",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                ("acknowledged_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "verbose_name": "Alert",
                "verbose_name_plural": "Alerts",
                "db_table": "rc_alert",
                "ordering": ["-created_at"],
            },
        ),
        migrations.AddIndex(
            model_name="alert",
            index=models.Index(
                fields=["status", "priority_level"], name="idx_alert_status_priority"
            ),
        ),
    ]
