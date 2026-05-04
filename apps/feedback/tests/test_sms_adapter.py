"""
Tests for C-01 — Africa's Talking SMS adapter.

Coverage targets:
  TC-SMS-01  Missing X-AT-Signature header → 401
  TC-SMS-02  Invalid HMAC signature → 401
  TC-SMS-03  Missing required field ('text') → 400
  TC-SMS-04  Valid request → MessageNormaliser.process() called, 200 returned
  TC-SMS-05  Idempotency: second identical message_id → normaliser called once only
  TC-SMS-06  Multi-part SMS first part → stored in Redis, normaliser NOT called
  TC-SMS-07  _verify_at_signature correct HMAC → True
  TC-SMS-08  _verify_at_signature wrong HMAC → False
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

from apps.feedback.adapters.sms import SMSWebhookView, _verify_at_signature

AT_API_KEY = "test-at-api-key-sms"

VALID_PAYLOAD = {
    "from": "+256700000001",
    "text": "Hello from SMS",
    "to": "20121",
    "id": "ATXid_abc123",
    "date": "2025-01-15 09:00:00",
}


def _make_sig(body: bytes, key: str = AT_API_KEY) -> str:
    return hmac.new(key.encode(), body, hashlib.sha256).hexdigest()


def _build_request(payload: dict, sig: str | None = None) -> object:
    factory = APIRequestFactory()
    body_bytes = json.dumps(payload).encode()
    req = factory.post(
        "/api/v1/feedback/webhooks/sms/",
        data=body_bytes,
        content_type="application/json",
    )
    if sig is None:
        # Sign the actual body that the view will see
        sig = _make_sig(req.body)
    req.META["HTTP_X_AT_SIGNATURE"] = sig
    return req


@pytest.fixture(autouse=True)
def clear_cache():
    cache.clear()
    yield
    cache.clear()


# ── TC-SMS-01: Missing signature → 401 ───────────────────────────────────────

@override_settings(AT_API_KEY=AT_API_KEY, AFRICAS_TALKING_API_KEY=AT_API_KEY)
def test_sms_missing_signature_returns_401():
    factory = APIRequestFactory()
    req = factory.post("/api/v1/feedback/webhooks/sms/", data=VALID_PAYLOAD, format="json")
    # No HTTP_X_AT_SIGNATURE header
    response = SMSWebhookView.as_view()(req)
    assert response.status_code == 401


# ── TC-SMS-02: Bad HMAC → 401 ─────────────────────────────────────────────────

@override_settings(AT_API_KEY=AT_API_KEY, AFRICAS_TALKING_API_KEY=AT_API_KEY)
def test_sms_bad_signature_returns_401():
    req = _build_request(VALID_PAYLOAD, sig="badbadbadbad")
    response = SMSWebhookView.as_view()(req)
    assert response.status_code == 401


# ── TC-SMS-03: Missing 'text' field → 400 ─────────────────────────────────────

@override_settings(AT_API_KEY=AT_API_KEY, AFRICAS_TALKING_API_KEY=AT_API_KEY, AT_SKIP_SMS_SIGNATURE=True)
def test_sms_missing_text_field_returns_400():
    bad_payload = {"from": "+256700000001", "to": "20121", "id": "ATXid_x"}
    factory = APIRequestFactory()
    req = factory.post("/api/v1/feedback/webhooks/sms/", data=bad_payload, format="json")
    response = SMSWebhookView.as_view()(req)
    assert response.status_code == 400


# ── TC-SMS-04: Valid request → normaliser called, 200 ─────────────────────────

@override_settings(AT_API_KEY=AT_API_KEY, AFRICAS_TALKING_API_KEY=AT_API_KEY, PHONE_HASH_SALT="salt")
@patch("apps.feedback.services.normaliser.MessageNormaliser")
def test_sms_valid_request_calls_normaliser(mock_cls):
    mock_instance = MagicMock()
    mock_instance.process.return_value = 42
    mock_cls.return_value = mock_instance

    req = _build_request(VALID_PAYLOAD)
    response = SMSWebhookView.as_view()(req)

    assert response.status_code == 200
    mock_instance.process.assert_called_once()
    call_kwargs = mock_instance.process.call_args[0][0]
    assert call_kwargs["channel"] == "SMS"
    assert call_kwargs["body"] == VALID_PAYLOAD["text"]
    assert call_kwargs["sender"] == VALID_PAYLOAD["from"]


# ── TC-SMS-05: Idempotency guard ──────────────────────────────────────────────

@override_settings(AT_API_KEY=AT_API_KEY, AFRICAS_TALKING_API_KEY=AT_API_KEY, PHONE_HASH_SALT="salt")
@patch("apps.feedback.services.normaliser.MessageNormaliser")
def test_sms_idempotency_skips_second_call(mock_cls):
    mock_instance = MagicMock()
    mock_instance.process.return_value = 43
    mock_cls.return_value = mock_instance

    r1 = SMSWebhookView.as_view()(_build_request(VALID_PAYLOAD))
    r2 = SMSWebhookView.as_view()(_build_request(VALID_PAYLOAD))

    assert r1.status_code == 200
    assert r2.status_code == 200
    assert mock_instance.process.call_count == 1, "Normaliser must be called only once"


# ── TC-SMS-06: Multi-part first part → not forwarded to normaliser ────────────

@override_settings(AT_API_KEY=AT_API_KEY, AFRICAS_TALKING_API_KEY=AT_API_KEY, PHONE_HASH_SALT="salt")
@patch("apps.feedback.tasks.assemble_multipart_sms")
@patch("apps.feedback.services.normaliser.MessageNormaliser")
def test_sms_multipart_first_part_buffered(mock_cls, mock_task):
    mock_instance = MagicMock()
    mock_cls.return_value = mock_instance

    mp_payload = {
        "from": "+256700000002",
        "text": "Part one",
        "to": "20121",
        "id": "ATXid_mp_first",
        "linkId": "LINKXYZ",
        "partNumber": "1",
        "date": "2025-01-15 10:00:00",
    }
    req = _build_request(mp_payload)
    response = SMSWebhookView.as_view()(req)

    assert response.status_code == 200
    mock_instance.process.assert_not_called()


# ── TC-SMS-07/08: _verify_at_signature unit tests ─────────────────────────────

@override_settings(AT_API_KEY=AT_API_KEY, AFRICAS_TALKING_API_KEY=AT_API_KEY)
def test_verify_at_signature_correct_key():
    body = b"key=value&other=thing"
    sig = hmac.new(AT_API_KEY.encode(), body, hashlib.sha256).hexdigest()
    assert _verify_at_signature(body, sig) is True


@override_settings(AT_API_KEY=AT_API_KEY, AFRICAS_TALKING_API_KEY=AT_API_KEY)
def test_verify_at_signature_wrong_key():
    body = b"key=value&other=thing"
    assert _verify_at_signature(body, "not-a-valid-signature") is False
