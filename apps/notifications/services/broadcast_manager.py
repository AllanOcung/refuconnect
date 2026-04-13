"""
Broadcast manager — creates Notification records for all consenting users.
"""
from __future__ import annotations

import logging
from typing import Optional

from apps.dashboard.models import User
from apps.feedback.models import Feedback
from apps.notifications.models import Notification, UserConsent
from apps.notifications.services.response_composer import compose_broadcast

logger = logging.getLogger(__name__)


def create_broadcast(
    sender: User,
    message: str,
    channel: str,
    language: str = "en",
    message_type: str = Notification.MessageType.BROADCAST_GENERAL,
    target_feedback: Optional[Feedback] = None,
    broadcast_type: str = "broadcast_general",
) -> list[Notification]:
    """
    Create a Notification record for every UserConsent record that matches
    the given channel preference.

    Returns the list of created Notification objects.
    """
    consents = UserConsent.objects.filter(
        channel_preference=channel,
        is_active=True,
    )

    message_body = compose_broadcast(message, language=language, broadcast_type=broadcast_type)
    created: list[Notification] = []

    for consent in consents:
        try:
            notification = Notification.objects.create(
                user_consent=consent,
                related_feedback=target_feedback,
                message_type=message_type,
                message_body=message_body,
                sent_by=sender,
                delivery_status=Notification.DeliveryStatus.QUEUED,
            )
            created.append(notification)
        except Exception as exc:
            logger.error(
                "create_broadcast: Failed to create notification for consent %s: %s",
                consent.pk,
                exc,
            )

    logger.info("create_broadcast: Queued %d notifications.", len(created))
    return created
