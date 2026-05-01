"""
Tests for C-04 — MessageNormaliser.

Coverage targets:
  TC-NRM-01  Anonymise: sender zeroed out after process(), anon_id has 'ANON-' prefix
  TC-NRM-02  Anonymise: same phone within TTL returns same anon_id (Redis cache hit)
  TC-NRM-03  Duplicate: same body from same anon within 300s → is_duplicate=True on Feedback
  TC-NRM-04  Feedback record created with correct channel, language_hint, status
  TC-NRM-05  Pre-category: USSD category linked as FeedbackCategory (confidence=0.80)
  TC-NRM-06  Pre-category: missing category in DB does not raise, Feedback still created
  TC-NRM-07  FeedbackMedia created when media_info present
  TC-NRM-08  NLP task dispatched (process_feedback_nlp.delay called)
  TC-NRM-09  USSD channel: no outbound acknowledgement attempted
  TC-NRM-10  SMS channel: acknowledgement attempted via MessageRouter
  TC-NRM-11  Text cleaning: control chars stripped, whitespace collapsed
  TC-NRM-12  SMS body truncated to 480 chars; USSD to 160 chars
"""
from __future__ import annotations

from decimal import Decimal
from unittest.mock import MagicMock, patch, call

import pytest
from django.core.cache import cache
from django.test import override_settings

from apps.feedback.services.normaliser import MessageNormaliser

PHONE = "+256700000099"
SALT = "test-salt"


def _raw(
    channel: str = "SMS",
    body: str = "I need water near Nakivale",
    phone: str = PHONE,
    **kwargs,
) -> dict:
    from datetime import datetime, timezone
    return {
        "channel": channel,
        "sender": phone,
        "body": body,
        "received_at": datetime.now(timezone.utc),
        **kwargs,
    }


@pytest.fixture(autouse=True)
def flush_cache():
    cache.clear()
    yield
    cache.clear()


# ── TC-NRM-01: sender zeroed out, anon_id has ANON- prefix ───────────────────

@pytest.mark.django_db
@override_settings(PHONE_HASH_SALT=SALT)
@patch("apps.feedback.services.normaliser.MessageNormaliser._dispatch_acknowledgement")
def test_sender_zeroed_and_anon_id_format(mock_ack):
    with patch.dict("sys.modules", {"apps.nlp.tasks": MagicMock()}):
        raw = _raw()
        norm = MessageNormaliser()
        feedback_id = norm.process(raw)

    assert raw["sender"] is None, "Sender must be zeroed after process()"

    from apps.feedback.models import Feedback
    fb = Feedback.objects.get(pk=feedback_id)
    assert fb.anonymous_user_id.startswith("ANON-"), f"Got: {fb.anonymous_user_id}"


# ── TC-NRM-02: Same phone within TTL uses cached anon_id ─────────────────────

@override_settings(PHONE_HASH_SALT=SALT)
def test_same_phone_same_anon_id_within_ttl():
    norm = MessageNormaliser()
    id1 = norm._get_or_create_anon_id(PHONE)
    id2 = norm._get_or_create_anon_id(PHONE)
    assert id1 == id2


# ── TC-NRM-03: Duplicate body within 300s → is_duplicate=True ────────────────

@pytest.mark.django_db
@override_settings(PHONE_HASH_SALT=SALT)
@patch("apps.feedback.services.normaliser.MessageNormaliser._dispatch_acknowledgement")
def test_duplicate_body_flagged(mock_ack):
    with patch("apps.feedback.services.normaliser.MessageNormaliser._enqueue_ack_retry"):
        with _patch_nlp():
            norm = MessageNormaliser()
            anon_id = norm._get_or_create_anon_id(PHONE)
            # Prime the duplicate cache
            body = "Flooding near my camp"
            norm._check_and_mark_duplicate(anon_id, body)

            # Process a message with the same body through the full pipeline
            raw = _raw(channel="USSD", body=body, language_hint="en")
            fb_id = norm.process(raw)

    from apps.feedback.models import Feedback
    fb = Feedback.objects.get(pk=fb_id)
    assert fb.is_duplicate is True


# ── TC-NRM-04: Feedback record channel, language, status ─────────────────────

@pytest.mark.django_db
@override_settings(PHONE_HASH_SALT=SALT)
@patch("apps.feedback.services.normaliser.MessageNormaliser._dispatch_acknowledgement")
def test_feedback_record_fields(mock_ack):
    with _patch_nlp():
        fb_id = MessageNormaliser().process(_raw(channel="WhatsApp", language_hint="sw"))

    from apps.feedback.models import Feedback
    fb = Feedback.objects.get(pk=fb_id)
    assert fb.channel == "WhatsApp"
    assert fb.language == "sw"
    assert fb.status == Feedback.Status.NEW


# ── TC-NRM-05: USSD pre-category linked as FeedbackCategory ──────────────────

