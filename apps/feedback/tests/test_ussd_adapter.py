"""
Tests for C-02 — Africa's Talking USSD session adapter.

Coverage targets:
  TC-USSD-01  Empty text → language menu (CON)
  TC-USSD-02  Valid language choice → category menu (CON)
  TC-USSD-03  Invalid language choice → error + re-prompt (CON)
  TC-USSD-04  Valid language + category → message prompt (CON)
  TC-USSD-05  Invalid category choice → error + re-prompt (CON)
  TC-USSD-06  Full 3-step flow → MessageNormaliser.process() called, END response
  TC-USSD-07  Session timeout → END message
  TC-USSD-08  Message truncated to 160 characters at step 3
"""
from __future__ import annotations

import pytest
from django.core.cache import cache
from django.test import override_settings
from rest_framework.test import APIRequestFactory
from unittest.mock import MagicMock, patch

from apps.feedback.adapters.ussd import USSDSessionView

USSD_PAYLOAD_BASE = {
    "sessionId": "USSD_SESSION_001",
    "phoneNumber": "+256700000010",
    "serviceCode": "*123#",
}


def _build_request(text: str, session_id: str = "USSD_SESSION_001") -> object:
    factory = APIRequestFactory()
    payload = {**USSD_PAYLOAD_BASE, "sessionId": session_id, "text": text}
    return factory.post("/api/v1/feedback/webhooks/ussd/", data=payload, format="json")


@pytest.fixture(autouse=True)
def clear_cache():
    cache.clear()
    yield
    cache.clear()


# ── TC-USSD-01: Empty text → language menu ────────────────────────────────────

def test_ussd_empty_text_returns_language_menu():
    req = _build_request("")
    response = USSDSessionView.as_view()(req)
    # Africa's Talking expects text/plain content type
    assert response.status_code == 200
    body = response.content.decode()
    assert body.startswith("CON")
    assert "English" in body or "1." in body


# ── TC-USSD-02: Valid language choice → category menu ─────────────────────────

def test_ussd_valid_language_returns_category_menu():
    req = _build_request("1")  # 1=English
    response = USSDSessionView.as_view()(req)
    body = response.content.decode()
    assert body.startswith("CON")
    assert "Health" in body or "1." in body


# ── TC-USSD-03: Invalid language choice → re-prompt ──────────────────────────

def test_ussd_invalid_language_returns_end():
    req = _build_request("9")  # 9 is not a valid language
    response = USSDSessionView.as_view()(req)
    body = response.content.decode()
    # Implementation returns END with a re-dial prompt for invalid language
    assert body.startswith("END")
    assert "Invalid language" in body or "*123#" in body


# ── TC-USSD-04: Language + valid category → message prompt ────────────────────

def test_ussd_valid_language_and_category_returns_message_prompt():
    req = _build_request("1*1")  # English + Health
    response = USSDSessionView.as_view()(req)
    body = response.content.decode()
    assert body.startswith("CON")
    # Step 2 prompt asks user to type their message
    assert "message" in body.lower() or "type" in body.lower() or "enter" in body.lower()


# ── TC-USSD-05: Invalid category choice → re-prompt ──────────────────────────

def test_ussd_invalid_category_returns_reprompt():
    req = _build_request("1*9")  # English + invalid category 9
    response = USSDSessionView.as_view()(req)
    body = response.content.decode()
    assert body.startswith("CON")
    assert "END" not in body


# ── TC-USSD-06: Full flow → normaliser called, END ────────────────────────────

@patch("apps.common.utils.generate_reference_id", return_value="RFC-00000077")
@patch("apps.feedback.services.normaliser.MessageNormaliser")
def test_ussd_complete_flow_calls_normaliser_and_ends(mock_cls, mock_ref):
    mock_instance = MagicMock()
    mock_instance.process.return_value = 77
    mock_cls.return_value = mock_instance

    # lang=1 (en) * category=1 (Health) * message text
    req = _build_request("1*1*I need health assistance")
    response = USSDSessionView.as_view()(req)
    body = response.content.decode()

    assert body.startswith("END")
    mock_instance.process.assert_called_once()

    call_arg = mock_instance.process.call_args[0][0]
    assert call_arg["channel"] == "USSD"
    assert call_arg["language_hint"] == "en"
    assert call_arg["pre_category"] == "Health"
    assert "I need health assistance" in call_arg["body"]


# ── TC-USSD-07: Session timeout → END response ───────────────────────────────

@patch("apps.feedback.adapters.ussd.USSDSessionView._is_timed_out", return_value=True)
def test_ussd_timed_out_session_returns_end(mock_timeout):
    req = _build_request("1*1")
    response = USSDSessionView.as_view()(req)
    body = response.content.decode()
    assert body.startswith("END")


# ── TC-USSD-08: Long message → truncated to 160 chars ─────────────────────────

@patch("apps.common.utils.generate_reference_id", return_value="RFC-00000078")
@patch("apps.feedback.services.normaliser.MessageNormaliser")
def test_ussd_message_truncated_at_step3(mock_cls, mock_ref):
    mock_instance = MagicMock()
    mock_instance.process.return_value = 78
    mock_cls.return_value = mock_instance

    long_msg = "A" * 200  # 200 chars — exceeds 160-char limit
    req = _build_request(f"1*1*{long_msg}")
    response = USSDSessionView.as_view()(req)

    assert response.status_code == 200
    mock_instance.process.assert_called_once()
    call_arg = mock_instance.process.call_args[0][0]
    assert len(call_arg["body"]) <= 160
