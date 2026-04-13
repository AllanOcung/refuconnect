"""Seed Sentiment lookup table with the four standard values."""
from django.db import migrations

SENTIMENTS = [
    {"sentiment_label": "Positive", "display_colour": "#28a745"},
    {"sentiment_label": "Neutral", "display_colour": "#6c757d"},
    {"sentiment_label": "Negative", "display_colour": "#dc3545"},
    {"sentiment_label": "Uncertain", "display_colour": "#ffc107"},
]


def seed_sentiments(apps, schema_editor):
    Sentiment = apps.get_model("feedback", "Sentiment")
    for data in SENTIMENTS:
        Sentiment.objects.get_or_create(
            sentiment_label=data["sentiment_label"],
            defaults={"display_colour": data["display_colour"]},
        )


def reverse_seed_sentiments(apps, schema_editor):
    Sentiment = apps.get_model("feedback", "Sentiment")
    Sentiment.objects.filter(
        sentiment_label__in=[s["sentiment_label"] for s in SENTIMENTS]
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("feedback", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(seed_sentiments, reverse_seed_sentiments),
    ]
