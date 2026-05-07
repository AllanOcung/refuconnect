from __future__ import annotations

import hashlib
import json
from datetime import timedelta

from django.core.cache import cache
from django.db.models import Count
from django.db.models.functions import TruncDate
from django.utils import timezone

from apps.dashboard.filters import FeedbackFilterSet
from apps.feedback.models import Alert, Feedback
from apps.nlp.models import ThemeCluster


class AnalyticsEngine:
    cache_timeout = 60
    cache_registry_timeout = 3600

    def get_summary(self, filters: dict, org_id: int | str) -> dict:
        cache_key = self._cache_key(filters, org_id)
        cached = cache.get(cache_key)
        if cached:
            return cached
        result = self._compute_summary(filters)
        result["cached_at"] = timezone.now().isoformat()
        cache.set(cache_key, result, timeout=self.cache_timeout)
        self._remember_cache_key(org_id, cache_key)
        return result

    def get_sentiment_timeseries(self, days: int, filters: dict | None = None) -> list:
        filters = filters or {}
        today = timezone.localdate()
        since = today - timedelta(days=days - 1)
        qs = self._filtered_feedback(filters).filter(submitted_at__date__gte=since)
        rows = (
            qs.annotate(day=TruncDate("submitted_at"))
            .values("day", "sentiment__sentiment_label")
            .annotate(count=Count("feedback_id"))
            .order_by("day")
        )
        by_day = {
            (since + timedelta(days=offset)).isoformat(): {
                "date": (since + timedelta(days=offset)).isoformat(),
                "Positive": 0,
                "Neutral": 0,
                "Negative": 0,
                "Uncertain": 0,
            }
            for offset in range(days)
        }
        for row in rows:
            if row["day"] is None:
                continue
            day_key = row["day"].isoformat()
            label = row["sentiment__sentiment_label"] or "Uncertain"
            if label in by_day.get(day_key, {}):
                by_day[day_key][label] = row["count"]
        return list(by_day.values())

    def get_theme_summary(self) -> list[dict]:
        latest_week = (
            ThemeCluster.objects.order_by("-week_start_date")
            .values_list("week_start_date", flat=True)
            .first()
        )
        if latest_week is None:
            return []
        return list(
            ThemeCluster.objects.filter(week_start_date=latest_week)
            .order_by("-feedback_count")[:5]
            .values(
                "cluster_label",
                "feedback_count",
                "avg_sentiment",
                "top_keywords",
                "week_start_date",
            )
        )

    def invalidate_cache(self, org_id: int | str) -> None:
        pattern = f"analytics:{self._org_cache_part(org_id)}:*"
        delete_pattern = getattr(cache, "delete_pattern", None)
        if callable(delete_pattern):
            delete_pattern(pattern)
            cache.delete(self._registry_key(org_id))
            return

        registry_key = self._registry_key(org_id)
        keys = cache.get(registry_key, [])
        for key in keys:
            cache.delete(key)
        cache.delete(registry_key)

    def _cache_key(self, filters: dict, org_id: int | str) -> str:
        digest = hashlib.md5(
            json.dumps(filters, sort_keys=True, default=str).encode()
        ).hexdigest()
        return f"analytics:{self._org_cache_part(org_id)}:{digest}"

    def _org_cache_part(self, org_id: int | str) -> str:
        raw = str(org_id)
        if raw.isalnum():
            return raw
        return hashlib.md5(raw.encode()).hexdigest()

    def _registry_key(self, org_id: int | str) -> str:
        return f"analytics:keys:{self._org_cache_part(org_id)}"

    def _remember_cache_key(self, org_id: int | str, cache_key: str) -> None:
        registry_key = self._registry_key(org_id)
        keys = set(cache.get(registry_key, []))
        keys.add(cache_key)
        cache.set(registry_key, sorted(keys), timeout=self.cache_registry_timeout)

    def _filtered_feedback(self, filters: dict):
        qs = Feedback.objects.select_related("sentiment").prefetch_related(
            "feedback_categories__category"
        )
        filterset = FeedbackFilterSet(data=filters, queryset=qs)
        return filterset.qs.distinct() if filterset.is_valid() else qs

    def _compute_summary(self, filters: dict) -> dict:
        qs = self._filtered_feedback(filters)
        today = timezone.localdate()
        week_start = today - timedelta(days=today.weekday())
        month_start = today.replace(day=1)
        total = qs.count()

        trend_start = today - timedelta(days=6)
        trend_rows = (
            qs.filter(submitted_at__date__gte=trend_start)
            .annotate(day=TruncDate("submitted_at"))
            .values("day")
            .annotate(count=Count("feedback_id"))
        )
        trend_counts = {
            (trend_start + timedelta(days=offset)).isoformat(): 0
            for offset in range(7)
        }
        for row in trend_rows:
            if row["day"]:
                trend_counts[row["day"].isoformat()] = row["count"]

        sentiment_counts = {
            "Positive": 0,
            "Neutral": 0,
            "Negative": 0,
            "Uncertain": 0,
        }
        for row in qs.values("sentiment__sentiment_label").annotate(
            count=Count("feedback_id")
        ):
            label = row["sentiment__sentiment_label"] or "Uncertain"
            if label in sentiment_counts:
                sentiment_counts[label] += row["count"]
        sentiment_distribution = {
            label: {
                "count": count,
                "percentage": round((count / total * 100), 2) if total else 0.0,
            }
            for label, count in sentiment_counts.items()
        }

        category_rows = (
            qs.values("feedback_categories__category__category_name")
            .annotate(count=Count("feedback_id", distinct=True))
            .order_by("-count")[:5]
        )
        top_categories = [
            {
                "category_name": row["feedback_categories__category__category_name"],
                "count": row["count"],
                "percentage": round((row["count"] / total * 100), 2) if total else 0.0,
            }
            for row in category_rows
            if row["feedback_categories__category__category_name"]
        ]

        channel_distribution = {}
        for channel, _label in Feedback.Channel.choices:
            count = qs.filter(channel=channel).count()
            channel_distribution[channel] = {
                "count": count,
                "percentage": round((count / total * 100), 2) if total else 0.0,
            }

        geographic_distribution = [
            {"settlement": row["location"], "count": row["count"]}
            for row in qs.exclude(location__isnull=True)
            .exclude(location="")
            .values("location")
            .annotate(count=Count("feedback_id"))
            .order_by("-count")
        ]

        return {
            "volume": {
                "today": qs.filter(submitted_at__date=today).count(),
                "this_week": qs.filter(submitted_at__date__gte=week_start).count(),
                "this_month": qs.filter(submitted_at__date__gte=month_start).count(),
                "total": total,
                "trend_7_days": [
                    {"date": day, "count": count}
                    for day, count in sorted(trend_counts.items())
                ],
            },
            "sentiment_distribution": sentiment_distribution,
            "top_categories": top_categories,
            "channel_distribution": channel_distribution,
            "geographic_distribution": geographic_distribution,
            "theme_summary": self.get_theme_summary(),
            "urgent_open_count": Alert.objects.filter(
                status=Alert.AlertStatus.OPEN,
                priority_level=Alert.Priority.HIGH,
            ).count(),
            "unprocessed_count": qs.filter(
                status__in=[Feedback.Status.NEW, Feedback.Status.PROCESSING]
            ).count(),
            "sentiment_trend": self.get_sentiment_timeseries(30, filters),
        }
