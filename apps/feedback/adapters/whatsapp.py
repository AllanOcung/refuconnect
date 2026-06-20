"""
Meta WhatsApp Business API Connector — C-03.

Contains:
  WhatsAppAdapter      — outbound text messaging + signature helpers.
  WhatsAppWebhookView  — combined GET (challenge) + POST (events) endpoint.
  _download_meta_media — secure binary download from Meta Graph API.
  _save_media_file     — persist binary to MEDIA_ROOT with UUID filename.

Endpoint:
  GET  /api/v1/webhooks/whatsapp/ — Meta hub challenge verification
  POST /api/v1/webhooks/whatsapp/ — Inbound messages and delivery status events

Security:
  - POST requests verified with X-Hub-Signature-256 (HMAC-SHA256,
    key = settings.WHATSAPP_APP_SECRET).
  - Meta always expects HTTP 200; non-200 triggers aggressive retries.
  - Phone numbers (from, to) are NEVER logged — only feedback_id.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import os
import uuid
from datetime import datetime, timezone as stdlib_timezone
from typing import Optional

import requests
from django.conf import settings
from django.core.cache import cache
from django.http import HttpResponse
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

logger = logging.getLogger("refuconnect.feedback.whatsapp")

_GRAPH_API_VERSION = "v18.0"
_GRAPH_API_BASE = "https://graph.facebook.com"
_MAX_IMAGE_BYTES = 5 * 1024 * 1024        # 5 MB hard size cap
_ALLOWED_DOC_MIMETYPES = {"application/pdf"}
_MEDIA_SUBDIR = "feedback_media"


# ── Media helpers ─────────────────────────────────────────────────────────────

def _download_meta_media(media_id: str) -> Optional[bytes]:
    """
    Download binary content for a Meta media object.

    Two-step process:
      1. GET /{_GRAPH_API_VERSION}/{media_id}  → resolve opaque ID to a CDN URL.
      2. GET CDN URL (with Bearer token)       → download raw bytes.

    Parameters
    ----------
    media_id: Opaque Meta media ID from the webhook payload.

    Returns
    -------
    bytes | None   Raw content bytes, or None on any failure.
    """
    access_token = settings.WHATSAPP_ACCESS_TOKEN
    auth_headers = {"Authorization": f"Bearer {access_token}"}

    try:
        # Step 1: resolve media ID → CDN URL
        resolve_url = f"{_GRAPH_API_BASE}/{_GRAPH_API_VERSION}/{media_id}"
        resp = requests.get(resolve_url, headers=auth_headers, timeout=15)
        resp.raise_for_status()
        cdn_url = resp.json().get("url")
        if not cdn_url:
            logger.warning(
                "_download_meta_media: No url field in response for media_id=%s", media_id
            )
            return None

        # Step 2: download binary from CDN
        download_resp = requests.get(
            cdn_url, headers=auth_headers, timeout=30, stream=True
        )
        download_resp.raise_for_status()
        return download_resp.content

    except requests.RequestException:
        logger.exception(
            "_download_meta_media: Request exception for media_id=%s", media_id
        )
        return None


def _save_media_file(content: bytes, ext: str) -> tuple[str, int]:
    """
    Persist *content* to ``MEDIA_ROOT/feedback_media/{year}/{month:02d}/{uuid}.{ext}``.

    Creates intermediate directories if needed.

    Parameters
    ----------
    content: Raw bytes to write.
    ext:     File extension without leading dot (e.g. ``jpg``, ``ogg``, ``pdf``).

    Returns
    -------
    tuple[str, int]
        ``(relative_storage_path, file_size_bytes)``
    """
    now = datetime.now(stdlib_timezone.utc)
    rel_dir = os.path.join(_MEDIA_SUBDIR, str(now.year), f"{now.month:02d}")
    abs_dir = os.path.join(settings.MEDIA_ROOT, rel_dir)
    os.makedirs(abs_dir, exist_ok=True)

    filename = f"{uuid.uuid4().hex}.{ext}"
    abs_path = os.path.join(abs_dir, filename)
    with open(abs_path, "wb") as fp:
        fp.write(content)

    return os.path.join(rel_dir, filename), len(content)


# ── WhatsAppAdapter (outbound) ────────────────────────────────────────────────

class WhatsAppAdapter:
    """
    Wraps the Meta Graph API for outbound WhatsApp messaging.

    Responsibilities:
      - ``send_message()``: deliver a text message.
      - ``verify_webhook()``: validate a GET challenge from Meta.
      - ``verify_signature()``: validate a POST HMAC-SHA256 signature.
    """

    def __init__(self) -> None:
        self._access_token: str = settings.WHATSAPP_ACCESS_TOKEN
        self._phone_number_id: str = settings.WHATSAPP_PHONE_NUMBER_ID
        self._messages_url = (
            f"{_GRAPH_API_BASE}/{_GRAPH_API_VERSION}"
            f"/{self._phone_number_id}/messages"
        )
        self._headers = {
            "Authorization": f"Bearer {self._access_token}",
            "Content-Type": "application/json",
        }

    def send_message(self, to_phone: str, text: str) -> bool:
        """
        Send a plain-text WhatsApp message.

        Parameters
        ----------
        to_phone: Recipient in E.164 format (leading ``+`` stripped automatically).
        text:     Message body (max 4096 chars; trimmed silently).

        Returns
        -------
        bool  True on success.

        Security: ``to_phone`` is NEVER included in log output.
        """
        to_phone = to_phone.lstrip("+")
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to_phone,
            "type": "text",
            "text": {"preview_url": False, "body": text[:4096]},
        }
        try:
            resp = requests.post(
                self._messages_url,
                json=payload,
                headers=self._headers,
                timeout=10,
            )
            resp.raise_for_status()
            response_data = resp.json()
            success = bool(response_data.get("messages"))
            if not success:
                logger.warning(
                    "WhatsAppAdapter.send_message: unexpected response=%s", response_data
                )
            return success
        except requests.HTTPError as exc:
            logger.error(
                "WhatsAppAdapter.send_message: HTTP %s — %s",
                exc.response.status_code,
                exc.response.text,
            )
            return False
        except requests.RequestException:
            # SECURITY: do not log to_phone
            logger.exception(
                "WhatsAppAdapter.send_message: request exception for [phone redacted]"
            )
            return False

    @staticmethod
    def verify_webhook(mode: str, token: str, challenge: str) -> Optional[str]:
        """
        Validate a Meta hub.challenge verification request.

        Returns the ``challenge`` string when the mode is ``subscribe`` and the
        token matches ``settings.WHATSAPP_VERIFY_TOKEN``; None otherwise.
        """
        verify_token = getattr(settings, "WHATSAPP_VERIFY_TOKEN", "")
        if mode == "subscribe" and token == verify_token:
            return challenge
        return None

    @staticmethod
    def verify_signature(payload_bytes: bytes, signature_header: str) -> bool:
        """
        Validate the ``X-Hub-Signature-256`` header on inbound POST events.

        Uses ``settings.WHATSAPP_APP_SECRET`` as the HMAC key.
        Constant-time comparison prevents timing attacks.

        Parameters
        ----------
        payload_bytes:    Raw HTTP request body.
        signature_header: Value of ``X-Hub-Signature-256`` (``sha256=<hex>``).
        """
        if not signature_header.startswith("sha256="):
            return False
        app_secret = getattr(settings, "WHATSAPP_APP_SECRET", "")
        if not app_secret:
            logger.warning(
                "WhatsAppAdapter.verify_signature: WHATSAPP_APP_SECRET not configured"
            )
            return False
        expected = hmac.new(
            app_secret.encode("utf-8"), payload_bytes, hashlib.sha256
        ).hexdigest()
        provided = signature_header[len("sha256="):]
        return hmac.compare_digest(expected, provided)


# ── WhatsAppWebhookView ───────────────────────────────────────────────────────

class WhatsAppWebhookView(APIView):
    """
    Combined WhatsApp webhook view.

    GET  /api/v1/webhooks/whatsapp/ — Meta hub challenge verification.
    POST /api/v1/webhooks/whatsapp/ — Inbound messages + delivery status events.

    Meta retries aggressively on non-200 responses; always return 200 for POST.
    """

    permission_classes = [AllowAny]
    throttle_classes = []

    # ── GET: challenge verification ───────────────────────────────────────────

    def get(self, request: Request) -> HttpResponse:
        """
        Respond to Meta's webhook subscription verification challenge.

        Query params: hub.mode, hub.verify_token, hub.challenge.
        Returns hub.challenge as plain text on success, HTTP 403 otherwise.
        """
        mode = request.query_params.get("hub.mode", "")
        token = request.query_params.get("hub.verify_token", "")
        challenge = request.query_params.get("hub.challenge", "")

        result = WhatsAppAdapter.verify_webhook(mode, token, challenge)
        if result is None:
            logger.warning(
                "WhatsAppWebhookView.get: Verification failed — mode=%s", mode
            )
            return HttpResponse(
                "Forbidden", status=403, content_type="text/plain"
            )
        logger.info("WhatsAppWebhookView.get: Webhook verified successfully")
        return HttpResponse(result, content_type="text/plain")

    # ── POST: inbound events ──────────────────────────────────────────────────

    def post(self, request: Request) -> Response:
        """
        Process inbound WhatsApp events (messages or delivery status updates).

        Validates X-Hub-Signature-256, then delegates to _process_payload().
        Returns HTTP 200 regardless of downstream processing success.
        """
        sig_header = request.headers.get("X-Hub-Signature-256", "")
        if not WhatsAppAdapter.verify_signature(request.body, sig_header):
            logger.warning(
                "WhatsAppWebhookView.post: Invalid X-Hub-Signature-256 — rejecting"
            )
            return Response(
                {"detail": "Invalid signature"}, status=status.HTTP_403_FORBIDDEN
            )

        try:
            self._process_payload(request.data)
        except Exception:
            # Still return 200 — Meta must not be left without an ACK
            logger.exception(
                "WhatsAppWebhookView.post: Unhandled error — returning 200 anyway"
            )

        return Response({"detail": "ok"}, status=status.HTTP_200_OK)

    # ── Payload dispatcher ────────────────────────────────────────────────────

    def _process_payload(self, data: dict) -> None:
        """
        Iterate all entry/change/value nodes and dispatch messages or statuses.

        Meta payload structure::

            data
            └─ entry[]
               └─ changes[]
                  └─ value
                     ├─ messages[]   ← inbound messages
                     └─ statuses[]   ← delivery receipts
        """
        try:
            for entry in data.get("entry", []):
                for change in entry.get("changes", []):
                    value = change.get("value", {})
                    for stat in value.get("statuses", []):
                        self._handle_status_update(stat)
                    for msg in value.get("messages", []):
                        self._handle_message(msg)
        except (KeyError, IndexError, TypeError):
            logger.exception("WhatsAppWebhookView: Failed to parse Meta payload structure")

    def _handle_status_update(self, status_update: dict) -> None:
        """
        Forward delivery status to DeliveryTracker.

        SECURITY: ``recipient_id`` in the status payload is a phone number;
        it is NOT extracted or logged here.
        """
        try:
            from apps.notifications.services.delivery_tracker import handle_webhook_update
            wamid = status_update.get("id", "")
            raw_status = status_update.get("status", "")
            logger.debug(
                "WhatsAppWebhookView: Status update wamid=%s status=%s", wamid, raw_status
            )
            # Map WhatsApp status to our internal vocabulary
            handle_webhook_update({"whatsapp_message_id": wamid, "status": raw_status})
        except Exception:
            logger.exception(
                "WhatsAppWebhookView: Error forwarding status update to DeliveryTracker"
            )

    def _handle_message(self, msg: dict) -> None:
        """
        Extract content, download media if needed, and dispatch to MessageNormaliser.

        Supported message types: text, image, audio, document.
        Unsupported types are silently skipped (logged at DEBUG).

        SECURITY: ``msg['from']`` is the sender's phone — it is passed
        directly to MessageNormaliser which anonymises it; never logged here.
        """
        msg_type: str = msg.get("type", "")
        sender: str = msg.get("from", "")
        received_at = datetime.now(stdlib_timezone.utc)
        body: str = ""
        media_info: Optional[dict] = None

        if msg_type == "text":
            body = msg.get("text", {}).get("body", "")

        elif msg_type == "image":
            image = msg.get("image", {})
            media_id = image.get("id", "")
            body = image.get("caption", "") or ""
            media_info = self._fetch_and_store(media_id, "image", "jpg")

        elif msg_type == "audio":
            audio = msg.get("audio", {})
            media_id = audio.get("id", "")
            body = "[Voice note received — transcription pending]"
            media_info = self._fetch_and_store(media_id, "voice_note", "ogg")

        elif msg_type == "document":
            doc = msg.get("document", {})
            mime_type = doc.get("mime_type", "")
            if mime_type in _ALLOWED_DOC_MIMETYPES:
                media_id = doc.get("id", "")
                body = "[Document received — text extraction pending]"
                media_info = self._fetch_and_store(media_id, "document", "pdf")
            else:
                logger.debug(
                    "WhatsAppWebhookView: Skipping document mime_type=%s (not PDF)", mime_type
                )
                return

        elif msg_type == "location":
            # User shared their GPS location — capture as "lat,lng" string.
            # Only processed when a location_pending key exists; otherwise ignored.
            lat = msg.get("location", {}).get("latitude")
            lng = msg.get("location", {}).get("longitude")
            if lat is None or lng is None:
                return
            body = f"{lat:.5f},{lng:.5f}"

        else:
            logger.debug(
                "WhatsAppWebhookView: Skipping unsupported message type=%s", msg_type
            )
            return

        # Consent routing: YES/NO text replies must not create Feedback records
        if msg_type == "text":
            normalised_body = body.strip().upper()
            if normalised_body in ("YES", "Y"):
                try:
                    from apps.notifications.services.consent_manager import ConsentManager
                    ConsentManager().handle_opt_in(phone=sender, channel="WhatsApp")
                except Exception:
                    logger.exception(
                        "WhatsAppWebhookView: handle_opt_in failed for sender=[redacted]"
                    )
                # Prompt for incident location if the user has feedback awaiting one.
                self._maybe_send_location_prompt(sender)
                return
            if normalised_body in ("NO", "N", "STOP"):
                try:
                    from apps.notifications.services.consent_manager import ConsentManager
                    ConsentManager().handle_opt_out(phone=sender, channel="WhatsApp")
                except Exception:
                    logger.exception(
                        "WhatsAppWebhookView: handle_opt_out failed for sender=[redacted]"
                    )
                # Location is captured for the feedback regardless of follow-up
                # consent, so still prompt for it when one is pending.
                self._maybe_send_location_prompt(sender)
                return

        # Location reply check — when a pending-location key exists:
        #   • a shared GPS pin (msg_type=="location") is unambiguous → always consumed;
        #   • a text reply is consumed only if it is a VALID menu selection (digit or
        #     exact settlement name).  Other text falls through to new-feedback
        #     creation, so a genuine second complaint is never swallowed.
        if msg_type in ("text", "location") and body.strip():
            from apps.common.utils import hash_phone_number
            from apps.feedback.location_options import resolve_location_reply
            _loc_salt = getattr(settings, "PHONE_HASH_SALT", settings.SECRET_KEY)
            _phone_hash = hash_phone_number(sender, _loc_salt)
            _pending_id = cache.get(f"location_pending:{_phone_hash}")
            if _pending_id:
                if msg_type == "location":
                    self._handle_location_reply(
                        feedback_id=_pending_id,
                        location=body.strip()[:100],
                        phone_hash=_phone_hash,
                        sender=sender,
                    )
                    return
                matched, location_value = resolve_location_reply(body)
                if matched:
                    self._handle_location_reply(
                        feedback_id=_pending_id,
                        location=location_value,
                        phone_hash=_phone_hash,
                        sender=sender,
                    )
                    return
                # Not a location selection — fall through to feedback creation.

        # GPS location shares with no pending request are silently dropped —
        # they carry no feedback text and should not create a Feedback record.
        if msg_type == "location":
            logger.debug(
                "WhatsAppWebhookView: Location message with no pending request — skipping"
            )
            return

        raw_message: dict = {
            "channel": "WhatsApp",
            "sender": sender,
            "body": body,
            "received_at": received_at,
        }
        if media_info:
            raw_message["media_info"] = media_info

        from apps.feedback.services.normaliser import MessageNormaliser
        feedback_id = MessageNormaliser().process(raw_message)
        # SECURITY: log feedback_id only, never the sender phone number
        logger.debug("WhatsAppWebhookView: Created feedback_id=%s", feedback_id)

    @staticmethod
    def _maybe_send_location_prompt(sender: str) -> None:
        """
        Send the localized location menu if the sender has feedback awaiting a
        location (a ``location_pending`` Redis key). The menu language follows the
        pending feedback's detected language so prompts stay consistent with how
        the feedback was submitted. Best-effort: failures are logged, not raised.
        """
        try:
            from apps.common.utils import hash_phone_number
            from apps.feedback.location_options import build_location_menu
            from apps.feedback.models import Feedback

            _loc_salt = getattr(settings, "PHONE_HASH_SALT", settings.SECRET_KEY)
            _phone_hash = hash_phone_number(sender, _loc_salt)
            _pending_id = cache.get(f"location_pending:{_phone_hash}")
            if not _pending_id:
                return
            lang = (
                Feedback.objects.filter(feedback_id=_pending_id)
                .values_list("language", flat=True)
                .first()
            ) or "en"
            WhatsAppAdapter().send_message(sender, build_location_menu(lang))
        except Exception:
            logger.warning(
                "WhatsAppWebhookView: location prompt failed for sender=[redacted]"
            )

    @staticmethod
    def _handle_location_reply(
        feedback_id: int,
        location: str | None,
        phone_hash: str,
        sender: str,
    ) -> None:
        """
        Update ``Feedback.location`` with the resolved selection and clear the
        pending-location Redis key.

        Parameters
        ----------
        feedback_id: PK of the Feedback awaiting a location.
        location:    Canonical settlement name, a "lat,lng" string from a GPS pin,
                     or None for "Other district" (left null, parity with USSD).
        phone_hash:  Salted SHA-256 hash of the sender's phone.
        sender:      Raw E.164 phone — used for confirmation ack, then zeroed.
                     NEVER logged.
        """
        from apps.feedback.models import Feedback

        Feedback.objects.filter(feedback_id=feedback_id).update(location=location)
        cache.delete(f"location_pending:{phone_hash}")
        logger.debug(
            "WhatsAppWebhookView: Location recorded for feedback_id=%d value=%r",
            feedback_id,
            location,
        )

        lang = (
            Feedback.objects.filter(feedback_id=feedback_id)
            .values_list("language", flat=True)
            .first()
        )
        ack = (
            "Mahali pamepokelewa. Asante."
            if lang == "sw"
            else "Location received. Thank you."
        )
        try:
            WhatsAppAdapter().send_message(sender, ack)
        except Exception:
            logger.warning(
                "WhatsAppWebhookView: Location confirmation ack failed for feedback_id=%d",
                feedback_id,
            )
        finally:
            sender = None  # Privacy wipe  # noqa: F841

    @staticmethod
    def _fetch_and_store(
        media_id: str,
        media_type_str: str,
        ext: str,
    ) -> Optional[dict]:
        """
        Download a Meta media object and persist it to disk.

        Parameters
        ----------
        media_id:       Opaque Meta media ID from the webhook payload.
        media_type_str: FeedbackMedia.MediaType value (image/voice_note/document).
        ext:            File extension for storage (jpg / ogg / pdf).

        Returns
        -------
        dict | None
            ``{'media_type': …, 'storage_path': …, 'file_size_bytes': …}``
            ready for inclusion in ``raw_message['media_info']``, or None on error.
        """
        if not media_id:
            return None

        content = _download_meta_media(media_id)
        if content is None:
            return None

        # Enforce image size limit
        if media_type_str == "image" and len(content) > _MAX_IMAGE_BYTES:
            logger.warning(
                "WhatsAppWebhookView: Image media_id=%s exceeds 5MB (size=%d bytes)",
                media_id,
                len(content),
            )
            # Store with a sentinel extension so NLP pipeline can flag it
            ext = f"oversized.{ext}"

        storage_path, file_size = _save_media_file(content, ext)
        return {
            "media_type": media_type_str,
            "storage_path": storage_path,
            "file_size_bytes": file_size,
        }


# ── Backward-compatible parse helper (kept for existing tests) ────────────────

# The old parse_incoming static method is preserved on WhatsAppAdapter above.
# WhatsAppVerificationView is an alias exposed for explicit GET-only registration.
WhatsAppVerificationView = WhatsAppWebhookView
