"""
Tests for C-03 — Meta WhatsApp Business API adapter.

Coverage targets:
  TC-WA-01  GET hub challenge with valid verify_token → 200 + challenge echoed
  TC-WA-02  GET hub challenge with invalid token → 403
  TC-WA-03  POST without X-Hub-Signature-256 → 403
  TC-WA-04  POST with invalid HMAC signature → 403
  TC-WA-05  POST valid text message → normaliser called, 200
  TC-WA-06  POST status update → normaliser NOT called, 200
  TC-WA-07  POST unsupported message type → logged, 200, no normaliser
  TC-WA-08  POST audio message → normaliser called with placeholder body
"""
from __future__ import annotations

import hashlib
import hmac
import json

import pytest
from django.core.cache import cache
from django.test import override_settings
from rest_framework.test import APIRequestFactory
from unittest.mock import MagicMock, patch

from apps.feedback.adapters.whatsapp import WhatsAppWebhookView

WA_APP_SECRET = "test-whatsapp-app-secret"
WA_VERIFY_TOKEN = "test-verify-token"


def _make_wa_sig(body: bytes, secret: str = WA_APP_SECRET) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def _text_message_payload(phone: str = "+256700000020", txt: str = "Hello WA", wamid: str = "wamid.abc") -> dict:
    return {
        "object": "whatsapp_business_account",
        "entry": [{
            "id": "ENTRY_001",
            "changes": [{
                "field": "messages",
                "value": {
                    "messaging_product": "whatsapp",
                    "metadata": {"display_phone_number": "20121", "phone_number_id": "PHID01"},
                    "contacts": [{"profile": {"name": "Anon"}, "wa_id": phone.lstrip("+")}],
                    "messages": [{
                        "from": phone,
                        "id": wamid,
                        "timestamp": "1736000000",
                        "type": "text",
                        "text": {"body": txt},
                    }],
                },
            }],
        }],
    }


def _status_payload(wamid: str = "wamid.sts", raw_status: str = "delivered") -> dict:
    return {
        "object": "whatsapp_business_account",
        "entry": [{
            "id": "ENTRY_002",
            "changes": [{
                "field": "messages",
                "value": {
                    "messaging_product": "whatsapp",
                    "metadata": {"display_phone_number": "20121", "phone_number_id": "PHID01"},
                    "statuses": [{
                        "id": wamid,
                        "status": raw_status,
                        "timestamp": "1736000001",
                        "recipient_id": "256700000020",
                    }],
                },
            }],
        }],
    }


def _post_request(payload: dict) -> object:
    factory = APIRequestFactory()
    body_bytes = json.dumps(payload).encode()
    sig = _make_wa_sig(body_bytes)
    req = factory.post("/api/v1/feedback/webhooks/whatsapp/", data=payload, format="json")
    req.META["HTTP_X_HUB_SIGNATURE_256"] = sig
    return req


@pytest.fixture(autouse=True)
def clear_cache():
    cache.clear()
    yield
    cache.clear()


# ── TC-WA-01: GET verify challenge ────────────────────────────────────────────

@override_settings(WHATSAPP_VERIFY_TOKEN=WA_VERIFY_TOKEN, WHATSAPP_APP_SECRET=WA_APP_SECRET)
def test_wa_get_challenge_valid_token():
    factory = APIRequestFactory()
    req = factory.get(
        "/api/v1/feedback/webhooks/whatsapp/",
        {
            "hub.mode": "subscribe",
            "hub.verify_token": WA_VERIFY_TOKEN,
            "hub.challenge": "abc123challenge",
        },
    )
    response = WhatsAppWebhookView.as_view()(req)
    assert response.status_code == 200
    assert b"abc123challenge" in response.content


# ── TC-WA-02: GET verify wrong token → 403 ────────────────────────────────────

@override_settings(WHATSAPP_VERIFY_TOKEN=WA_VERIFY_TOKEN, WHATSAPP_APP_SECRET=WA_APP_SECRET)
def test_wa_get_challenge_wrong_token():
    factory = APIRequestFactory()
    req = factory.get(
        "/api/v1/feedback/webhooks/whatsapp/",
        {
            "hub.mode": "subscribe",
            "hub.verify_token": "wrong-token",
            "hub.challenge": "abc123challenge",
        },
    )
    response = WhatsAppWebhookView.as_view()(req)
    assert response.status_code == 403


# ── TC-WA-03: POST missing signature → 403 ────────────────────────────────────

