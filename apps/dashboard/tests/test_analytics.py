import pytest
from django.core.cache import cache
from django.urls import reverse

from apps.dashboard.services.analytics_engine import AnalyticsEngine


@pytest.mark.django_db
def test_summary_returns_all_required_fields(auth_client, sample_feedback):
    response = auth_client.get(reverse("dashboard:analytics-summary"))
    assert response.status_code == 200
    for key in [
        "volume",
        "sentiment_distribution",
        "top_categories",
        "channel_distribution",
        "geographic_distribution",
        "theme_summary",
        "urgent_open_count",
        "unprocessed_count",
        "sentiment_trend",
        "cached_at",
    ]:
        assert key in response.data


@pytest.mark.django_db
def test_summary_cached_for_60_seconds(sample_feedback):
    engine = AnalyticsEngine()
    first = engine.get_summary({}, 1)
    second = engine.get_summary({}, 1)
    assert first["cached_at"] == second["cached_at"]


@pytest.mark.django_db
def test_cache_invalidated_after_feedback_edit(auth_client, sample_feedback, ngo_staff_user):
    engine = AnalyticsEngine()
    cached = engine.get_summary({}, ngo_staff_user.organisation)
    assert cache.get(engine._cache_key({}, ngo_staff_user.organisation)) == cached

    response = auth_client.patch(
        reverse("dashboard:feedback-detail", args=[sample_feedback.feedback_id]),
        {"urgency_level": "High"},
        format="json",
    )

    assert response.status_code == 200
    assert cache.get(engine._cache_key({}, ngo_staff_user.organisation)) is None


@pytest.mark.django_db
def test_sentiment_distribution_percentages_sum_to_100(sample_feedback):
    data = AnalyticsEngine().get_summary({}, 1)
    total = sum(row["percentage"] for row in data["sentiment_distribution"].values())
    assert total in (0, 100.0)


@pytest.mark.django_db
def test_sentiment_trend_returns_correct_number_of_days(auth_client, sample_feedback):
    response = auth_client.get(reverse("dashboard:analytics-sentiment-trend"), {"days": 7})
    assert response.status_code == 200
    assert len(response.data) == 7
