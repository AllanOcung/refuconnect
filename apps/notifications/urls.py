"""
URL configuration for the notifications app.
"""
from __future__ import annotations

from django.urls import path

from apps.notifications.views import (
    DeliveryWebhookView,
    NotificationListView,
    SendAcknowledgementView,
    SendBroadcastView,
)

app_name = "notifications"

urlpatterns = [
    path("", NotificationListView.as_view(), name="notification-list"),
    path("acknowledge/", SendAcknowledgementView.as_view(), name="send-acknowledgement"),
    path("broadcast/", SendBroadcastView.as_view(), name="send-broadcast"),
    path("webhook/delivery/", DeliveryWebhookView.as_view(), name="delivery-webhook"),
]
