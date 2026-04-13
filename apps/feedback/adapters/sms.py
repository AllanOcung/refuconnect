"""
Africa's Talking SMS Gateway Adapter — C-01.

Contains:
  SMSAdapter       — outbound SMS dispatch via AT SDK
  SMSWebhookView   — inbound SMS webhook (POST /api/v1/webhooks/sms/)

Security:
  - HMAC-SHA256 signature verification using X-AT-Signature header
  - Idempotency guard via Redis (TTL=300 s)
  - Multi-part SMS assembly via Redis + Celery countdown task
  - Phone numbers are NEVER logged; only anonymous_user_id or feedback_id.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
from datetime import datetime, timezone as stdlib_timezone
from typing import Optional

import africastalking
from django.conf import settings
from django.core.cache import cache
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

logger = logging.getLogger("refuconnect.feedback.sms")

# ── Tunables ──────────────────────────────────────────────────────────────────
_IDEMPOTENCY_TTL: int = 300   # seconds
_MULTIPART_TTL: int = 300     # seconds to wait for remaining parts
_MAX_MULTIPART_PARTS: int = 3
_REQUIRED_FIELDS = frozenset({"from", "text", "to"})


# ── Signature verification ────────────────────────────────────────────────────

def _verify_at_signature(raw_body: bytes, header_sig: str) -> bool:
    """
    Verify an Africa's Talking X-AT-Signature HMAC-SHA256 header.

    The shared secret is ``settings.AFRICAS_TALKING_API_KEY`` (AT_API_KEY).
    Comparison is constant-time to prevent timing-based side-channel attacks.

    Parameters
    ----------
    raw_body:   Raw HTTP request body bytes.
    header_sig: Value of the ``X-AT-Signature`` header.
    """
    api_key: str = (
        getattr(settings, "AT_API_KEY", "")
        or settings.AFRICAS_TALKING_API_KEY
    )
    expected: str = hmac.new(
        api_key.encode("utf-8"), raw_body, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, header_sig.strip())


# ── SMSAdapter (outbound) ─────────────────────────────────────────────────────

class SMSAdapter:
    """
    Wraps the Africa's Talking SMS SDK for outbound dispatch.

    Responsibilities:
      - Initialise the AT SDK on construction.
      - ``send()``: deliver a single SMS.
      - ``parse_incoming()``: normalise webhook payload field names.
    """

    def __init__(self) -> None:
        africastalking.initialize(
            username=settings.AFRICAS_TALKING_USERNAME,
            api_key=settings.AFRICAS_TALKING_API_KEY,
        )
        self._sms = africastalking.SMS

    def send(self, phone_number: str, message: str) -> bool:
        """
        Send *message* to *phone_number* (E.164 format).

        Returns True on success, False on any failure.
        SECURITY: phone_number is never logged — only a redacted placeholder.

        Parameters
        ----------
        phone_number: Recipient in E.164 format, e.g. ``+256700123456``.
        message:      Text to deliver (split automatically for >160 chars).
        """
        try:
            response = self._sms.send(
                message,
                [phone_number],
                getattr(settings, "SMS_SHORT_CODE", None) or None,
            )
            recipients = (
                response.get("SMSMessageData", {}).get("Recipients", [])
            )
            if recipients and recipients[0].get("status") == "Success":
                return True
            # SECURITY: log status only, never the phone number
            logger.warning(
                "SMSAdapter.send: non-success status=%s",
                recipients[0].get("status") if recipients else "no-recipients",
            )
            return False
        except Exception:
            # SECURITY: do not log phone_number
            logger.exception("SMSAdapter.send: exception for [phone redacted]")
            return False

    @staticmethod
    def parse_incoming(data: dict) -> dict:
        """
        Parse an inbound Africa's Talking SMS webhook payload.

        Returns a normalised dict with snake_case keys regardless of the
        provider's camelCase payload structure.

        Parameters
        ----------
        data: Raw POST data dict from the AT webhook callback.
        """
        return {
            "phone": data.get("from", ""),
            "text": data.get("text", "").strip(),
            "short_code": data.get("to", ""),
            "link_id": data.get("linkId", ""),
            "message_id": data.get("id", ""),
            "date": data.get("date", ""),
        }


# ── SMSWebhookView (inbound) ──────────────────────────────────────────────────

class SMSWebhookView(APIView):
    """
    Receive inbound SMS messages from Africa's Talking.

    Endpoint: POST /api/v1/webhooks/sms/

    Processing pipeline:
      1. HMAC-SHA256 signature verification (X-AT-Signature header).
      2. Idempotency guard — skip already-processed gateway message IDs.
      3. Multi-part SMS assembly — collect parts sharing a linkId.
      4. Delegate to ``MessageNormaliser.process()`` for Feedback creation.

    Always returns HTTP 200 on unexpected exceptions to prevent AT retry storms.
    """

    permission_classes = [AllowAny]
    throttle_classes = []  # AT static IP ranges bypass app-level throttling

    def get(self, request: Request) -> Response:
        """URL reachability check used by Africa's Talking sandbox dashboard."""
        return Response({"detail": "ok"}, status=status.HTTP_200_OK)

    def post(self, request: Request) -> Response:
        """
        Handle one inbound Africa's Talking SMS callback.

        Returns HTTP 401 on invalid signature, HTTP 400 on missing fields,
        HTTP 200 in all other cases (including unexpected errors).
        """
        # Step 1: HMAC signature verification (skipped when AT_SKIP_SMS_SIGNATURE=True)
        skip_sig = getattr(settings, "AT_SKIP_SMS_SIGNATURE", False)
        if not skip_sig:
            header_sig = request.headers.get("X-AT-Signature", "")
            if not header_sig:
                logger.warning("SMSWebhookView: Missing X-AT-Signature header")
                return Response(
                    {"detail": "Missing signature"},
                    status=status.HTTP_401_UNAUTHORIZED,
                )
            if not _verify_at_signature(request.body, header_sig):
                logger.warning("SMSWebhookView: Invalid X-AT-Signature — rejecting")
                return Response(
                    {"detail": "Invalid signature"},
                    status=status.HTTP_401_UNAUTHORIZED,
                )
        else:
            logger.debug("SMSWebhookView: Signature check skipped (AT_SKIP_SMS_SIGNATURE=True)")

        # Field validation
        missing = _REQUIRED_FIELDS - set(request.data.keys())
        if missing:
            logger.warning("SMSWebhookView: Missing required fields %s", missing)
            return Response(
                {"detail": f"Missing required fields: {missing}"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            return self._handle(request.data)
        except Exception:
            # Always ACK the gateway on unexpected errors to prevent retry floods
            logger.exception(
                "SMSWebhookView: Unexpected error — returning 200 to suppress retries"
            )
            return Response({"detail": "ok"}, status=status.HTTP_200_OK)

    # ── Internal pipeline ─────────────────────────────────────────────────────

    def _handle(self, data: dict) -> Response:
        """Parse payload, check idempotency, assemble multi-part, then normalise."""
        parsed = SMSAdapter.parse_incoming(data)
        phone = parsed["phone"]
        link_id = parsed.get("link_id", "")
        received_at = datetime.now(stdlib_timezone.utc)

        # Stable gateway message ID; fall back to a content hash if absent
        message_id = parsed["message_id"] or hashlib.sha256(
            f"{phone}:{parsed['text']}:{parsed['date']}".encode()
        ).hexdigest()

        # Step 2: Idempotency — skip replayed webhooks
        idempotency_key = f"sms:idempotent:{message_id}"
        if cache.get(idempotency_key):
            # SECURITY: log message_id only, never the phone number
            logger.debug(
                "SMSWebhookView: Duplicate message_id=%s — skipping", message_id
            )
            return Response({"detail": "ok"}, status=status.HTTP_200_OK)
        cache.set(idempotency_key, True, _IDEMPOTENCY_TTL)

        # Step 3: Multi-part SMS assembly
        body = parsed["text"]
        if link_id:
            assembled = self._assemble_multipart(
                phone=phone,
                link_id=link_id,
                part_body=body,
                message_id=message_id,
                received_at=received_at,
            )
            if assembled is None:
                # Parts still outstanding — return 200 so AT doesn't retry
                return Response({"detail": "ok"}, status=status.HTTP_200_OK)
            body = assembled

        if not body.strip():
            logger.warning("SMSWebhookView: Empty body after assembly — skipping")
            return Response({"detail": "ok"}, status=status.HTTP_200_OK)

        # Step 4: Build raw_message and delegate to MessageNormaliser
        raw_message: dict = {
            "channel": "SMS",
            "sender": phone,
            "body": body,
            "received_at": received_at,
            "gateway_message_id": message_id,
        }
        from apps.feedback.services.normaliser import MessageNormaliser
        feedback_id = MessageNormaliser().process(raw_message)
        # SECURITY: log feedback_id only, never the phone number
        logger.debug("SMSWebhookView: Created feedback_id=%s", feedback_id)
        return Response({"detail": "ok"}, status=status.HTTP_200_OK)

    @staticmethod
    def _assemble_multipart(
        phone: str,
        link_id: str,
        part_body: str,
        message_id: str,
        received_at: datetime,
    ) -> Optional[str]:
        """
        Collect multi-part SMS fragments and return assembled text when ready.

        Parts are stored in Redis keyed by ``sms:mp:{hash(phone+linkId)}``.
        When ``_MAX_MULTIPART_PARTS`` parts are present they are assembled
        immediately and the Redis key is deleted. Otherwise a Celery countdown
        task finalises assembly after ``_MULTIPART_TTL`` seconds.

        Parameters
        ----------
        phone:       Sender's phone number.
        link_id:     Africa's Talking linkId that groups SMS parts.
        part_body:   Text body of this individual part.
        message_id:  Unique AT gateway message ID for this part.
        received_at: UTC datetime of this part's arrival.

        Returns
        -------
        str | None
            Assembled text when all parts are ready; None when still collecting.
        """
        from apps.common.encryption import encrypt_field

        # SECURITY: hash phone for the Redis key — never store the raw phone as a key
        assembly_key = "sms:mp:" + hashlib.sha256(
            f"{phone}:{link_id}".encode()
        ).hexdigest()

        state = cache.get(assembly_key)
        if state is None:
            state = {
                "parts": {},
                "encrypted_phone": encrypt_field(phone),
                "received_at": received_at.isoformat(),
            }

        # Preserve arrival order (Python dicts maintain insertion order)
        state["parts"][message_id] = part_body
        part_count = len(state["parts"])

        if part_count >= _MAX_MULTIPART_PARTS:
            # All expected parts received — assemble and clear Redis immediately
            cache.delete(assembly_key)
            return " ".join(state["parts"].values())

        # Persist updated state; schedule countdown task on the first part only
        cache.set(assembly_key, state, _MULTIPART_TTL)
        if part_count == 1:
            from apps.feedback.tasks import assemble_multipart_sms
            assemble_multipart_sms.apply_async(
                args=[assembly_key], countdown=_MULTIPART_TTL
            )

        return None  # still collecting parts
