"""
pytest configuration and factory-boy factories for all RefuConnect models.
"""
from __future__ import annotations

import factory
import pytest
from django.utils import timezone
from factory.django import DjangoModelFactory
from rest_framework.test import APIClient


# -------------------------------------------------------------------------
# Factories
# -------------------------------------------------------------------------


class UserFactory(DjangoModelFactory):
    class Meta:
        model = "dashboard.User"
        skip_postgeneration_save = True

    email = factory.Sequence(lambda n: f"user{n}@refuconnect.test")
    full_name = factory.Faker("name")
    role = "NGO_Staff"
    status = "Active"
    organisation = "Test NGO"

    @factory.post_generation
    def password(obj, create, extracted, **kwargs):
        raw = extracted or "TestPass123!"
        obj.set_password(raw)
        if create:
            obj.save()


class AdminUserFactory(UserFactory):
    role = "Administrator"
    email = factory.Sequence(lambda n: f"admin{n}@refuconnect.test")


class SentimentFactory(DjangoModelFactory):
    class Meta:
        model = "feedback.Sentiment"
        django_get_or_create = ("sentiment_label",)

    sentiment_label = "Positive"
    display_colour = "#22c55e"


class CategoryFactory(DjangoModelFactory):
    class Meta:
        model = "feedback.Category"
        django_get_or_create = ("category_name",)

    category_name = factory.Sequence(lambda n: f"Category {n}")
    is_active = True


class FeedbackFactory(DjangoModelFactory):
    class Meta:
        model = "feedback.Feedback"

    anonymous_user_id = factory.Faker("uuid4")
    message_original = factory.Faker("paragraph")
    message_normalised = factory.LazyAttribute(lambda obj: obj.message_original)
    channel = "SMS"
    status = "Pending"
    urgency_level = "Low"
    detected_language = "en"
    submitted_at = factory.LazyFunction(timezone.now)


class FeedbackCategoryFactory(DjangoModelFactory):
    class Meta:
        model = "feedback.FeedbackCategory"

    feedback = factory.SubFactory(FeedbackFactory)
    category = factory.SubFactory(CategoryFactory)
    confidence_score = 0.85


class FeedbackMediaFactory(DjangoModelFactory):
    class Meta:
        model = "feedback.FeedbackMedia"

    feedback = factory.SubFactory(FeedbackFactory)
    media_type = "image"
    file_url = factory.Faker("url")


class AlertFactory(DjangoModelFactory):
    class Meta:
        model = "feedback.Alert"

    feedback = factory.SubFactory(FeedbackFactory)
    priority = "High"
    alert_status = "Open"
    alert_message = factory.Faker("sentence")


class AIModelLogFactory(DjangoModelFactory):
    class Meta:
        model = "nlp.AIModelLog"

    model_type = "sentiment"
    model_version = "v1.0.0"
    training_data_size = 1000
    accuracy_score = 0.90
    trained_by = factory.SubFactory(UserFactory)


class ThemeClusterFactory(DjangoModelFactory):
    class Meta:
        model = "nlp.ThemeCluster"

    week_start_date = factory.LazyFunction(lambda: timezone.now().date())
    cluster_label = factory.Sequence(lambda n: f"Theme {n}")
    top_keywords = ["water", "food", "shelter"]
    feedback_count = 10


class UserConsentFactory(DjangoModelFactory):
    class Meta:
        model = "notifications.UserConsent"

    anonymous_user_id = factory.Faker("uuid4")
    phone_number_encrypted = "dGVzdA=="  # placeholder encrypted value
    consent_type = "follow_up"
    channel_preference = "SMS"
    language_preference = "en"
    is_active = True


class NotificationFactory(DjangoModelFactory):
    class Meta:
        model = "notifications.Notification"

    user_consent = factory.SubFactory(UserConsentFactory)
    message_type = "Acknowledgement"
    message_body = factory.Faker("sentence")
    delivery_status = "Queued"
    sent_by = factory.SubFactory(UserFactory)


# -------------------------------------------------------------------------
# Fixtures
# -------------------------------------------------------------------------


@pytest.fixture
def api_client():
    """Unauthenticated DRF API client."""
    return APIClient()


@pytest.fixture
def admin_user(db):
    """Persisted Administrator user."""
    return AdminUserFactory(password="AdminPass123!")


@pytest.fixture
def ngo_staff_user(db):
    """Persisted NGO Staff user."""
    return UserFactory(password="StaffPass123!")


@pytest.fixture
def auth_client(api_client, ngo_staff_user):
    """APIClient authenticated as an NGO Staff user via JWT."""
    from rest_framework_simplejwt.tokens import RefreshToken

    refresh = RefreshToken.for_user(ngo_staff_user)
    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")
    return api_client


@pytest.fixture
def admin_client(api_client, admin_user):
    """APIClient authenticated as an Administrator via JWT."""
    from rest_framework_simplejwt.tokens import RefreshToken

    refresh = RefreshToken.for_user(admin_user)
    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")
    return api_client


@pytest.fixture
def sample_sentiment(db):
    """Positive sentiment seed object."""
    return SentimentFactory(sentiment_label="Positive", display_colour="#22c55e")


@pytest.fixture
def sample_feedback(db, sample_sentiment):
    """A single persisted Feedback object."""
    return FeedbackFactory(sentiment=sample_sentiment)
