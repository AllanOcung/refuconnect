"""
C-24: DeliveryTracker
=====================
Handles inbound delivery-status callbacks from Africa's Talking (SMS) and
Meta (WhatsApp) and updates the corresponding Notification records.

Webhook endpoints must ALWAYS return HTTP 200 to the gateway, even on errors,
to prevent the gateway from retrying indefinitely. Catching exceptions and
returning 200 is handled in views.py; this module raises exceptions freely.
"""
from __future__ import annotations

import logging

from django.core.cache import cache
from django.utils import timezone

from apps.notifications.models import Notification

logger = logging.getLogger("apps.notifications.delivery_tracker")

# Africa's Talking delivery status → normalised DeliveryStatus
_AT_STATUS_MAP: dict[str, str] = {
    "Success": Notification.DeliveryStatus.DELIVERED,
    "Sent": Notification.DeliveryStatus.SENT,
    "Buffered": Notification.DeliveryStatus.SENT,
    "Rejected": Notification.DeliveryStatus.FAILED,
    "Failed": Notification.DeliveryStatus.FAILED,
}

# WhatsApp status → normalised DeliveryStatus
_WA_STATUS_MAP: dict[str, str] = {
    "sent": Notification.DeliveryStatus.SENT,
    "delivered": Notification.DeliveryStatus.DELIVERED,
    "read": Notification.DeliveryStatus.READ,
    "failed": Notification.DeliveryStatus.FAILED,
}

# Redis key prefix for failed acknowledgement tracking
_FAILED_ACK_CACHE_PREFIX = "failed_ack:"


class DeliveryTracker:
    """
    Processes inbound delivery-status callbacks from SMS and WhatsApp gateways
    and keeps Notification records up to date.
    """

    # ------------------------------------------------------------------ #
    # SMS (Africa's Talking)                                               #
    # ------------------------------------------------------------------ #

    def handle_sms_delivery_callback(self, payload: dict) -> None:
        """
        Process an Africa's Talking delivery report.

        Expected payload shape::

            {
                "id": "ATXid_abc123",
                "status": "Success",
                "phoneNumber": "+256700123456",
                "networkCode": "63902",
                "failureReason": null,
                "retryCount": "0"
            }

        PRIVACY: ``phoneNumber`` in the payload is never logged or stored.
        """
        gateway_id = payload.get("id")
        raw_status = payload.get("status", "")

        if not gateway_id:
            logger.warning(
                "DeliveryTracker.handle_sms_delivery_callback: missing 'id' in payload"
            )
            return

        normalised = _AT_STATUS_MAP.get(raw_status)
        if normalised is None:
            logger.warning(
                "DeliveryTracker.handle_sms_delivery_callback: "
                "Unknown AT status '%s' for gateway_id=%s — treating as Sent",
                raw_status,
                gateway_id,
            )
            normalised = Notification.DeliveryStatus.SENT

        notification = self._find_by_gateway_id(gateway_id)
        if notification is None:
            logger.warning(
                "DeliveryTracker.handle_sms_delivery_callback: "
                "No Notification found for gateway_message_id='%s' — "
                "possible race condition (callback arrived before DB commit).",
                gateway_id,
            )
            return

        notification.delivery_status = normalised

        if normalised == Notification.DeliveryStatus.DELIVERED:
            notification.delivered_at = timezone.now()

        notification.save(update_fields=["delivery_status", "delivered_at"])

        if normalised == Notification.DeliveryStatus.FAILED:
            self._handle_permanent_failure(notification)

    # ------------------------------------------------------------------ #
    # WhatsApp (Meta)                                                      #
    # ------------------------------------------------------------------ #

    def handle_whatsapp_status_callback(self, payload: dict) -> None:
        """
        Process a WhatsApp delivery/read status object.

        Meta embeds these inside the same webhook payload as inbound messages.
        The status object shape::

            {
                "id": "wamid.xxx",
                "status": "delivered",
                "timestamp": "1700000000",
                "recipient_id": "256700123456"
            }

        PRIVACY: ``recipient_id`` is never logged or stored.
        """
        gateway_id = payload.get("id")
        raw_status = (payload.get("status") or "").lower()

        if not gateway_id:
            logger.warning(
                "DeliveryTracker.handle_whatsapp_status_callback: missing 'id' in payload"
            )
            return

        normalised = _WA_STATUS_MAP.get(raw_status)
        if normalised is None:
            logger.warning(
                "DeliveryTracker.handle_whatsapp_status_callback: "
                "Unknown WA status '%s' for gateway_id=%s — ignoring.",
                raw_status,
                gateway_id,
            )
            return

        notification = self._find_by_gateway_id(gateway_id)
        if notification is None:
            logger.warning(
                "DeliveryTracker.handle_whatsapp_status_callback: "
                "No Notification found for gateway_message_id='%s'",
                gateway_id,
            )
            return

        notification.delivery_status = normalised
        update_fields = ["delivery_status"]

        if normalised == Notification.DeliveryStatus.DELIVERED:
            notification.delivered_at = timezone.now()
            update_fields.append("delivered_at")

        if normalised == Notification.DeliveryStatus.READ:
            notification.read_at = timezone.now()
            update_fields.append("read_at")
            # Read implies delivered if not already set
            if not notification.delivered_at:
                notification.delivered_at = timezone.now()
                update_fields.append("delivered_at")

        notification.save(update_fields=update_fields)

        if normalised == Notification.DeliveryStatus.FAILED:
            self._handle_permanent_failure(notification)

    # ------------------------------------------------------------------ #
    # Private helpers                                                      #
    # ------------------------------------------------------------------ #

    def _find_by_gateway_id(self, gateway_id: str) -> Notification | None:
        return Notification.objects.filter(gateway_message_id=gateway_id).first()

    def _handle_permanent_failure(self, notification: Notification) -> None:
        """
        Called when a message has permanently failed (all retries exhausted,
        gateway confirmed failure).

        For Acknowledgement failures: push to Redis 'failed ack' cache and
        notify AlertManager so the admin dashboard can surface them.
        For other types: dashboard delivery-failures view queries
        Notification.delivery_status='Failed' automatically.
        """
        logger.error(
            "DeliveryTracker._handle_permanent_failure: "
            "notification_id=%d feedback_id=%s permanently failed.",
            notification.notification_id,
            notification.feedback_id,
        )

        if notification.message_type == Notification.MessageType.ACKNOWLEDGEMENT:
            # Surface in admin dashboard via Redis cache
            cache_key = f"{_FAILED_ACK_CACHE_PREFIX}{notification.feedback_id}"
            try:
                cache.set(
                    cache_key,
                    {
                        "notification_id": notification.notification_id,
                        "feedback_id": notification.feedback_id,
                        "channel": notification.channel,
                        "failed_at": timezone.now().isoformat(),
                    },
                    timeout=86400 * 7,  # Keep for 7 days
                )
            except Exception as exc:
                logger.error(
                    "DeliveryTracker._handle_permanent_failure: "
                    "Redis cache set failed: %s",
                    exc,
                )

            # Notify AlertManager
            try:
                from apps.nlp.services.alert_manager import AlertManager  # type: ignore[import]
                AlertManager().notify_admin_of_ack_failure(notification.feedback_id)
            except Exception as exc:
                logger.warning(
                    "DeliveryTracker._handle_permanent_failure: "
                    "AlertManager notification failed: %s",
                    exc,
                )