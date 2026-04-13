"""
Delivery tracker — updates Notification delivery status.
"""
from __future__ import annotations

import logging
from typing import Any

from apps.notifications.models import Notification

logger = logging.getLogger(__name__)


def mark_sent(notification: Notification) -> None:
    notification.delivery_status = Notification.DeliveryStatus.SENT
    notification.save(update_fields=["delivery_status"])


def mark_delivered(notification: Notification) -> None:
    notification.delivery_status = Notification.DeliveryStatus.DELIVERED
    notification.save(update_fields=["delivery_status"])


def mark_read(notification: Notification) -> None:
    notification.delivery_status = Notification.DeliveryStatus.READ
    notification.save(update_fields=["delivery_status"])


def mark_failed(notification: Notification) -> None:
    notification.delivery_status = Notification.DeliveryStatus.FAILED
    notification.save(update_fields=["delivery_status"])


def handle_webhook_update(data: dict[str, Any]) -> None:
    """
    Update delivery status based on an inbound webhook payload.
    Expects data with keys: "notification_id" and "status".
    """
    notification_id = data.get("notification_id")
    raw_status = (data.get("status") or "").lower()

    if not notification_id:
        logger.warning("handle_webhook_update: missing notification_id in payload")
        return

    try:
        notification = Notification.objects.get(pk=notification_id)
    except Notification.DoesNotExist:
        logger.warning("handle_webhook_update: Notification %s not found", notification_id)
        return

    status_map = {
        "sent": mark_sent,
        "delivered": mark_delivered,
        "read": mark_read,
        "failed": mark_failed,
    }

    handler = status_map.get(raw_status)
    if handler:
        handler(notification)
    else:
        logger.warning("handle_webhook_update: Unknown status %s", raw_status)
