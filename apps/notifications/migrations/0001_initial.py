"""
Initial migration for the notifications app.
Creates the consent_schema PostgreSQL schema, then the Notification and
UserConsent models.
"""
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ("dashboard", "0001_initial"),
        ("feedback", "0001_initial"),
    ]

    operations = [
        # ── Create the dedicated consent schema ──────────────────────────────
        migrations.RunSQL(
            sql="CREATE SCHEMA IF NOT EXISTS consent_schema;",
            reverse_sql="DROP SCHEMA IF EXISTS consent_schema CASCADE;",
        ),
        # ── Notification ─────────────────────────────────────────────────────
        migrations.CreateModel(
            name="Notification",
            fields=[
                ("notification_id", models.AutoField(primary_key=True, serialize=False)),
                (
                    "feedback",
                    models.ForeignKey(
                        blank=True,
                        db_index=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="notifications",
                        to="feedback.feedback",
                    ),
                ),
                (
                    "sent_by_user",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="sent_notifications",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "message_type",
                    models.CharField(
                        choices=[
                            ("Acknowledgement", "Acknowledgement"),
                            ("Targeted_Response", "Targeted Response"),
                            ("Broadcast_YSWD", "Broadcast YSWD"),
                            ("Broadcast_General", "Broadcast General"),
                        ],
                        max_length=30,
                    ),
                ),
                ("content", models.TextField()),
                ("delivery_language", models.CharField(max_length=10)),
                (
                    "channel",
                    models.CharField(
                        choices=[("SMS", "SMS"), ("WhatsApp", "WhatsApp")],
                        max_length=10,
                    ),
                ),
                (
                    "delivery_status",
                    models.CharField(
                        choices=[
                            ("Queued", "Queued"),
                            ("Sent", "Sent"),
                            ("Delivered", "Delivered"),
                            ("Read", "Read"),
                            ("Failed", "Failed"),
                        ],
                        default="Queued",
                        max_length=15,
                    ),
                ),
                ("retry_count", models.SmallIntegerField(default=0)),
                ("sent_at", models.DateTimeField(blank=True, null=True)),
                ("delivered_at", models.DateTimeField(blank=True, null=True)),
                ("read_at", models.DateTimeField(blank=True, null=True)),
            ],
            options={
                "verbose_name": "Notification",
                "verbose_name_plural": "Notifications",
                "db_table": "rc_notification",
                "ordering": ["-notification_id"],
            },
        ),
        migrations.AddIndex(
            model_name="notification",
            index=models.Index(
                fields=["delivery_status", "channel"],
                name="idx_notif_status_channel",
            ),
        ),
        migrations.AddIndex(
            model_name="notification",
            index=models.Index(fields=["feedback"], name="idx_notif_feedback"),
        ),
        # ── UserConsent (in consent_schema) ──────────────────────────────────
        migrations.CreateModel(
            name="UserConsent",
            fields=[
                ("consent_id", models.AutoField(primary_key=True, serialize=False)),
                ("anonymous_user_id", models.CharField(db_index=True, max_length=100)),
                ("phone_number_encrypted", models.TextField()),
                (
                    "consent_type",
                    models.CharField(
                        choices=[("follow_up", "Follow Up"), ("survey", "Survey")],
                        max_length=30,
                    ),
                ),
                (
                    "channel_preference",
                    models.CharField(
                        choices=[("SMS", "SMS"), ("WhatsApp", "WhatsApp")],
                        default="SMS",
                        max_length=10,
                    ),
                ),
                ("consent_given_at", models.DateTimeField()),
                ("consent_withdrawn_at", models.DateTimeField(blank=True, null=True)),
                ("is_active", models.BooleanField(default=True)),
            ],
            options={
                "verbose_name": "User Consent",
                "verbose_name_plural": "User Consents",
                "db_table": '"consent_schema"."user_consent"',
                "ordering": ["-consent_given_at"],
            },
        ),
        migrations.AddIndex(
            model_name="userconsent",
            index=models.Index(
                fields=["anonymous_user_id"],
                name="idx_consent_anon_user",
            ),
        ),
    ]
