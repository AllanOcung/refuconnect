"""
Dashboard app models:
  - User   — custom AbstractBaseUser (email as username, bcrypt passwords)
  - AuditLog — immutable event ledger for compliance
"""
from __future__ import annotations

from django.contrib.auth.models import (
    AbstractBaseUser,
    BaseUserManager,
    PermissionsMixin,
)
from django.db import models


# ─── Manager ────────────────────────────────────────────────────────────────


class UserManager(BaseUserManager):
    """Custom manager that uses email (not username) as the unique identifier."""

    def create_user(
        self,
        email: str,
        full_name: str,
        password: str | None = None,
        **extra_fields,
    ) -> "User":
        if not email:
            raise ValueError("An email address is required.")
        if not full_name:
            raise ValueError("A full name is required.")
        email = self.normalize_email(email)
        extra_fields.setdefault("status", User.Status.PENDING_VERIFICATION)
        user: User = self.model(email=email, full_name=full_name, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(
        self,
        email: str,
        full_name: str,
        password: str | None = None,
        **extra_fields,
    ) -> "User":
        extra_fields.setdefault("role", User.Role.ADMINISTRATOR)
        extra_fields.setdefault("status", User.Status.ACTIVE)
        extra_fields.setdefault("is_superuser", True)
        if extra_fields.get("role") != User.Role.ADMINISTRATOR:
            raise ValueError("Superuser must have role=Administrator.")
        return self.create_user(email, full_name, password, **extra_fields)


# ─── User ────────────────────────────────────────────────────────────────────


class User(AbstractBaseUser, PermissionsMixin):
    """
    Custom user model for RefuConnect NGO staff.

    ``email`` is used as the login credential.
    Passwords are stored using BCryptSHA256 (configured in settings.PASSWORD_HASHERS).
    ``mfa_secret`` holds a TOTP seed; encrypt/decrypt it at the application layer
    using ``apps.common.encryption`` if exporting outside the process.
    """

    class Role(models.TextChoices):
        ADMINISTRATOR = "Administrator", "Administrator"
        NGO_STAFF = "NGO_Staff", "NGO Staff"

    class Status(models.TextChoices):
        PENDING_VERIFICATION = "Pending_Verification", "Pending Verification"
        ACTIVE = "Active", "Active"
        SUSPENDED = "Suspended", "Suspended"
        LOCKED = "Locked", "Locked"

    user_id = models.AutoField(primary_key=True)
    full_name = models.CharField(max_length=150)
    email = models.EmailField(max_length=254, unique=True, db_index=True)
    role = models.CharField(
        max_length=20,
        choices=Role.choices,
        default=Role.NGO_STAFF,
        db_index=True,
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING_VERIFICATION,
        db_index=True,
    )
    mfa_secret = models.CharField(max_length=64, null=True, blank=True)
    failed_login_count = models.SmallIntegerField(default=0)
    last_login_at = models.DateTimeField(null=True, blank=True)
    preferred_language = models.CharField(max_length=10, default="en")
    receive_alerts = models.BooleanField(default=True)
    alert_phone = models.CharField(max_length=20, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # Required by AbstractBaseUser / Django admin
    is_active = models.BooleanField(default=True)

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["full_name"]

    objects = UserManager()

    class Meta:
        db_table = "rc_user"
        verbose_name = "User"
        verbose_name_plural = "Users"
        ordering = ["full_name"]
        indexes = [
            models.Index(fields=["email"], name="idx_user_email"),
            models.Index(fields=["role", "status"], name="idx_user_role_status"),
        ]

    def __str__(self) -> str:
        return f"{self.full_name} <{self.email}>"

    # ── Permission helpers (used by Django admin) ─────────────────────────────

    @property
    def is_staff(self) -> bool:
        """Allow administrators to access the Django admin site."""
        return self.is_superuser or self.role == self.Role.ADMINISTRATOR

    def has_perm(self, perm: str, obj: object = None) -> bool:  # type: ignore[override]
        return self.is_active and (
            self.is_superuser or self.role == self.Role.ADMINISTRATOR
        )

    def has_module_perms(self, app_label: str) -> bool:
        return self.is_active and (
            self.is_superuser or self.role == self.Role.ADMINISTRATOR
        )

    # ── Business helpers ──────────────────────────────────────────────────────

    def increment_failed_login(self, lock_threshold: int = 5) -> None:
        """Increment the failed login counter and lock the account if the threshold is reached."""
        self.failed_login_count += 1
        if self.failed_login_count >= lock_threshold:
            self.status = self.Status.LOCKED
        self.save(update_fields=["failed_login_count", "status"])

    def reset_failed_login(self) -> None:
        """Clear the failed login counter after a successful login."""
        if self.failed_login_count != 0:
            self.failed_login_count = 0
            self.save(update_fields=["failed_login_count"])


# ─── AuditLog ────────────────────────────────────────────────────────────────


class AuditLog(models.Model):
    """
    Immutable compliance audit trail.

    Never update or delete rows from this table in application code.
    Use ``apps.common.audit.log_audit_event`` to create entries.
    """

    log_id = models.BigAutoField(primary_key=True)
    user = models.ForeignKey(
        "dashboard.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="audit_logs",
    )
    feedback = models.ForeignKey(
        "feedback.Feedback",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="audit_logs",
    )
    action = models.CharField(max_length=60)
    field_changed = models.CharField(max_length=60, null=True, blank=True)
    old_value = models.TextField(null=True, blank=True)
    new_value = models.TextField(null=True, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = "rc_audit_log"
        verbose_name = "Audit Log"
        verbose_name_plural = "Audit Logs"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["created_at"], name="idx_audit_created_at"),
            models.Index(fields=["action", "created_at"], name="idx_audit_action"),
            models.Index(fields=["user", "created_at"], name="idx_audit_user"),
        ]

    def __str__(self) -> str:
        actor = str(self.user) if self.user_id else "system"
        return f"[{self.created_at:%Y-%m-%d %H:%M}] {self.action} by {actor}"

    def save(self, *args, **kwargs):
        """Prevent updates — audit rows are append-only."""
        if self.pk:
            raise ValueError("AuditLog entries are immutable and cannot be modified.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValueError("AuditLog entries are immutable and cannot be deleted.")
