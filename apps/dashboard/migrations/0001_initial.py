"""Initial migration: creates the rc_user table only.

AuditLog is added in 0002 after the feedback app creates the Feedback model,
preventing a circular migration dependency.
"""
import django.contrib.auth.models
import django.db.models.deletion
from django.db import migrations, models

import apps.dashboard.models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ("auth", "0012_alter_user_first_name_max_length"),
    ]

    operations = [
        migrations.CreateModel(
            name="User",
            fields=[
                ("user_id", models.AutoField(primary_key=True, serialize=False)),
                (
                    "password",
                    models.CharField(max_length=128, verbose_name="password"),
                ),
                (
                    "last_login",
                    models.DateTimeField(
                        blank=True, null=True, verbose_name="last login"
                    ),
                ),
                (
                    "is_superuser",
                    models.BooleanField(
                        default=False,
                        help_text="Designates that this user has all permissions without explicitly assigning them.",
                        verbose_name="superuser status",
                    ),
                ),
                ("full_name", models.CharField(max_length=150)),
                (
                    "email",
                    models.EmailField(db_index=True, max_length=254, unique=True),
                ),
                (
                    "role",
                    models.CharField(
                        choices=[
                            ("Administrator", "Administrator"),
                            ("NGO_Staff", "NGO Staff"),
                        ],
                        db_index=True,
                        default="NGO_Staff",
                        max_length=20,
                    ),
                ),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("Pending_Verification", "Pending Verification"),
                            ("Active", "Active"),
                            ("Suspended", "Suspended"),
                            ("Locked", "Locked"),
                        ],
                        db_index=True,
                        default="Pending_Verification",
                        max_length=20,
                    ),
                ),
                (
                    "mfa_secret",
                    models.CharField(blank=True, max_length=64, null=True),
                ),
                ("failed_login_count", models.SmallIntegerField(default=0)),
                (
                    "last_login_at",
                    models.DateTimeField(blank=True, null=True),
                ),
                (
                    "preferred_language",
                    models.CharField(default="en", max_length=10),
                ),
                ("receive_alerts", models.BooleanField(default=True)),
                (
                    "alert_phone",
                    models.CharField(blank=True, max_length=20, null=True),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("is_active", models.BooleanField(default=True)),
                (
                    "groups",
                    models.ManyToManyField(
                        blank=True,
                        help_text="The groups this user belongs to.",
                        related_name="user_set",
                        related_query_name="user",
                        to="auth.group",
                        verbose_name="groups",
                    ),
                ),
                (
                    "user_permissions",
                    models.ManyToManyField(
                        blank=True,
                        help_text="Specific permissions for this user.",
                        related_name="user_set",
                        related_query_name="user",
                        to="auth.permission",
                        verbose_name="user permissions",
                    ),
                ),
            ],
            options={
                "verbose_name": "User",
                "verbose_name_plural": "Users",
                "db_table": "rc_user",
                "ordering": ["full_name"],
            },
            managers=[
                ("objects", apps.dashboard.models.UserManager()),
            ],
        ),
        migrations.AddIndex(
            model_name="user",
            index=models.Index(fields=["email"], name="idx_user_email"),
        ),
        migrations.AddIndex(
            model_name="user",
            index=models.Index(
                fields=["role", "status"], name="idx_user_role_status"
            ),
        ),
    ]