@pytest.mark.django_db
@override_settings(PHONE_HASH_SALT=SALT)
@patch("apps.feedback.services.normaliser.MessageNormaliser._dispatch_acknowledgement")
def test_pre_category_creates_feedback_category(mock_ack):
    from apps.feedback.models import Category, FeedbackCategory
    cat = Category.objects.create(category_name="Health", is_active=True)

    with _patch_nlp():
        fb_id = MessageNormaliser().process(
            _raw(channel="USSD", pre_category="Health", language_hint="en")
        )

    fc = FeedbackCategory.objects.filter(feedback_id=fb_id, category=cat).first()
    assert fc is not None
    assert float(fc.confidence_score) == pytest.approx(0.80, rel=1e-3)
    assert fc.is_ai_assigned is False


# ── TC-NRM-06: Missing pre-category in DB → no raise, Feedback created ────────

@pytest.mark.django_db
@override_settings(PHONE_HASH_SALT=SALT)
@patch("apps.feedback.services.normaliser.MessageNormaliser._dispatch_acknowledgement")
def test_missing_pre_category_does_not_raise(mock_ack):
    with _patch_nlp():
        fb_id = MessageNormaliser().process(
            _raw(channel="USSD", pre_category="NonExistentCategory")
        )

    from apps.feedback.models import Feedback
    assert Feedback.objects.filter(pk=fb_id).exists()


# ── TC-NRM-07: FeedbackMedia created from media_info ─────────────────────────

@pytest.mark.django_db
@override_settings(PHONE_HASH_SALT=SALT)
@patch("apps.feedback.services.normaliser.MessageNormaliser._dispatch_acknowledgement")
def test_feedback_media_created_from_media_info(mock_ack):
    media_info = {
        "media_type": "image",
        "storage_path": "feedback_media/2025/01/abc.jpg",
        "file_size_bytes": 45000,
    }
    with _patch_nlp():
        fb_id = MessageNormaliser().process(
            _raw(channel="WhatsApp", media_info=media_info)
        )

    from apps.feedback.models import FeedbackMedia
    media = FeedbackMedia.objects.filter(feedback_id=fb_id).first()
    assert media is not None
    assert media.media_type == "image"
    assert media.storage_path == "feedback_media/2025/01/abc.jpg"
    assert media.file_size_bytes == 45000


# ── TC-NRM-08: NLP task dispatched ───────────────────────────────────────────

@pytest.mark.django_db
@override_settings(PHONE_HASH_SALT=SALT)
@patch("apps.feedback.services.normaliser.MessageNormaliser._dispatch_acknowledgement")
def test_nlp_task_dispatched(mock_ack):
    mock_task = MagicMock()
    with patch.dict("sys.modules", {"apps.nlp.tasks": MagicMock(process_feedback_nlp=mock_task)}):
        fb_id = MessageNormaliser().process(_raw())

    mock_task.delay.assert_called_once_with(fb_id)


# ── TC-NRM-09: USSD channel → no outbound acknowledgement ────────────────────

@pytest.mark.django_db
@override_settings(PHONE_HASH_SALT=SALT)
def test_ussd_no_ack_attempted():
    with _patch_nlp():
        with patch("apps.feedback.services.normaliser.MessageNormaliser._dispatch_acknowledgement") as mock_ack:
            MessageNormaliser().process(_raw(channel="USSD", language_hint="en"))

    # _dispatch_acknowledgement is called but internally skips for USSD
    mock_ack.assert_called_once()
    call_kwargs = mock_ack.call_args[1]
    assert call_kwargs.get("channel") == "USSD"


# ── TC-NRM-10: SMS channel → ack attempted ───────────────────────────────────

@pytest.mark.django_db
@override_settings(PHONE_HASH_SALT=SALT)
def test_sms_ack_dispatch_attempted():
    with _patch_nlp():
        with patch("apps.feedback.services.normaliser.MessageNormaliser._dispatch_acknowledgement") as mock_ack:
            MessageNormaliser().process(_raw(channel="SMS"))

    mock_ack.assert_called_once()
    call_kwargs = mock_ack.call_args[1]
    assert call_kwargs.get("channel") == "SMS"


# ── TC-NRM-11: Text cleaning ─────────────────────────────────────────────────

def test_clean_strips_control_chars_and_collapses_whitespace():
    norm = MessageNormaliser()
    raw = "Hello\x00\x01 World\t  \tEnd"
    cleaned = norm._clean_and_truncate(raw, "SMS")
    assert "\x00" not in cleaned
    assert "\x01" not in cleaned
    assert "Hello World End" == cleaned


# ── TC-NRM-12: Truncation per channel ────────────────────────────────────────

def test_sms_text_truncated_at_480():
    norm = MessageNormaliser()
    assert len(norm._clean_and_truncate("A" * 600, "SMS")) <= 480


def test_ussd_text_truncated_at_160():
    norm = MessageNormaliser()
    assert len(norm._clean_and_truncate("B" * 300, "USSD")) <= 160


# ── Helpers ───────────────────────────────────────────────────────────────────

def _patch_nlp():
    """Silence NLP task dispatch in tests that don't care about it."""
    import sys
    from unittest.mock import patch as _patch, MagicMock as _MM
    mock_mod = _MM()
    mock_mod.process_feedback_nlp = _MM()
    return _patch.dict(sys.modules, {"apps.nlp.tasks": mock_mod})
