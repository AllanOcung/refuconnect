"""
Unit tests for the translation service component.

Tests cover:
  - Redis cache hit (mocked Redis)
  - Redis cache miss → HuggingFace pipeline call (mocked)
  - HuggingFace pipeline failure → translation_failed flag set
  - Pipeline load failure → translation_failed flag set
  - Text truncation with logging
  - Context passing and modification
  - Model selection by language code
  - detect_and_translate backward compat
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from apps.nlp.pipeline.translation_service import (
    _get_model_name,
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
        """Cache hit should return cached translation without calling pipeline."""
        text = "Habari yako"
        context = {"feedback_id": "fb_123"}

        with patch("apps.nlp.pipeline.translation_service._get_redis_client") as mock_redis:
            redis_instance = MagicMock()
            redis_instance.get.return_value = "How are you"
            mock_redis.return_value = redis_instance

            with patch(
                "apps.nlp.pipeline.translation_service._get_translation_pipeline"
            ) as mock_pipe:
                result, updated_context = translate_to_english(
                    text, source_language="sw", context=context
                )

                assert result == "How are you"
                # Pipeline should not be called on cache hit
                mock_pipe.assert_not_called()

    def test_redis_cache_miss_uses_huggingface(self):
        """Cache miss should call HuggingFace pipeline."""
        text = "Habari yako"
        context = {}

        with patch("apps.nlp.pipeline.translation_service._get_redis_client") as mock_redis:
            redis_instance = MagicMock()
            redis_instance.get.return_value = None  # Cache miss
            mock_redis.return_value = redis_instance

            with patch(
                "apps.nlp.pipeline.translation_service._get_translation_pipeline"
            ) as mock_get_pipe:
                pipe_instance = MagicMock()
                pipe_instance.return_value = [{"translation_text": "How are you"}]
                mock_get_pipe.return_value = pipe_instance

                result, updated_context = translate_to_english(
                    text, source_language="sw", context=context
                )

                assert result == "How are you"
                pipe_instance.assert_called_once_with(text)

    def test_huggingface_result_cached_in_redis(self):
        """Successful HuggingFace translation should be cached in Redis."""
        text = "Habari yako"

        with patch("apps.nlp.pipeline.translation_service._get_redis_client") as mock_redis:
            redis_instance = MagicMock()
            redis_instance.get.return_value = None
            mock_redis.return_value = redis_instance

            with patch(
                "apps.nlp.pipeline.translation_service._get_translation_pipeline"
            ) as mock_get_pipe:
                pipe_instance = MagicMock()
                pipe_instance.return_value = [{"translation_text": "How are you"}]
                mock_get_pipe.return_value = pipe_instance

                result, _ = translate_to_english(text, source_language="sw")

                assert result == "How are you"
                redis_instance.setex.assert_called_once()

    def test_huggingface_fails_sets_translation_failed_flag(self):
        """HuggingFace pipeline error should set translation_failed flag."""
        text = "Habari yako"
        context = {"feedback_id": "fb_456"}

        with patch("apps.nlp.pipeline.translation_service._get_redis_client") as mock_redis:
            redis_instance = MagicMock()
            redis_instance.get.return_value = None
            mock_redis.return_value = redis_instance

            with patch(
                "apps.nlp.pipeline.translation_service._get_translation_pipeline"
            ) as mock_get_pipe:
                pipe_instance = MagicMock()
                pipe_instance.side_effect = Exception("Pipeline inference error")
                mock_get_pipe.return_value = pipe_instance

                result, updated_context = translate_to_english(
                    text, source_language="sw", context=context
                )

                assert result == text  # Returns original
                assert updated_context.get("translation_failed") is True

    def test_pipeline_load_failure_sets_translation_failed(self):
        """Pipeline load failure (None returned) should set translation_failed flag."""
        text = "Habari yako"
        context = {"feedback_id": "fb_789"}

        with patch("apps.nlp.pipeline.translation_service._get_redis_client") as mock_redis:
            redis_instance = MagicMock()
            redis_instance.get.return_value = None
            mock_redis.return_value = redis_instance

            with patch(
                "apps.nlp.pipeline.translation_service._get_translation_pipeline",
                return_value=None,
            ):
                result, updated_context = translate_to_english(
                    text, source_language="sw", context=context
                )

                assert result == text
                assert updated_context.get("translation_failed") is True

    def test_text_truncation_at_5000_chars(self):
        """Text > 5000 chars should be truncated before translation."""
        text = "a" * 6000
        context = {"feedback_id": "fb_789"}

        with patch("apps.nlp.pipeline.translation_service._get_redis_client") as mock_redis:
            redis_instance = MagicMock()
            redis_instance.get.return_value = None
            mock_redis.return_value = redis_instance

            with patch(
                "apps.nlp.pipeline.translation_service._get_translation_pipeline"
            ) as mock_get_pipe:
                pipe_instance = MagicMock()

                def pipe_side_effect(text_arg):
                    assert len(text_arg) == 5000
                    return [{"translation_text": "translated"}]

                pipe_instance.side_effect = pipe_side_effect
                mock_get_pipe.return_value = pipe_instance

                result, _ = translate_to_english(text, source_language="sw", context=context)

                assert result == "translated"

    def test_truncation_logs_warning(self):
        """Truncation should log warning with feedback_id."""
        text = "x" * 6000
        context = {"feedback_id": "fb_001"}

        with patch("apps.nlp.pipeline.translation_service._get_redis_client"):
            with patch(
                "apps.nlp.pipeline.translation_service._get_translation_pipeline"
            ) as mock_get_pipe:
                pipe_instance = MagicMock()
                pipe_instance.return_value = [{"translation_text": "result"}]
                mock_get_pipe.return_value = pipe_instance

                with patch(
                    "apps.nlp.pipeline.translation_service.logger"
                ) as mock_logger:
                    result, _ = translate_to_english(text, source_language="sw", context=context)

                    mock_logger.warning.assert_called_once()
                    call_args = mock_logger.warning.call_args
                    assert "5000" in str(call_args)
                    assert "fb_001" in str(call_args)

    def test_context_preservation(self):
        """Original context should be preserved and updated."""
        text = "Test"
        context = {"feedback_id": "fb_x", "channel": "SMS"}

        with patch("apps.nlp.pipeline.translation_service._get_redis_client"):
            with patch(
                "apps.nlp.pipeline.translation_service._get_translation_pipeline"
            ) as mock_get_pipe:
                pipe_instance = MagicMock()
                pipe_instance.return_value = [{"translation_text": "Prueba"}]
                mock_get_pipe.return_value = pipe_instance

                result, updated_context = translate_to_english(
                    text, source_language="es", context=context
                )

                assert updated_context["feedback_id"] == "fb_x"
                assert updated_context["channel"] == "SMS"
                assert "translation_failed" not in updated_context

    def test_detect_and_translate_returns_unknown(self):
        """detect_and_translate should return ('unknown', translated_text)."""
        from apps.nlp.pipeline.translation_service import detect_and_translate

        with patch("apps.nlp.pipeline.translation_service._get_redis_client") as mock_redis:
            redis_instance = MagicMock()
            redis_instance.get.return_value = None
            mock_redis.return_value = redis_instance

            with patch(
                "apps.nlp.pipeline.translation_service._get_translation_pipeline"
            ) as mock_get_pipe:
                pipe_instance = MagicMock()
                pipe_instance.return_value = [{"translation_text": "How are you"}]
                mock_get_pipe.return_value = pipe_instance

                detected, translated = detect_and_translate("Habari yako")

                assert detected == "unknown"
                assert translated == "How are you"

    def test_redis_connection_error_handled(self):
        """Redis connection error should not break translation."""
        text = "Habari"

        with patch("apps.nlp.pipeline.translation_service._get_redis_client") as mock_redis:
            redis_instance = MagicMock()
            redis_instance.get.side_effect = Exception("Redis error")
            mock_redis.return_value = redis_instance

            with patch(
                "apps.nlp.pipeline.translation_service._get_translation_pipeline"
            ) as mock_get_pipe:
                pipe_instance = MagicMock()
                pipe_instance.return_value = [{"translation_text": "Greetings"}]
                mock_get_pipe.return_value = pipe_instance

                result, _ = translate_to_english(text, source_language="sw")

                # Should still translate despite Redis error
                assert result == "Greetings"

    def test_none_source_language_returns_original(self):
        """C-07: None source_language should bypass translation and keep original text."""
        text = "Unknown language text"

        with patch(
            "apps.nlp.pipeline.translation_service._get_translation_pipeline"
        ) as mock_get_pipe:
            result, context = translate_to_english(text, source_language=None)

            assert result == text
            assert context == {}
            mock_get_pipe.assert_not_called()

    def test_unknown_source_language_uses_fallback_pipeline(self):
        """'unknown' source_language should go through the fallback pipeline."""
        text = "Text in unknown language"

        with patch("apps.nlp.pipeline.translation_service._get_redis_client") as mock_redis:
            redis_instance = MagicMock()
            redis_instance.get.return_value = None
            mock_redis.return_value = redis_instance

            with patch(
                "apps.nlp.pipeline.translation_service._get_translation_pipeline"
            ) as mock_get_pipe:
                pipe_instance = MagicMock()
                pipe_instance.return_value = [{"translation_text": "result"}]
                mock_get_pipe.return_value = pipe_instance

                result, _ = translate_to_english(text, source_language="unknown")

                # Pipeline should be called (not short-circuited)
                mock_get_pipe.assert_called_once_with("unknown")
                assert result == "result"

    def test_model_selection_sw_uses_multilingual_fallback(self):
        """Swahili uses the multilingual fallback (no dedicated sw-en model on HuggingFace)."""
        model = _get_model_name("sw")
        assert model == "Helsinki-NLP/opus-mt-mul-en"

    def test_model_selection_unknown_uses_fallback_model(self):
        """'unknown' and 'other' source languages should use the multilingual fallback."""
        assert _get_model_name("unknown") == "Helsinki-NLP/opus-mt-mul-en"
        assert _get_model_name("other") == "Helsinki-NLP/opus-mt-mul-en"
        assert _get_model_name(None) == "Helsinki-NLP/opus-mt-mul-en"

    def test_model_selection_unsupported_language_uses_fallback(self):
        """Unsupported language codes should fall back to the multilingual model."""
        model = _get_model_name("fr")
        assert model == "Helsinki-NLP/opus-mt-mul-en"

    def test_huggingface_result_not_cached_on_redis_error(self):
        """Redis setex error should not break translation."""
        text = "Habari"

        with patch("apps.nlp.pipeline.translation_service._get_redis_client") as mock_redis:
            redis_instance = MagicMock()
            redis_instance.get.return_value = None
            redis_instance.setex.side_effect = Exception("Redis write error")
            mock_redis.return_value = redis_instance

            with patch(
                "apps.nlp.pipeline.translation_service._get_translation_pipeline"
            ) as mock_get_pipe:
                pipe_instance = MagicMock()
                pipe_instance.return_value = [{"translation_text": "Greetings"}]
                mock_get_pipe.return_value = pipe_instance

                result, context = translate_to_english(text, source_language="sw")

                # Translation should still succeed even if caching fails
                assert result == "Greetings"
                assert "translation_failed" not in context

    def test_no_redis_translation_still_works(self):
        """Translation should work when Redis is unavailable."""
        text = "Habari"

        with patch(
            "apps.nlp.pipeline.translation_service._get_redis_client",
            return_value=None,
        ):
            with patch(
                "apps.nlp.pipeline.translation_service._get_translation_pipeline"
            ) as mock_get_pipe:
                pipe_instance = MagicMock()
                pipe_instance.return_value = [{"translation_text": "Greetings"}]
                mock_get_pipe.return_value = pipe_instance

                result, context = translate_to_english(text, source_language="sw")

                assert result == "Greetings"
                assert "translation_failed" not in context

