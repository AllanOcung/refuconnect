"""
Feedback app URL configuration.

Webhook paths (public, no auth):
  POST /webhooks/sms/         — Africa's Talking SMS inbound
  POST /webhooks/ussd/        — Africa's Talking USSD session
  GET+POST /webhooks/whatsapp/ — Meta WhatsApp verify + inbound

Dashboard API paths (JWT required):
  GET  /                      — Paginated feedback list
  GET  /<id>/                 — Single feedback detail
  PATCH /<id>/flag/           — Flag / un-flag a feedback record
"""
from django.urls import path

from apps.feedback.adapters.sms import SMSWebhookView
from apps.feedback.adapters.ussd import USSDSessionView
from apps.feedback.adapters.whatsapp import WhatsAppWebhookView

from .views import (
    FeedbackDetailView,
    FeedbackFlagView,
    FeedbackListView,
    LanguageDetectionReviewView,
)

app_name = "feedback"

urlpatterns = [
    # ── Public webhook endpoints (unauthenticated) ──────────────────────────
    path("webhooks/sms/", SMSWebhookView.as_view(), name="sms-webhook"),
    path("webhooks/ussd/", USSDSessionView.as_view(), name="ussd-webhook"),
    path("webhooks/whatsapp/", WhatsAppWebhookView.as_view(), name="whatsapp-webhook"),

    # ── Authenticated dashboard endpoints ───────────────────────────────────
    path("", FeedbackListView.as_view(), name="feedback-list"),
    path("language-review/", LanguageDetectionReviewView.as_view(), name="language-review"),
    path("<int:pk>/", FeedbackDetailView.as_view(), name="feedback-detail"),
    path("<int:pk>/flag/", FeedbackFlagView.as_view(), name="feedback-flag"),
]
