from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("dashboard", "0002_auditlog"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="organisation",
            field=models.CharField(blank=True, default="", max_length=150),
        ),
        migrations.CreateModel(
            name="ScheduledReport",
            fields=[
                ("report_id", models.AutoField(primary_key=True, serialize=False)),
                ("template_id", models.CharField(max_length=50)),
                (
                    "format",
                    models.CharField(
                        choices=[("pdf", "PDF"), ("xlsx", "Excel")],
                        max_length=10,
                    ),
                ),
                ("filters", models.JSONField(default=dict)),
                (
                    "frequency",
                    models.CharField(
                        choices=[
                            ("daily", "Daily"),
                            ("weekly", "Weekly"),
                            ("monthly", "Monthly"),
                        ],
                        max_length=20,
                    ),
                ),
                ("next_run_at", models.DateTimeField(db_index=True)),
                ("last_sent_at", models.DateTimeField(blank=True, null=True)),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="scheduled_reports",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "db_table": "rc_scheduled_report",
                "ordering": ["next_run_at"],
            },
        ),
        migrations.CreateModel(
            name="ReportExport",
            fields=[
                ("export_id", models.AutoField(primary_key=True, serialize=False)),
                ("template_id", models.CharField(max_length=50)),
                ("format", models.CharField(max_length=10)),
                ("filters_snapshot", models.JSONField(default=dict)),
                ("row_count", models.IntegerField(default=0)),
                ("file_size_bytes", models.IntegerField(blank=True, null=True)),
                ("generated_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                (
                    "user",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="report_exports",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "db_table": "rc_report_export",
                "ordering": ["-generated_at"],
            },
        ),
    ]
