"""
Analytics engine — aggregates feedback statistics for the dashboard.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from django.db.models import Count, Q
from django.db.models.functions import TruncDate

from apps.feedback.models import Feedback


def get_feedback_summary(date_from: date, date_to: date) -> dict[str, Any]:
    """Aggregate counts by status, channel, and language for a date range."""
    base_qs = Feedback.objects.filter(
        submitted_at__date__gte=date_from,
        submitted_at__date__lte=date_to,
    )

    total = base_qs.count()

    by_status = list(
        base_qs.values("status").annotate(count=Count("feedback_id")).order_by("status")
    )
    by_channel = list(
        base_qs.values("channel").annotate(count=Count("feedback_id")).order_by("channel")
    )
    by_language = list(
        base_qs.values("detected_language")
        .annotate(count=Count("feedback_id"))
        .order_by("-count")[:10]
    )

    return {
        "date_from": date_from.isoformat(),
        "date_to": date_to.isoformat(),
        "total": total,
        "by_status": by_status,
        "by_channel": by_channel,
        "by_language": by_language,
    }


def get_channel_breakdown() -> list[dict[str, Any]]:
    """Return total feedback count per channel (all time)."""
    return list(
        Feedback.objects.values("channel")
        .annotate(count=Count("feedback_id"))
        .order_by("-count")
    )


def get_sentiment_trends(days: int = 30) -> list[dict[str, Any]]:
    """
    Return daily sentiment counts for the past `days` days.
    Each entry: {"date": "YYYY-MM-DD", "sentiment": "Positive", "count": 5}
    """
    since = date.today() - timedelta(days=days)
    rows = (
        Feedback.objects.filter(submitted_at__date__gte=since, sentiment__isnull=False)
        .annotate(day=TruncDate("submitted_at"))
        .values("day", "sentiment__sentiment_label")
        .annotate(count=Count("feedback_id"))
        .order_by("day", "sentiment__sentiment_label")
    )
    return [
        {
            "date": row["day"].isoformat(),
            "sentiment": row["sentiment__sentiment_label"],
            "count": row["count"],
        }
        for row in rows
    ]


def get_urgency_breakdown() -> list[dict[str, Any]]:
    """Return feedback counts grouped by urgency level (all time)."""
    return list(
        Feedback.objects.values("urgency_level")
        .annotate(count=Count("feedback_id"))
        .order_by("urgency_level")
    )