@override_settings(WHATSAPP_APP_SECRET=WA_APP_SECRET)
def test_wa_post_missing_signature_returns_403():
    factory = APIRequestFactory()
    payload = _text_message_payload()
    req = factory.post("/api/v1/feedback/webhooks/whatsapp/", data=payload, format="json")
    # No X-Hub-Signature-256 header
    response = WhatsAppWebhookView.as_view()(req)
    assert response.status_code == 403


# ── TC-WA-04: POST bad signature → 403 ────────────────────────────────────────

@override_settings(WHATSAPP_APP_SECRET=WA_APP_SECRET)
def test_wa_post_bad_signature_returns_403():
    factory = APIRequestFactory()
    payload = _text_message_payload()
    req = factory.post("/api/v1/feedback/webhooks/whatsapp/", data=payload, format="json")
    req.META["HTTP_X_HUB_SIGNATURE_256"] = "sha256=notarealsig"
    response = WhatsAppWebhookView.as_view()(req)
    assert response.status_code == 403


# ── TC-WA-05: Valid text message → normaliser called ─────────────────────────

@override_settings(WHATSAPP_APP_SECRET=WA_APP_SECRET)
@patch("apps.feedback.services.normaliser.MessageNormaliser")
def test_wa_valid_text_calls_normaliser(mock_cls):
    mock_instance = MagicMock()
    mock_instance.process.return_value = 55
    mock_cls.return_value = mock_instance

    req = _post_request(_text_message_payload(txt="I need food"))
    response = WhatsAppWebhookView.as_view()(req)

    assert response.status_code == 200
    mock_instance.process.assert_called_once()
    call_arg = mock_instance.process.call_args[0][0]
    assert call_arg["channel"] == "WhatsApp"
    assert call_arg["body"] == "I need food"


# ── TC-WA-06: Status update → normaliser NOT called ──────────────────────────

@override_settings(WHATSAPP_APP_SECRET=WA_APP_SECRET)
@patch("apps.feedback.services.normaliser.MessageNormaliser")
def test_wa_status_update_does_not_call_normaliser(mock_cls):
    mock_instance = MagicMock()
    mock_cls.return_value = mock_instance

    req = _post_request(_status_payload())
    response = WhatsAppWebhookView.as_view()(req)

    assert response.status_code == 200
    mock_instance.process.assert_not_called()


# ── TC-WA-07: Unsupported message type → 200, no normaliser ──────────────────

@override_settings(WHATSAPP_APP_SECRET=WA_APP_SECRET)
@patch("apps.feedback.services.normaliser.MessageNormaliser")
def test_wa_unsupported_message_type_returns_200(mock_cls):
    mock_instance = MagicMock()
    mock_cls.return_value = mock_instance

    payload = _text_message_payload()
    # Replace type with unsupported
    payload["entry"][0]["changes"][0]["value"]["messages"][0]["type"] = "reaction"
    req = _post_request(payload)
    response = WhatsAppWebhookView.as_view()(req)

    assert response.status_code == 200
    mock_instance.process.assert_not_called()


# ── TC-WA-08: Audio message → normaliser with placeholder body ────────────────

@override_settings(WHATSAPP_APP_SECRET=WA_APP_SECRET)
@patch("apps.feedback.services.normaliser.MessageNormaliser")
@patch("apps.feedback.adapters.whatsapp._download_meta_media", return_value=b"fakeaudiobytes")
@patch("apps.feedback.adapters.whatsapp._save_media_file", return_value=("feedback_media/2025/01/uuid.ogg", 14))
def test_wa_audio_message_normaliser_gets_placeholder(mock_save, mock_dl, mock_cls):
    mock_instance = MagicMock()
    mock_instance.process.return_value = 56
    mock_cls.return_value = mock_instance

    payload = _text_message_payload()
    msg = payload["entry"][0]["changes"][0]["value"]["messages"][0]
    msg["type"] = "audio"
    msg.pop("text", None)
    msg["audio"] = {"id": "AUDIO_MEDIA_ID_001", "mime_type": "audio/ogg; codecs=opus"}

    req = _post_request(payload)
    response = WhatsAppWebhookView.as_view()(req)

    assert response.status_code == 200
    mock_instance.process.assert_called_once()
    call_arg = mock_instance.process.call_args[0][0]
    assert "Voice note" in call_arg["body"] or "transcription" in call_arg["body"].lower()
