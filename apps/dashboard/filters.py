"""
Django-filter FilterSets for the dashboard app.
"""
from __future__ import annotations

import django_filters

from apps.feedback.models import Feedback


class FeedbackFilter(django_filters.FilterSet):
    """Filter feedback by date range, channel, status, urgency, language, location."""

    date_from = django_filters.DateFilter(field_name="submitted_at", lookup_expr="date__gte")
    date_to = django_filters.DateFilter(field_name="submitted_at", lookup_expr="date__lte")
    channel = django_filters.ChoiceFilter(choices=Feedback.Channel.choices)
    status = django_filters.ChoiceFilter(choices=Feedback.Status.choices)
    urgency_level = django_filters.ChoiceFilter(choices=Feedback.UrgencyLevel.choices)
    detected_language = django_filters.CharFilter(lookup_expr="iexact")
    location_mentioned = django_filters.CharFilter(lookup_expr="icontains")
    is_flagged = django_filters.BooleanFilter()
    sentiment = django_filters.NumberFilter(field_name="sentiment__sentiment_id")

    class Meta:
        model = Feedback
        fields = [
            "date_from",
            "date_to",
            "channel",
            "status",
            "urgency_level",
            "detected_language",
            "location_mentioned",
            "is_flagged",
            "sentiment",
        ]
