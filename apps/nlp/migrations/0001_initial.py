"""Initial migration for the nlp app: AIModelLog and ThemeCluster."""
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="AIModelLog",
            fields=[
                ("model_log_id", models.AutoField(primary_key=True, serialize=False)),
                (
                    "model_type",
                    models.CharField(
                        choices=[
                            ("sentiment", "Sentiment Analyser"),
                            ("topic_classifier", "Topic Classifier"),
                            ("language_detector", "Language Detector"),
                        ],
                        db_index=True,
                        max_length=50,
                    ),
                ),
                ("model_version", models.CharField(max_length=20)),
                ("training_data_summary", models.TextField()),
                (
                    "accuracy_english",
                    models.DecimalField(
                        blank=True, decimal_places=2, max_digits=5, null=True
                    ),
                ),
                (
                    "accuracy_swahili",
                    models.DecimalField(
                        blank=True, decimal_places=2, max_digits=5, null=True
                    ),
                ),
                (
                    "accuracy_local_lang",
                    models.DecimalField(
                        blank=True, decimal_places=2, max_digits=5, null=True
                    ),
                ),
                ("bias_test_results", models.JSONField(blank=True, null=True)),
                ("trained_by", models.CharField(max_length=100)),
                ("trained_at", models.DateTimeField()),
            ],
            options={
                "verbose_name": "AI Model Log",
                "verbose_name_plural": "AI Model Logs",
                "db_table": "rc_ai_model_log",
                "ordering": ["-trained_at"],
            },
        ),
        migrations.AddIndex(
            model_name="aimodellog",
            index=models.Index(
                fields=["model_type", "trained_at"], name="idx_ailog_type_date"
            ),
        ),
        migrations.CreateModel(
            name="ThemeCluster",
            fields=[
                ("cluster_id", models.AutoField(primary_key=True, serialize=False)),
                ("week_start_date", models.DateField(db_index=True)),
                ("cluster_label", models.CharField(max_length=100)),
                ("feedback_count", models.IntegerField(default=0)),
                ("avg_sentiment", models.CharField(blank=True, max_length=15, null=True)),
                (
                    "top_keywords",
                    models.JSONField(default=list),
                ),
                ("generated_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "verbose_name": "Theme Cluster",
                "verbose_name_plural": "Theme Clusters",
                "db_table": "rc_theme_cluster",
                "ordering": ["-week_start_date", "-feedback_count"],
            },
        ),
        migrations.AddIndex(
            model_name="themecluster",
            index=models.Index(
                fields=["week_start_date"], name="idx_cluster_week"
            ),
        ),
    ]
