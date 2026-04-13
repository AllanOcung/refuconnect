"""
Django admin for the dashboard app.
"""
from __future__ import annotations

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from apps.dashboard.models import AuditLog, User


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = ("email", "full_name", "role", "status", "created_at")
    list_filter = ("role", "status")
    search_fields = ("email", "full_name", "organisation")
    ordering = ("-created_at",)
    readonly_fields = ("user_id", "created_at", "last_login_at", "failed_login_count")

    fieldsets = (
        ("Credentials", {"fields": ("email", "password")}),
        ("Personal", {"fields": ("full_name", "organisation", "phone_number")}),
        ("Role & Status", {"fields": ("role", "status")}),
        ("Activity", {"fields": ("last_login_at", "failed_login_count", "created_at")}),
        ("Permissions", {"fields": ("is_superuser", "groups", "user_permissions")}),
    )

    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": ("email", "full_name", "role", "organisation", "password1", "password2"),
            },
        ),
    )


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ("log_id", "user", "action", "created_at", "ip_address")
    list_filter = ("action",)
    search_fields = ("user__email", "action", "ip_address")
    readonly_fields = (
        "log_id",
        "user",
        "action",
        "feedback",
        "field_changed",
        "old_value",
        "new_value",
        "ip_address",
        "user_agent",
        "created_at",
    )
    ordering = ("-created_at",)

    def has_add_permission(self, request) -> bool:
        return False

    def has_change_permission(self, request, obj=None) -> bool:
        return False

    def has_delete_permission(self, request, obj=None) -> bool:
        return False
