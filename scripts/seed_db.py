#!/usr/bin/env python
"""
Seed the database with initial Sentiment and Category data.
Run: python scripts/seed_db.py
"""
from __future__ import annotations

import os
import sys
import django

# ---------------------------------------------------------------------------
# Bootstrap Django
# ---------------------------------------------------------------------------
_BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _BASE_DIR)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.development")
django.setup()

# ---------------------------------------------------------------------------
# Seed data
# ---------------------------------------------------------------------------
from apps.feedback.models import Category, Sentiment  # noqa: E402

SENTIMENTS = [
    {"sentiment_label": "Positive", "display_colour": "#22c55e"},
    {"sentiment_label": "Negative", "display_colour": "#ef4444"},
    {"sentiment_label": "Neutral", "display_colour": "#64748b"},
    {"sentiment_label": "Uncertain", "display_colour": "#f59e0b"},
]

CATEGORIES = [
    "Food Security",
    "Health & Medical",
    "Shelter & Housing",
    "Water & Sanitation",
    "Education",
    "Protection & Safety",
    "Legal & Documentation",
    "Livelihood & Employment",
    "Mental Health & Psychosocial",
    "Gender-Based Violence",
    "Child Protection",
]


def seed_sentiments() -> None:
    created = 0
    for data in SENTIMENTS:
        _, was_created = Sentiment.objects.get_or_create(
            sentiment_label=data["sentiment_label"],
            defaults={"display_colour": data["display_colour"]},
        )
        if was_created:
            created += 1
    print(f"Sentiments: {created} created, {len(SENTIMENTS) - created} already existed.")


def seed_categories() -> None:
    created = 0
    for name in CATEGORIES:
        _, was_created = Category.objects.get_or_create(
            category_name=name,
            defaults={"is_active": True},
        )
        if was_created:
            created += 1
    print(f"Categories: {created} created, {len(CATEGORIES) - created} already existed.")


if __name__ == "__main__":
    print("Seeding database…")
    seed_sentiments()
    seed_categories()
    print("Done.")
