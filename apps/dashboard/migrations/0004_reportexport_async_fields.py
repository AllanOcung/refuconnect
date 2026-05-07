from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("dashboard", "0003_user_organisation_reports"),
    ]

    operations = [
        migrations.AddField(
            model_name="reportexport",
            name="completed_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="reportexport",
            name="content_type",
            field=models.CharField(blank=True, max_length=120, null=True),
        ),
        migrations.AddField(
            model_name="reportexport",
            name="error_message",
            field=models.TextField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="reportexport",
            name="file_data",
            field=models.BinaryField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="reportexport",
            name="file_name",
            field=models.CharField(blank=True, max_length=255, null=True),
        ),
        migrations.AddField(
            model_name="reportexport",
            name="status",
            field=models.CharField(
                choices=[
                    ("queued", "Queued"),
                    ("processing", "Processing"),
                    ("completed", "Completed"),
                    ("failed", "Failed"),
                ],
                db_index=True,
                default="completed",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="reportexport",
            name="task_id",
            field=models.CharField(blank=True, db_index=True, max_length=255, null=True),
        ),
    ]
