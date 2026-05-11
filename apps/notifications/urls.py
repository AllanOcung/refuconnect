"""
URL configuration for the notifications app.

All paths here are mounted under /api/v1/ in the root config/urls.py.
"""
from __future__ import annotations

from django.urls import path

from apps.notifications.views import (
    # Delivery webhooks
    SMSDeliveryWebhookView,
    WhatsAppDeliveryWebhookView,
    # Targeted responses
    FeedbackResponseListView,
    SendResponseView,
    # Broadcasts
    BroadcastCancelView,
    BroadcastDetailView,
    BroadcastEstimateView,
    BroadcastListCreateView,
    BroadcastProgressView,
    # Templates
    TemplateDetailView,
    TemplateKeyListView,
    TemplateListCreateView,
)

app_name = "notifications"

urlpatterns = [
    # ── Delivery webhooks ────────────────────────────────────────────────
    path("delivery/sms/", SMSDeliveryWebhookView.as_view(), name="delivery-sms"),
    path("delivery/whatsapp/", WhatsAppDeliveryWebhookView.as_view(), name="delivery-whatsapp"),

    # ── Targeted responses ───────────────────────────────────────────────
    path(
        "feedback/<int:feedback_id>/respond/",
        SendResponseView.as_view(),
        name="send-response",
    ),
    path(
        "feedback/<int:feedback_id>/responses/",
        FeedbackResponseListView.as_view(),
        name="feedback-responses",
    ),

    # ── Broadcasts ───────────────────────────────────────────────────────
    path("broadcasts/", BroadcastListCreateView.as_view(), name="broadcast-list-create"),
    path("broadcasts/estimate/", BroadcastEstimateView.as_view(), name="broadcast-estimate"),
    path("broadcasts/<int:broadcast_id>/", BroadcastDetailView.as_view(), name="broadcast-detail"),
    path(
        "broadcasts/<int:broadcast_id>/progress/",
        BroadcastProgressView.as_view(),
        name="broadcast-progress",
    ),
    path(
        "broadcasts/<int:broadcast_id>/cancel/",
        BroadcastCancelView.as_view(),
        name="broadcast-cancel",
    ),

    # ── Templates (admin only) ───────────────────────────────────────────
    path("templates/", TemplateListCreateView.as_view(), name="template-list-create"),
    path("templates/keys/", TemplateKeyListView.as_view(), name="template-keys"),
    path("templates/<int:template_id>/", TemplateDetailView.as_view(), name="template-detail"),
]