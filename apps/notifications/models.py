"""
Notifications app models:
  Notification    – outbound message record (acknowledgement / broadcast / response)
  UserConsent     – GDPR/PDPA consent records stored in a separate PostgreSQL schema
  MessageTemplate – multilingual message templates used by TemplateLibrary
  Broadcast       – broadcast campaign records for YSWD and general announcements
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
    gateway_message_id = models.CharField(max_length=255, null=True, blank=True, db_index=True)
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
            models.Index(fields=["gateway_message_id"], name="idx_notif_gw_msg_id"),
        ]

    def __str__(self) -> str:
        return (
            f"Notification #{self.notification_id} "
            f"[{self.channel}] [{self.delivery_status}]"
        )


class UserConsent(models.Model):
    """
    Consent records for follow-up communication.

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
            f"[{self.consent_type}] – {self.anonymous_user_id[:12]}…"
        )


class MessageTemplate(models.Model):
    """
    Stores multilingual message templates used by TemplateLibrary.

    Standard template_key values:
        ACKNOWLEDGEMENT, ACKNOWLEDGEMENT_DUPLICATE, RESPONSE_HEADER,
        BROADCAST_YSWD_HEADER, BROADCAST_GENERAL_HEADER,
        OPT_IN_PROMPT, OPT_IN_CONFIRMATION, OPT_OUT_CONFIRMATION, SESSION_EXPIRED

    System templates (is_system=True) cannot be deleted, only edited.
    """

    STANDARD_KEYS = [
        "ACKNOWLEDGEMENT",
        "ACKNOWLEDGEMENT_DUPLICATE",
        "RESPONSE_HEADER",
        "BROADCAST_YSWD_HEADER",
        "BROADCAST_GENERAL_HEADER",
        "OPT_IN_PROMPT",
        "OPT_IN_CONFIRMATION",
        "OPT_OUT_CONFIRMATION",
        "SESSION_EXPIRED",
    ]

    SUPPORTED_LANGUAGES = ["en", "sw", "lg", "rw", "ar", "so", "fr"]

    template_id = models.AutoField(primary_key=True)
    template_key = models.CharField(max_length=60, db_index=True)
    language = models.CharField(max_length=10)  # BCP 47 code
    body = models.TextField(
        help_text="Template text with {variable} placeholders. "
                  "Allowed: {reference_id}, {category}, {location}, {org_name}"
    )
    is_active = models.BooleanField(default=True)
    is_system = models.BooleanField(
        default=False,
        help_text="System templates cannot be deleted, only edited.",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="created_templates",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "rc_message_template"
        verbose_name = "Message Template"
        verbose_name_plural = "Message Templates"
        unique_together = [("template_key", "language")]
        ordering = ["template_key", "language"]
        indexes = [
            models.Index(fields=["template_key", "language"], name="idx_tmpl_key_lang"),
            models.Index(fields=["is_active"], name="idx_tmpl_active"),
        ]

    def __str__(self) -> str:
        return f"{self.template_key} [{self.language}]"


class Broadcast(models.Model):
    """
    Broadcast campaign record for 'You Said, We Did' and general announcements.
    """

    class MessageType(models.TextChoices):
        YSWD = "YSWD", "You Said We Did"
        GENERAL_ANNOUNCEMENT = "General_Announcement", "General Announcement"

    class TargetType(models.TextChoices):
        ALL = "all", "All opted-in users"
        BY_LOCATION = "by_location", "By location"
        BY_CATEGORY = "by_category", "By category"
        BY_FEEDBACK_IDS = "by_feedback_ids", "By specific feedback IDs"

    class Status(models.TextChoices):
        DRAFT = "Draft", "Draft"
        SCHEDULED = "Scheduled", "Scheduled"
        SENDING = "Sending", "Sending"
        COMPLETED = "Completed", "Completed"
        FAILED = "Failed", "Failed"

    broadcast_id = models.AutoField(primary_key=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="broadcasts",
    )
    message_type = models.CharField(max_length=30, choices=MessageType.choices)
    body_en = models.TextField(help_text="Message body in English (source language).")
    target_type = models.CharField(max_length=20, choices=TargetType.choices)
    target_location = models.CharField(max_length=100, null=True, blank=True)
    target_category = models.ForeignKey(
        "feedback.Category",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="broadcasts",
    )
    target_days = models.IntegerField(
        default=30,
        help_text="When target_type='by_category': look back this many days.",
    )
    target_feedback_ids = models.JSONField(
        null=True,
        blank=True,
        help_text="When target_type='by_feedback_ids': list of specific feedback_ids.",
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.DRAFT,
        db_index=True,
    )
    scheduled_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="NULL means send immediately on creation.",
    )
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    total_recipients = models.IntegerField(default=0)
    sent_count = models.IntegerField(default=0)
    delivered_count = models.IntegerField(default=0)
    failed_count = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "rc_broadcast"
        verbose_name = "Broadcast"
        verbose_name_plural = "Broadcasts"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status"], name="idx_broadcast_status"),
            models.Index(fields=["scheduled_at"], name="idx_broadcast_scheduled"),
        ]

    def __str__(self) -> str:
        return f"Broadcast #{self.broadcast_id} [{self.message_type}] [{self.status}]"