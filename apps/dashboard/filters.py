from __future__ import annotations

import django_filters
from django.db.models import Q
from django.db.models import CharField
from django.db.models.functions import Cast

from apps.dashboard.models import AuditLog
from apps.feedback.models import Category, Feedback


class FeedbackFilterSet(django_filters.FilterSet):
    date_from = django_filters.DateTimeFilter(
        field_name="submitted_at", lookup_expr="gte"
    )
    date_to = django_filters.DateTimeFilter(
        field_name="submitted_at", lookup_expr="lte"
    )
    category = django_filters.ModelMultipleChoiceFilter(
        field_name="feedback_categories__category",
        queryset=Category.objects.filter(is_active=True),
    )
    sentiment = django_filters.MultipleChoiceFilter(
        field_name="sentiment__sentiment_label",
        choices=[
            ("Positive", "Positive"),
            ("Neutral", "Neutral"),
            ("Negative", "Negative"),
            ("Uncertain", "Uncertain"),
        ],
    )
    channel = django_filters.MultipleChoiceFilter(choices=Feedback.Channel.choices)
    language = django_filters.CharFilter(field_name="language")
    urgency_level = django_filters.MultipleChoiceFilter(
        choices=Feedback.UrgencyLevel.choices
    )
    status = django_filters.MultipleChoiceFilter(
        choices=[
            (Feedback.Status.NEW, Feedback.Status.NEW),
            (Feedback.Status.PROCESSING, Feedback.Status.PROCESSING),
            (Feedback.Status.PROCESSED, Feedback.Status.PROCESSED),
            (Feedback.Status.PROCESSING_FAILED, Feedback.Status.PROCESSING_FAILED),
        ]
    )
    location = django_filters.CharFilter(field_name="location", lookup_expr="icontains")
    is_flagged = django_filters.BooleanFilter()
    q = django_filters.CharFilter(method="full_text_search")

    class Meta:
        model = Feedback
        fields = [
            "date_from",
            "date_to",
            "category",
            "sentiment",
            "channel",
            "language",
            "urgency_level",
            "status",
            "location",
            "is_flagged",
            "q",
        ]

    def full_text_search(self, queryset, name, value):
        return queryset.annotate(
            feedback_id_text=Cast("feedback_id", output_field=CharField())
        ).filter(
            Q(message_text__icontains=value)
            | Q(message_text_en__icontains=value)
            | Q(feedback_id_text__icontains=value)
        )


class AuditLogFilterSet(django_filters.FilterSet):
    # user_id = actor (who performed the action). target_user = subject (who it
    # was performed on). Names are intentionally distinct to avoid confusion.
    user_id = django_filters.NumberFilter(field_name="user_id")
    target_user = django_filters.NumberFilter(field_name="target_user_id")
    feedback_id = django_filters.NumberFilter(field_name="feedback_id")
    action = django_filters.CharFilter(field_name="action")
    date_from = django_filters.DateTimeFilter(field_name="created_at", lookup_expr="gte")
    date_to = django_filters.DateTimeFilter(field_name="created_at", lookup_expr="lte")

    class Meta:
        model = AuditLog
        fields = [
            "user_id",
            "target_user",
            "feedback_id",
            "action",
            "date_from",
            "date_to",
        ]
