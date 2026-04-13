"""
Django admin for the notifications app.
"""
from __future__ import annotations

from django.contrib import admin

from apps.notifications.models import Notification, UserConsent


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ("notification_id", "message_type", "delivery_status", "sent_by_user", "sent_at")
    list_filter = ("message_type", "delivery_status")
    search_fields = ("content", "sent_by_user__email")
    readonly_fields = (
        "notification_id",
        "message_type",
        "content",
        "delivery_status",
        "sent_by_user",
        "feedback",
        "sent_at",
    )
    ordering = ("-notification_id",)

    def has_add_permission(self, request) -> bool:
        return False


@admin.register(UserConsent)
class UserConsentAdmin(admin.ModelAdmin):
    list_display = ("consent_id", "anonymous_user_id", "consent_type", "channel_preference", "is_active", "consent_given_at")
    list_filter = ("consent_type", "channel_preference", "is_active")
    search_fields = ("anonymous_user_id",)
    readonly_fields = ("consent_id", "anonymous_user_id", "phone_number_encrypted", "consent_given_at")
    ordering = ("-consent_given_at",)
