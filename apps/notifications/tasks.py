"""
Celery tasks for the notifications app.
"""
from __future__ import annotations

import logging

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def send_notification_task(self, notification_id: int) -> None:
    """Send a single queued Notification via its preferred channel."""
    from apps.notifications.models import Notification
    from apps.notifications.services.message_router import route_notification

    try:
        notification = Notification.objects.select_related("user_consent").get(pk=notification_id)
    except Notification.DoesNotExist:
        logger.error("send_notification_task: Notification %s not found.", notification_id)
        return

    if notification.delivery_status == Notification.DeliveryStatus.DELIVERED:
        return

    success = route_notification(notification)
    if not success:
        logger.warning(
            "send_notification_task: Delivery failed for notification %s. Retrying.",
            notification_id,
        )
        raise self.retry()


@shared_task
def retry_failed_notifications() -> int:
    """Re-queue Failed notifications (called by Celery Beat every 15 minutes)."""
    from apps.notifications.models import Notification

    failed_ids = list(
        Notification.objects.filter(
            delivery_status=Notification.DeliveryStatus.FAILED
        ).values_list("pk", flat=True)
    )

    for notification_id in failed_ids:
        send_notification_task.delay(notification_id)

    logger.info("retry_failed_notifications: Re-queued %d notifications.", len(failed_ids))
    return len(failed_ids)
