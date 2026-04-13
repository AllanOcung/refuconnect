"""
Message router — dispatches a Notification to the appropriate channel adapter.
"""
from __future__ import annotations

import logging

from apps.common.encryption import decrypt_field
from apps.notifications.models import Notification

logger = logging.getLogger(__name__)


def route_notification(notification: Notification) -> bool:
    """
    Decrypt the recipient's phone number and send via the correct adapter.
    Returns True on success, False on failure.
    """
    from apps.notifications.services.delivery_tracker import mark_failed, mark_sent

    try:
        phone = decrypt_field(notification.user_consent.phone_number_encrypted)
    except Exception as exc:
        logger.error(
            "route_notification: Failed to decrypt phone for notification %s: %s",
            notification.pk,
            exc,
        )
        mark_failed(notification)
        return False

    channel = notification.user_consent.channel_preference
    message_text = notification.message_body

    try:
        if channel == notification.user_consent.ChannelPreference.SMS:
            from apps.feedback.adapters.sms import SMSAdapter
            success = SMSAdapter().send(phone, message_text)
        elif channel == notification.user_consent.ChannelPreference.WHATSAPP:
            from apps.feedback.adapters.whatsapp import WhatsAppAdapter
            success = WhatsAppAdapter().send_message(phone, message_text)
        else:
            logger.warning("route_notification: Unknown channel %s", channel)
            success = False
    except Exception as exc:
        logger.error(
            "route_notification: Delivery error for notification %s: %s",
            notification.pk,
            exc,
        )
        success = False

    if success:
        mark_sent(notification)
    else:
        mark_failed(notification)

    return success
