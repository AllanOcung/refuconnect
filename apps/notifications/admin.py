"""
Django admin for the notifications app.
"""
from __future__ import annotations

from django.contrib import admin

from apps.notifications.models import Broadcast, MessageTemplate, Notification, UserConsent


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = (
        "notification_id", "message_type", "channel", "delivery_status",
        "sent_by_user", "sent_at", "retry_count",
    )
    list_filter = ("message_type", "delivery_status", "channel")
    search_fields = ("content", "sent_by_user__email", "gateway_message_id")
    readonly_fields = (
        "notification_id", "message_type", "content", "delivery_language",
        "channel", "delivery_status", "gateway_message_id", "sent_by_user",
        "feedback", "sent_at", "delivered_at", "read_at", "retry_count",
    )
    ordering = ("-notification_id",)

    def has_add_permission(self, request) -> bool:
        return False


@admin.register(UserConsent)
class UserConsentAdmin(admin.ModelAdmin):
    list_display = (
        "consent_id", "anonymous_user_id", "consent_type",
        "channel_preference", "is_active", "consent_given_at",
    )
    list_filter = ("consent_type", "channel_preference", "is_active")
    search_fields = ("anonymous_user_id",)
    readonly_fields = (
        "consent_id", "anonymous_user_id", "phone_number_encrypted", "consent_given_at",
    )
    ordering = ("-consent_given_at",)


@admin.register(MessageTemplate)
class MessageTemplateAdmin(admin.ModelAdmin):
    list_display = (
        "template_id", "template_key", "language", "is_active", "is_system", "updated_at",
    )
    list_filter = ("is_active", "is_system", "language")
    search_fields = ("template_key", "body")
    readonly_fields = ("template_id", "is_system", "created_by", "created_at", "updated_at")
    ordering = ("template_key", "language")

    def has_delete_permission(self, request, obj=None) -> bool:
        if obj is not None and obj.is_system:
            return False
        return super().has_delete_permission(request, obj)


@admin.register(Broadcast)
class BroadcastAdmin(admin.ModelAdmin):
    list_display = (
        "broadcast_id", "message_type", "status", "total_recipients",
        "sent_count", "failed_count", "created_by", "created_at",
    )
    list_filter = ("message_type", "status", "target_type")
    search_fields = ("body_en",)
    readonly_fields = (
        "broadcast_id", "status", "started_at", "completed_at",
        "total_recipients", "sent_count", "delivered_count", "failed_count",
        "created_at", "updated_at",
    )
    ordering = ("-created_at",)

    def has_delete_permission(self, request, obj=None) -> bool:
        return False