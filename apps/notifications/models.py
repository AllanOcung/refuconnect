"""
Notifications app models:
  Notification  — outbound message record (acknowledgement / broadcast / response)
  UserConsent   — GDPR/PDPA consent records stored in a separate PostgreSQL schema
"""
from __future__ import annotations

from django.conf import settings
from django.db import models


class Notification(models.Model):
    """Outbound message dispatched to a community member via SMS or WhatsApp."""

    class MessageType(models.TextChoices):
        ACKNOWLEDGEMENT = "Acknowledgement", "Acknowledgement"
        TARGETED_RESPONSE = "Targeted_Response", "Targeted Response"
        BROADCAST_YSWD = "Broadcast_YSWD", "Broadcast YSWD"
        BROADCAST_GENERAL = "Broadcast_General", "Broadcast General"

    class Channel(models.TextChoices):
        SMS = "SMS", "SMS"
        WHATSAPP = "WhatsApp", "WhatsApp"

    class DeliveryStatus(models.TextChoices):
        QUEUED = "Queued", "Queued"
        SENT = "Sent", "Sent"
        DELIVERED = "Delivered", "Delivered"
        READ = "Read", "Read"
        FAILED = "Failed", "Failed"

    notification_id = models.AutoField(primary_key=True)
    feedback = models.ForeignKey(
        "feedback.Feedback",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="notifications",
        db_index=True,
    )
    sent_by_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="sent_notifications",
    )
    message_type = models.CharField(max_length=30, choices=MessageType.choices)
    content = models.TextField()
    delivery_language = models.CharField(max_length=10)
    channel = models.CharField(max_length=10, choices=Channel.choices)
    delivery_status = models.CharField(
        max_length=15,
        choices=DeliveryStatus.choices,
        default=DeliveryStatus.QUEUED,
    )
    retry_count = models.SmallIntegerField(default=0)
    sent_at = models.DateTimeField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "rc_notification"
        verbose_name = "Notification"
        verbose_name_plural = "Notifications"
        ordering = ["-notification_id"]
        indexes = [
            models.Index(
                fields=["delivery_status", "channel"],
                name="idx_notif_status_channel",
            ),
            models.Index(fields=["feedback"], name="idx_notif_feedback"),
        ]

    def __str__(self) -> str:
        return (
            f"Notification #{self.notification_id} "
            f"[{self.channel}] [{self.delivery_status}]"
        )


class UserConsent(models.Model):
    """
    Consent records for follow-up communication.

    Stored in a dedicated PostgreSQL schema (``consent_schema``) to enable
    tighter access controls at the database level.
    Phone numbers are AES-256-GCM encrypted at the application layer using
    ``apps.common.encryption.encrypt_field``.
    """

    class ConsentType(models.TextChoices):
        FOLLOW_UP = "follow_up", "Follow Up"
        SURVEY = "survey", "Survey"

    class ChannelPreference(models.TextChoices):
        SMS = "SMS", "SMS"
        WHATSAPP = "WhatsApp", "WhatsApp"

    consent_id = models.AutoField(primary_key=True)
    anonymous_user_id = models.CharField(max_length=100, db_index=True)
    phone_number_encrypted = models.TextField(
        help_text="AES-256-GCM encrypted phone number. Use apps.common.encryption to read/write."
    )
    consent_type = models.CharField(max_length=30, choices=ConsentType.choices)
    channel_preference = models.CharField(
        max_length=10,
        choices=ChannelPreference.choices,
        default=ChannelPreference.SMS,
    )
    consent_given_at = models.DateTimeField()
    consent_withdrawn_at = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "consent_schema_user_consent"
        verbose_name = "User Consent"
        verbose_name_plural = "User Consents"
        ordering = ["-consent_given_at"]
        indexes = [
            models.Index(
                fields=["anonymous_user_id"],
                name="idx_consent_anon_user",
            ),
        ]

    def __str__(self) -> str:
        return (
            f"Consent #{self.consent_id} "
            f"[{self.consent_type}] — {self.anonymous_user_id[:12]}…"
        )
