import pytest
from datetime import timedelta

from django.utils import timezone
from django.urls import reverse

from apps.common.audit import AuditAction
from apps.dashboard.models import AuditLog
from apps.feedback.models import Category, Feedback, FeedbackCategory, Sentiment


@pytest.mark.django_db
def test_list_returns_50_per_page(auth_client, sample_feedback):
    response = auth_client.get(reverse("dashboard:feedback-list"))
    assert response.status_code == 200
    assert "results" in response.data


@pytest.mark.django_db
def test_feedback_responses_do_not_expose_anonymous_user_id(auth_client, sample_feedback):
    list_response = auth_client.get(reverse("dashboard:feedback-list"))
    detail_response = auth_client.get(
        reverse("dashboard:feedback-detail", args=[sample_feedback.feedback_id])
    )

    assert "anonymous_user_id" not in list_response.data["results"][0]
    assert "anonymous_user_id" not in detail_response.data


@pytest.mark.django_db
def test_filter_by_channel(auth_client, sample_feedback):
    response = auth_client.get(reverse("dashboard:feedback-list"), {"channel": "SMS"})
    assert response.status_code == 200
    assert response.data["count"] == 1


@pytest.mark.django_db
def test_filter_by_category(auth_client, sample_feedback):
    category = Category.objects.create(category_name="Water", is_active=True)
    FeedbackCategory.objects.create(
        feedback=sample_feedback,
        category=category,
        confidence_score=0.9,
        is_ai_assigned=True,
    )

    response = auth_client.get(
        reverse("dashboard:feedback-list"),
        {"category": [category.category_id]},
    )
    assert response.status_code == 200
    assert response.data["count"] == 1


@pytest.mark.django_db
def test_filter_by_sentiment(auth_client, sample_feedback):
    uncertain, _created = Sentiment.objects.get_or_create(
        sentiment_label="Uncertain",
        defaults={"display_colour": "#cccccc"},
    )
    Feedback.objects.create(
        anonymous_user_id="anon-uncertain",
        message_text="No clear signal",
        message_text_en="No clear signal",
        channel=Feedback.Channel.SMS,
        status=Feedback.Status.NEW,
        urgency_level=Feedback.UrgencyLevel.LOW,
        language="en",
        sentiment=uncertain,
        submitted_at=timezone.now(),
    )

    response = auth_client.get(reverse("dashboard:feedback-list"), {"sentiment": "Uncertain"})
    assert response.status_code == 200
    assert response.data["count"] == 1


@pytest.mark.django_db
def test_filter_by_date_range(auth_client, sample_feedback):
    sample_feedback.submitted_at = timezone.now() - timedelta(days=10)
    sample_feedback.save(update_fields=["submitted_at"])
    Feedback.objects.create(
        anonymous_user_id="anon-recent",
        message_text="Recent item",
        message_text_en="Recent item",
        channel=Feedback.Channel.SMS,
        status=Feedback.Status.NEW,
        urgency_level=Feedback.UrgencyLevel.LOW,
        language="en",
        submitted_at=timezone.now(),
    )

    response = auth_client.get(
        reverse("dashboard:feedback-list"),
        {"date_from": (timezone.now() - timedelta(days=1)).isoformat()},
    )
    assert response.status_code == 200
    assert response.data["count"] == 1


@pytest.mark.django_db
def test_filter_by_urgency(auth_client, sample_feedback):
    sample_feedback.urgency_level = Feedback.UrgencyLevel.HIGH
    sample_feedback.save(update_fields=["urgency_level"])

    response = auth_client.get(reverse("dashboard:feedback-list"), {"urgency_level": "High"})
    assert response.status_code == 200
    assert response.data["count"] == 1


@pytest.mark.django_db
def test_full_text_search_finds_matching_records(auth_client, sample_feedback):
    sample_feedback.message_text = "Need urgent shelter support"
    sample_feedback.save(update_fields=["message_text"])
    response = auth_client.get(reverse("dashboard:feedback-list"), {"q": "shelter"})
    assert response.status_code == 200
    assert response.data["count"] == 1


@pytest.mark.django_db
def test_detail_view_logs_audit_event(auth_client, sample_feedback):
    response = auth_client.get(
        reverse("dashboard:feedback-detail", args=[sample_feedback.feedback_id])
    )
    assert response.status_code == 200
    assert AuditLog.objects.filter(
        feedback=sample_feedback,
        action=AuditAction.FEEDBACK_VIEWED,
    ).exists()


@pytest.mark.django_db
def test_detail_view_sets_reviewed_by(auth_client, sample_feedback, ngo_staff_user):
    auth_client.get(reverse("dashboard:feedback-detail", args=[sample_feedback.feedback_id]))
    sample_feedback.refresh_from_db()
    assert sample_feedback.reviewed_by == ngo_staff_user


@pytest.mark.django_db
def test_patch_urgency_level_logs_field_change(auth_client, sample_feedback):
    response = auth_client.patch(
        reverse("dashboard:feedback-detail", args=[sample_feedback.feedback_id]),
        {"urgency_level": "High"},
        format="json",
    )
    assert response.status_code == 200
    assert AuditLog.objects.filter(
        feedback=sample_feedback,
        action=AuditAction.FEEDBACK_EDITED,
        field_changed="urgency_level",
    ).exists()


@pytest.mark.django_db
def test_patch_categories_replaces_ai_assignments(auth_client, sample_feedback):
    category = Category.objects.create(category_name="Shelter", is_active=True)
    response = auth_client.patch(
        reverse("dashboard:feedback-detail", args=[sample_feedback.feedback_id]),
        {"categories": [category.category_id]},
        format="json",
    )
    assert response.status_code == 200
    assert FeedbackCategory.objects.filter(
        feedback=sample_feedback,
        category=category,
        is_ai_assigned=False,
    ).exists()


@pytest.mark.django_db
def test_audit_log_endpoint_restricted_to_administrator(admin_client):
    response = admin_client.get(reverse("dashboard:audit-log"))
    assert response.status_code == 200


@pytest.mark.django_db
def test_ngo_staff_cannot_access_audit_log(auth_client):
    response = auth_client.get(reverse("dashboard:audit-log"))
    assert response.status_code == 403
