# Generated migration for FeedbackCluster model

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("feedback", "0003_seed_categories"),
        ("nlp", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="FeedbackCluster",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("week_start_date", models.DateField(db_index=True)),
                ("assigned_at", models.DateTimeField(auto_now_add=True)),
                (
                    "cluster",
                    models.ForeignKey(
                        help_text="The theme cluster this feedback belongs to.",
                        on_delete=django.db.models.deletion.CASCADE,
                        to="nlp.themecluster",
                        db_index=True,
                    ),
                ),
                (
                    "feedback",
                    models.ForeignKey(
                        help_text="The feedback record assigned to this cluster.",
                        on_delete=django.db.models.deletion.CASCADE,
                        to="feedback.feedback",
                        db_index=True,
                    ),
                ),
            ],
            options={
                "verbose_name": "Feedback Cluster",
                "verbose_name_plural": "Feedback Clusters",
                "db_table": "rc_feedback_cluster",
                "ordering": ["-assigned_at"],
            },
        ),
        migrations.AddIndex(
            model_name="feedbackcluster",
            index=models.Index(
                fields=["week_start_date"], name="idx_fdbk_cluster_week"
            ),
        ),
        migrations.AddIndex(
            model_name="feedbackcluster",
            index=models.Index(
                fields=["feedback", "week_start_date"],
                name="idx_fdbk_cluster_composite",
            ),
        ),
        migrations.AlterUniqueTogether(
            name="feedbackcluster",
            unique_together={("feedback", "week_start_date")},
        ),
    ]
