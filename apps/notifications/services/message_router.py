"""
C-23: MessageRouter
===================
Routes outbound messages to the correct external gateway (Africa's Talking SMS
or Meta WhatsApp Business API) with retry logic and delivery tracking.

Every outbound message — acknowledgements, targeted responses, broadcasts,
alert notifications — goes through this class.

PRIVACY CONSTRAINT: Decrypted phone numbers must NEVER be logged, stored in
extra fields, or persist beyond the send() call. Zero them out immediately after
use: ``recipient = None``.
"""
from __future__ import annotations

import logging
import time

import httpx
from django.conf import settings
from django.core.mail import send_mail
from django.utils import timezone

from apps.common.exceptions import GatewayError, TemplateNotFoundError
from apps.notifications.models import Notification

logger = logging.getLogger("apps.notifications.message_router")

# Backoff delays in seconds before each retry attempt (3 attempts total)
_BACKOFF_SECONDS = [0, 30, 120]
_MAX_ATTEMPTS = 3


class MessageRouter:
    """
    Dispatches outbound messages to SMS or WhatsApp gateways.

    Instantiate once and reuse — Africa's Talking initialisation is lazy
    (only happens on first SMS send) to avoid import-time errors.
    """

    def __init__(self) -> None:
        self._at_initialised = False
        self._sms = None  # Africa's Talking SMS service handle

    # ------------------------------------------------------------------ #
    # Public methods                                                       #
    # ------------------------------------------------------------------ #

    def send(
        self,
        channel: str,
        recipient: str,
        body: str,
        media_url: str | None = None,
        notification_record: Notification | None = None,
    ) -> dict:
        """
        Send a message to the given recipient via the specified channel.

        Parameters
        ----------
        channel:             'SMS' or 'WhatsApp'
        recipient:           E.164 phone number (with + prefix)
        body:                Message text
        media_url:           Optional image URL (WhatsApp only)
        notification_record: If provided, delivery status is updated in place.

        Returns
        -------
        {'status': 'Sent'|'Failed', 'gateway_message_id': str|None}

        PRIVACY: ``recipient`` is a plain-text phone number — it must be zeroed
        out by the caller immediately after this method returns.
        """
        attempt = 0

        while attempt < _MAX_ATTEMPTS:
            if attempt > 0:
                time.sleep(_BACKOFF_SECONDS[attempt])

            try:
                if channel == "SMS":
                    result = self._send_via_africas_talking(recipient, body)
                elif channel == "WhatsApp":
                    result = self._send_via_whatsapp(recipient, body, media_url)
                else:
                    logger.error("MessageRouter.send: Unknown channel '%s'", channel)
                    break

                if notification_record:
                    notification_record.delivery_status = Notification.DeliveryStatus.SENT
                    notification_record.sent_at = timezone.now()
                    notification_record.gateway_message_id = result["message_id"]
                    notification_record.save(
                        update_fields=["delivery_status", "sent_at", "gateway_message_id"]
                    )

                return {"status": "Sent", "gateway_message_id": result["message_id"]}

            except GatewayError as exc:
                attempt += 1
                logger.warning(
                    "MessageRouter.send: Attempt %d/%d failed for channel=%s — %s",
                    attempt,
                    _MAX_ATTEMPTS,
                    channel,
                    exc,
                )
                if notification_record:
                    notification_record.retry_count = attempt
                    notification_record.save(update_fields=["retry_count"])

        # All attempts exhausted
        if notification_record:
            notification_record.delivery_status = Notification.DeliveryStatus.FAILED
            notification_record.save(update_fields=["delivery_status"])

        logger.error(
            "MessageRouter.send: Message delivery permanently failed after %d attempts "
            "(channel=%s, notification_id=%s)",
            _MAX_ATTEMPTS,
            channel,
            notification_record.pk if notification_record else "N/A",
        )
        return {"status": "Failed", "gateway_message_id": None}

    def send_acknowledgement(
        self,
        channel: str,
        recipient: str,
        language: str,
        reference_id: str,
        feedback_id: int,
    ) -> dict:
        """
        Send an acknowledgement message to a community member.

        Called by Subsystem 1's MessageNormaliser within the 10-second SLA window.
        Must be fast — no heavy work here.

        USSD acknowledgements are shown on-screen during the session; no outbound
        message is needed, so we return immediately for that channel.

        PRIVACY: ``recipient`` must be zeroed out by the caller after this returns.
        """
        # USSD: confirmation is on-screen, no outbound message needed
        if channel == "USSD":
            return {"status": "SCREEN_CONFIRMED"}

        from apps.notifications.services.template_library import TemplateLibrary

        # Render the acknowledgement template
        try:
            body = TemplateLibrary().get_and_render(
                "ACKNOWLEDGEMENT",
                language,
                {"reference_id": reference_id},
            )
        except TemplateNotFoundError:
            # Last-resort hardcoded fallback — log critical so ops team is alerted
            logger.critical(
                "MessageRouter.send_acknowledgement: ACKNOWLEDGEMENT template missing "
                "for language='%s' AND 'en'. Using hardcoded fallback. feedback_id=%d",
                language,
                feedback_id,
            )
            body = f"Message received. Ref: {reference_id}"

        # Create Notification record first (status=Queued)
        notification = Notification.objects.create(
            feedback_id=feedback_id,
            message_type=Notification.MessageType.ACKNOWLEDGEMENT,
            channel=channel if channel in ("SMS", "WhatsApp") else "SMS",
            content=body,
            delivery_language=language,
            delivery_status=Notification.DeliveryStatus.QUEUED,
        )

        result = self.send(
            channel=channel,
            recipient=recipient,
            body=body,
            notification_record=notification,
        )
        return result

    def send_alert_notification(self, user, alert) -> None:
        """
        Send email + SMS to an NGO staff member when a High-urgency alert fires.

        Called by Subsystem 2's AlertManager.

        PRIVACY: SMS recipient phone is read from user.alert_phone — it is passed
        directly to self.send() and never stored elsewhere in this method.
        """
        # --- Email ---
        try:
            subject = (
                f"[URGENT] RefuConnect Alert — "
                f"{alert.feedback.get_category_names() if hasattr(alert.feedback, 'get_category_names') else 'Feedback'}"
            )
            body = (
                f"A high-urgency feedback has been received.\n\n"
                f"Reference: {alert.feedback.get_reference_id() if hasattr(alert.feedback, 'get_reference_id') else f'#{alert.feedback_id}'}\n"
                f"Location: {alert.feedback.location or 'Unknown'}\n"
                f"Channel: {alert.feedback.channel}\n"
                f"Excerpt: {alert.description or ''}\n\n"
                f"View in dashboard: {settings.DASHBOARD_URL}/alerts/{alert.alert_id}/"
            )
            send_mail(
                subject,
                body,
                settings.DEFAULT_FROM_EMAIL,
                [user.email],
                fail_silently=False,
            )
            logger.info(
                "send_alert_notification: Email sent to %s for alert_id=%d",
                user.email,
                alert.alert_id,
            )
        except Exception as exc:
            logger.error(
                "send_alert_notification: Email failed for user_id=%s alert_id=%d: %s",
                user.pk,
                alert.alert_id,
                exc,
            )

        # --- SMS (only if user has an alert phone) ---
        if user.alert_phone:
            try:
                sms_body = (
                    f"URGENT RefuConnect Alert: {(alert.description or '')[:100]} "
                    f"View: {settings.DASHBOARD_URL}/alerts/{alert.alert_id}/"
                )
                self.send(
                    channel="SMS",
                    recipient=user.alert_phone,
                    body=sms_body[:160],
                )
            except Exception as exc:
                logger.error(
                    "send_alert_notification: SMS failed for user_id=%s: %s",
                    user.pk,
                    exc,
                )

    # ------------------------------------------------------------------ #
    # Private gateway integrations                                         #
    # ------------------------------------------------------------------ #

    def _send_via_africas_talking(self, recipient: str, body: str) -> dict:
        """
        Send an SMS via Africa's Talking.

        Africa's Talking requires the + prefix on phone numbers.
        Sandbox mode: set AFRICAS_TALKING_USERNAME=sandbox in .env.development.

        PRIVACY: ``recipient`` is a plaintext phone number — never log it.
        """
        try:
            import africastalking
        except ImportError as exc:
            raise GatewayError(
                "africastalking package is not installed. "
                "Run: pip install africastalking"
            ) from exc

        if not self._at_initialised:
            africastalking.initialize(
                username=settings.AFRICAS_TALKING_USERNAME,
                api_key=settings.AFRICAS_TALKING_API_KEY,
            )
            self._sms = africastalking.SMS
            self._at_initialised = True

        try:
            response = self._sms.send(
                message=body,
                recipients=[recipient],
                sender_id=settings.SMS_SHORT_CODE or None,
            )
        except Exception as exc:
            raise GatewayError(f"Africa's Talking SDK error: {exc}") from exc

        try:
            recipient_data = response["SMSMessageData"]["Recipients"][0]
        except (KeyError, IndexError) as exc:
            raise GatewayError(
                f"Unexpected Africa's Talking response shape: {response}"
            ) from exc

        if recipient_data.get("status") == "Success":
            return {"message_id": recipient_data["messageId"]}

        raise GatewayError(
            f"Africa's Talking rejected message: "
            f"{recipient_data.get('status')} — {recipient_data.get('statusCode', '')}"
        )

    def _send_via_whatsapp(
        self, recipient: str, body: str, media_url: str | None = None
    ) -> dict:
        """
        Send a message via the Meta WhatsApp Business API.

        WhatsApp requires phone numbers WITHOUT the + prefix.
        Strip it here before building the payload.

        PRIVACY: ``recipient`` is a plaintext phone number — never log it.
        """
        # Strip leading + — WhatsApp requires numbers without it
        recipient_clean = recipient.lstrip("+")

        url = (
            f"https://graph.facebook.com/v18.0/"
            f"{settings.WHATSAPP_PHONE_NUMBER_ID}/messages"
        )
        headers = {
            "Authorization": f"Bearer {settings.WHATSAPP_ACCESS_TOKEN}",
            "Content-Type": "application/json",
        }

        if media_url:
            payload = {
                "messaging_product": "whatsapp",
                "to": recipient_clean,
                "type": "image",
                "image": {"link": media_url, "caption": body},
            }
        else:
            payload = {
                "messaging_product": "whatsapp",
                "to": recipient_clean,
                "type": "text",
                "text": {"body": body, "preview_url": False},
            }

        try:
            with httpx.Client(timeout=8.0) as client:
                response = client.post(url, json=payload, headers=headers)
        except httpx.TimeoutException as exc:
            raise GatewayError("WhatsApp API timed out after 8 seconds.") from exc
        except Exception as exc:
            raise GatewayError(f"WhatsApp HTTP error: {exc}") from exc

        if response.status_code == 200:
            data = response.json()
            try:
                return {"message_id": data["messages"][0]["id"]}
            except (KeyError, IndexError) as exc:
                raise GatewayError(
                    f"Unexpected WhatsApp response shape: {response.text[:200]}"
                ) from exc

        raise GatewayError(
            f"WhatsApp API error {response.status_code}: {response.text[:200]}"
        )