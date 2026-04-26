"""
Unit tests for the translation service component.

Tests cover:
  - Redis cache hit (mocked Redis)
  - Redis cache miss → Google API call (mocked API)
  - Google fails → Azure fallback (mocked)
  - Both fail → translation_failed flag set
  - Text truncation with logging
  - Context passing and modification
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from apps.nlp.pipeline.translation_service import (
    _make_cache_key,
    translate_to_english,
)


class TestTranslationService:
    """Test suite for translation service logic."""

    def test_cache_key_generation(self):
        """Cache key should be consistent for same input."""
        key1 = _make_cache_key("sw", "Habari yako vipi?")
        key2 = _make_cache_key("sw", "Habari yako vipi?")
        assert key1 == key2
        assert key1.startswith("trans:")

    def test_cache_key_different_for_different_input(self):
        """Different inputs should produce different cache keys."""
        key1 = _make_cache_key("sw", "Text A")
        key2 = _make_cache_key("sw", "Text B")
        assert key1 != key2

    def test_english_text_returns_unchanged(self):
        """English text should return unchanged."""
        text = "This is already in English"
        result, context = translate_to_english(text, source_language="en")
        assert result == text
        assert context == {}

    def test_empty_text_returns_unchanged(self):
        """Empty text should return unchanged."""
        text = ""
        result, context = translate_to_english(text, source_language="sw")
        assert result == text
        assert context == {}

    def test_whitespace_only_text_returns_unchanged(self):
        """Whitespace-only text should return unchanged."""
        text = "   \n\t  "
        result, context = translate_to_english(text, source_language="sw")
        assert result == text
        assert context == {}

    def test_redis_cache_hit(self):
        """Cache hit should return cached translation without API call."""
        text = "Habari yako"
        context = {"feedback_id": "fb_123"}

        with patch("apps.nlp.pipeline.translation_service._get_redis_client") as mock_redis:
            redis_instance = MagicMock()
            redis_instance.get.return_value = "How are you"
            mock_redis.return_value = redis_instance

            with patch(
                "apps.nlp.pipeline.translation_service._get_google_client"
            ) as mock_google:
                result, updated_context = translate_to_english(
                    text, source_language="sw", context=context
                )

                assert result == "How are you"
                # Google client should not be called
                assert not mock_google.return_value.translate.called

    def test_redis_cache_miss_uses_google(self):
        """Cache miss should call Google API."""
        text = "Habari yako"
        context = {}

        with patch("apps.nlp.pipeline.translation_service._get_redis_client") as mock_redis:
            redis_instance = MagicMock()
            redis_instance.get.return_value = None  # Cache miss
            mock_redis.return_value = redis_instance

            with patch(
                "apps.nlp.pipeline.translation_service._get_google_client"
            ) as mock_google:
                google_instance = MagicMock()
                google_instance.translate.return_value = {
                    "translatedText": "How are you"
                }
                mock_google.return_value = google_instance

                result, updated_context = translate_to_english(
                    text, source_language="sw", context=context
                )

                assert result == "How are you"
                google_instance.translate.assert_called_once()

    def test_google_result_cached_in_redis(self):
        """Successful Google translation should be cached."""
        text = "Habari yako"

        with patch("apps.nlp.pipeline.translation_service._get_redis_client") as mock_redis:
            redis_instance = MagicMock()
            redis_instance.get.return_value = None
            mock_redis.return_value = redis_instance

            with patch(
                "apps.nlp.pipeline.translation_service._get_google_client"
            ) as mock_google:
                google_instance = MagicMock()
                google_instance.translate.return_value = {
                    "translatedText": "How are you"
                }
                mock_google.return_value = google_instance

                result, _ = translate_to_english(text, source_language="sw")

                assert result == "How are you"
                redis_instance.setex.assert_called_once()

    def test_google_fails_tries_azure_fallback(self):
        """Google failure should trigger Azure fallback."""
        text = "Habari yako"

        with patch("apps.nlp.pipeline.translation_service._get_redis_client") as mock_redis:
            redis_instance = MagicMock()
            redis_instance.get.return_value = None  # Cache miss
            mock_redis.return_value = redis_instance

            with patch(
                "apps.nlp.pipeline.translation_service._get_google_client"
            ) as mock_google:
                google_instance = MagicMock()
                google_instance.translate.side_effect = Exception("Google API error")
                mock_google.return_value = google_instance

                with patch(
                    "apps.nlp.pipeline.translation_service._is_azure_configured",
                    return_value=True
                ):
                    with patch(
                        "apps.nlp.pipeline.translation_service._translate_with_azure"
                    ) as mock_azure:
                        mock_azure.return_value = "How are you (from Azure)"

                        result, _ = translate_to_english(text, source_language="sw")

                        assert result == "How are you (from Azure)"
                        mock_azure.assert_called_once_with(text, "sw")

    def test_both_apis_fail_sets_translation_failed_flag(self):
        """Both API failures should set translation_failed flag."""
        text = "Habari yako"
        context = {"feedback_id": "fb_456"}

        with patch("apps.nlp.pipeline.translation_service._get_redis_client") as mock_redis:
            redis_instance = MagicMock()
            redis_instance.get.return_value = None
            mock_redis.return_value = redis_instance

            with patch(
                "apps.nlp.pipeline.translation_service._get_google_client"
            ) as mock_google:
                google_instance = MagicMock()
                google_instance.translate.side_effect = Exception("Google error")
                mock_google.return_value = google_instance

                with patch(
                    "apps.nlp.pipeline.translation_service._is_azure_configured",
                    return_value=True
                ):
                    with patch(
                        "apps.nlp.pipeline.translation_service._translate_with_azure"
                    ) as mock_azure:
                        mock_azure.return_value = None  # Azure also fails

                        result, updated_context = translate_to_english(
                            text, source_language="sw", context=context
                        )

                        assert result == text  # Returns original
                        assert updated_context.get("translation_failed") is True

    def test_text_truncation_at_5000_chars(self):
        """Text > 5000 chars should be truncated."""
        text = "a" * 6000
        context = {"feedback_id": "fb_789"}

        with patch("apps.nlp.pipeline.translation_service._get_redis_client") as mock_redis:
            redis_instance = MagicMock()
            redis_instance.get.return_value = None
            mock_redis.return_value = redis_instance

            with patch(
                "apps.nlp.pipeline.translation_service._get_google_client"
            ) as mock_google:
                google_instance = MagicMock()

                def google_translate_side_effect(text_arg, **kwargs):
                    # Verify truncation happened
                    assert len(text_arg) == 5000
                    return {"translatedText": "translated"}

                google_instance.translate.side_effect = google_translate_side_effect
                mock_google.return_value = google_instance

                result, _ = translate_to_english(text, source_language="sw", context=context)

                assert result == "translated"

    def test_truncation_logs_warning(self):
        """Truncation should log warning with feedback_id."""
        text = "x" * 6000
        context = {"feedback_id": "fb_001"}

        with patch("apps.nlp.pipeline.translation_service._get_redis_client"):
            with patch(
                "apps.nlp.pipeline.translation_service._get_google_client"
            ) as mock_google:
                google_instance = MagicMock()
                google_instance.translate.return_value = {"translatedText": "result"}
                mock_google.return_value = google_instance

                with patch(
                    "apps.nlp.pipeline.translation_service.logger"
                ) as mock_logger:
                    result, _ = translate_to_english(text, source_language="sw", context=context)

                    # Check warning was logged
                    mock_logger.warning.assert_called_once()
                    call_args = mock_logger.warning.call_args
                    assert "5000" in str(call_args)
                    assert "fb_001" in str(call_args)

    def test_azure_result_cached(self):
        """Successful Azure translation should be cached."""
        text = "Habari"

        with patch("apps.nlp.pipeline.translation_service._get_redis_client") as mock_redis:
            redis_instance = MagicMock()
            redis_instance.get.return_value = None
            mock_redis.return_value = redis_instance

            with patch(
                "apps.nlp.pipeline.translation_service._get_google_client"
            ) as mock_google:
                google_instance = MagicMock()
                google_instance.translate.side_effect = Exception("Google fails")
                mock_google.return_value = google_instance

                with patch(
                    "apps.nlp.pipeline.translation_service._is_azure_configured",
                    return_value=True
                ):
                    with patch(
                        "apps.nlp.pipeline.translation_service._translate_with_azure"
                    ) as mock_azure:
                        mock_azure.return_value = "Greetings"

                        result, _ = translate_to_english(text, source_language="sw")

                        assert result == "Greetings"
                        redis_instance.setex.assert_called_once()

    def test_azure_not_configured_returns_original(self):
        """Azure not configured should use Google, then return original if Google fails."""
        text = "Test"

        with patch("apps.nlp.pipeline.translation_service._get_redis_client") as mock_redis:
            redis_instance = MagicMock()
            redis_instance.get.return_value = None
            mock_redis.return_value = redis_instance

            with patch(
                "apps.nlp.pipeline.translation_service._get_google_client"
            ) as mock_google:
                google_instance = MagicMock()
                google_instance.translate.side_effect = Exception("Google fails")
                mock_google.return_value = google_instance

                with patch(
                    "apps.nlp.pipeline.translation_service._is_azure_configured"
                ) as mock_azure_config:
                    mock_azure_config.return_value = False

                    result, context = translate_to_english(text, source_language="sw", context={})

                    assert result == text
                    assert context.get("translation_failed") is True

    def test_context_preservation(self):
        """Original context should be preserved and updated."""
        text = "Test"
        context = {"feedback_id": "fb_x", "channel": "SMS"}

        with patch("apps.nlp.pipeline.translation_service._get_redis_client"):
            with patch(
                "apps.nlp.pipeline.translation_service._get_google_client"
            ) as mock_google:
                google_instance = MagicMock()
                google_instance.translate.return_value = {"translatedText": "Prueba"}
                mock_google.return_value = google_instance

                result, updated_context = translate_to_english(
                    text, source_language="es", context=context
                )

                # Original context preserved
                assert updated_context["feedback_id"] == "fb_x"
                assert updated_context["channel"] == "SMS"
                # No translation_failed should be added on success
                assert "translation_failed" not in updated_context

    def test_detect_and_translate_function_exists(self):
        """detect_and_translate should work for backward compatibility."""
        from apps.nlp.pipeline.translation_service import detect_and_translate

        with patch(
            "apps.nlp.pipeline.translation_service._get_google_client"
        ) as mock_google:
            google_instance = MagicMock()
            google_instance.translate.return_value = {
                "detectedSourceLanguage": "sw",
                "translatedText": "How are you",
            }
            mock_google.return_value = google_instance

            detected, translated = detect_and_translate("Habari yako")

            assert detected == "sw"
            assert translated == "How are you"

    def test_redis_connection_error_handled(self):
        """Redis connection error should not break translation."""
        text = "Habari"

        with patch("apps.nlp.pipeline.translation_service._get_redis_client") as mock_redis:
            redis_instance = MagicMock()
            redis_instance.get.side_effect = Exception("Redis error")
            mock_redis.return_value = redis_instance

            with patch(
                "apps.nlp.pipeline.translation_service._get_google_client"
            ) as mock_google:
                google_instance = MagicMock()
                google_instance.translate.return_value = {"translatedText": "Greetings"}
                mock_google.return_value = google_instance

                result, _ = translate_to_english(text, source_language="sw")

                # Should still translate despite Redis error
                assert result == "Greetings"

    def test_none_source_language_supported(self):
        """None source_language should be passed to API (auto-detect)."""
        text = "Unknown language text"

        with patch("apps.nlp.pipeline.translation_service._get_redis_client") as mock_redis:
            redis_instance = MagicMock()
            redis_instance.get.return_value = None
            mock_redis.return_value = redis_instance

            with patch(
                "apps.nlp.pipeline.translation_service._get_google_client"
            ) as mock_google:
                google_instance = MagicMock()
                google_instance.translate.return_value = {"translatedText": "result"}
                mock_google.return_value = google_instance

                result, _ = translate_to_english(text, source_language=None)

                google_instance.translate.assert_called_once()

    def test_unknown_source_language_passed_as_none(self):
        """'unknown' source_language should be treated as None for API."""
        text = "Text"

        with patch("apps.nlp.pipeline.translation_service._get_redis_client") as mock_redis:
            redis_instance = MagicMock()
            redis_instance.get.return_value = None
            mock_redis.return_value = redis_instance

            with patch(
                "apps.nlp.pipeline.translation_service._get_google_client"
            ) as mock_google:
                google_instance = MagicMock()
                google_instance.translate.return_value = {"translatedText": "result"}
                mock_google.return_value = google_instance

                result, _ = translate_to_english(text, source_language="unknown")

                # Should call with None, not "unknown"
                google_instance.translate.assert_called_once()
