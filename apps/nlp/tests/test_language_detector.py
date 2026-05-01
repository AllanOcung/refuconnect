"""
Unit tests for the language detector component.

Tests cover:
  - USSD language hint handling (trust hint, skip model)
  - Short text (<10 chars) detection
  - Unsupported language filtering
  - Low confidence flagging for review
  - Model loading and k=3 predictions
  - Text cleaning (URLs, whitespace)
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from apps.nlp.pipeline.language_detector import detect_language


class TestLanguageDetector:
    """Test suite for language detection logic."""

    def test_ussd_hint_trusted_returns_confidence_1(self):
        """USSD language hint should be trusted with confidence 1.0."""
        text = "any text here"
        lang, confidence, flags = detect_language(text, ussd_language="sw")
        assert lang == "sw"
        assert confidence == 1.0
        assert not flags["needs_language_review"]

    def test_ussd_hint_empty_string_ignored(self):
        """Empty string USSD hint should be ignored (fallback to model)."""
        text = "some text to detect"
        # Mock model to avoid loading fasttext
        with patch("apps.nlp.pipeline.language_detector._get_model") as mock_model:
            mock_instance = MagicMock()
            mock_instance.predict.return_value = (["__label__en"], [0.95])
            mock_model.return_value = mock_instance

            lang, confidence, flags = detect_language(text, ussd_language="")
            # Should use model since hint is empty
            assert lang == "en"
            assert confidence == 0.95

    def test_short_text_returns_unknown(self):
        """Text < 10 chars must return unknown, confidence=0.50 and flag review (C-06 §2)."""
        text = "hi"
        lang, confidence, flags = detect_language(text)
        assert lang == "unknown"
        assert confidence == 0.50
        assert flags["needs_language_review"] is True

    def test_short_text_with_spaces_stripped(self):
        """Short text (after stripping) must also return 0.50 and flag review."""
        text = "  abc  "  # 3 chars after strip
        lang, confidence, flags = detect_language(text)
        assert lang == "unknown"
        assert confidence == 0.50
        assert flags["needs_language_review"] is True

    def test_unsupported_language_returns_other(self):
        """Unsupported fastText top-1 + AfroLID miss → language='other' (C-06 §4)."""
        text = "This is a test message for language detection"
        with patch("apps.nlp.pipeline.language_detector._get_model") as mock_model, \
            patch("apps.nlp.pipeline.language_detector._detect_with_afrolid",
                  return_value=("unknown", 0.0, {"needs_language_review": True, "top_predictions": []})):
            mock_instance = MagicMock()
            mock_instance.predict.return_value = (
                ["__label__zh", "__label__ja", "__label__ko"],
                [0.92, 0.05, 0.03],
            )
            mock_model.return_value = mock_instance

            lang, confidence, flags = detect_language(text)
            assert lang == "other"
            assert confidence == 0.92
            assert flags["needs_language_review"]

    def test_low_confidence_uses_afrolid_fallback(self):
        """Low-confidence fastText output should fall back to AfroLID."""
        text = "This is a test message for language detection"
        with patch("apps.nlp.pipeline.language_detector._get_model") as mock_model, \
            patch("apps.nlp.pipeline.language_detector._get_afrolid_model") as mock_afrolid_model:
            mock_fasttext = MagicMock()
            mock_fasttext.predict.return_value = (
                ["__label__en", "__label__fr", "__label__de"],
                [0.78, 0.15, 0.07],
            )
            mock_model.return_value = mock_fasttext

            mock_afrolid = MagicMock()
            mock_afrolid.classify.return_value = {
                "eng": {"score": 82.0, "name": "English", "script": "Latin"},
                "swa": {"score": 9.0, "name": "Swahili", "script": "Latin"},
            }
            mock_afrolid_model.return_value = mock_afrolid

            lang, confidence, flags = detect_language(text)
            assert lang == "en"
            assert confidence == 0.82
            assert flags["needs_language_review"]

    def test_high_confidence_no_review_flag(self):
        """Confidence >= 0.85 should not flag review."""
        text = "This is a test message for language detection"
        with patch("apps.nlp.pipeline.language_detector._get_model") as mock_model:
            mock_instance = MagicMock()
            mock_instance.predict.return_value = (
                ["__label__en", "__label__sw", "__label__fr"],
                [0.92, 0.05, 0.03],
            )
            mock_model.return_value = mock_instance

            lang, confidence, flags = detect_language(text)
            assert lang == "en"
            assert confidence == 0.92
            assert not flags["needs_language_review"]

    def test_top_3_predictions_returned(self):
        """Top 3 predictions should be in review_flags."""
        text = "This is a test message for language detection"
        with patch("apps.nlp.pipeline.language_detector._get_model") as mock_model:
            mock_instance = MagicMock()
            mock_instance.predict.return_value = (
                ["__label__en", "__label__sw", "__label__lg"],
                [0.90, 0.06, 0.04],
            )
            mock_model.return_value = mock_instance

            lang, confidence, flags = detect_language(text)
            assert len(flags["top_predictions"]) == 3
            assert flags["top_predictions"][0] == ("en", 0.90)
            assert flags["top_predictions"][1] == ("sw", 0.06)
            assert flags["top_predictions"][2] == ("lg", 0.04)

    def test_swahili_detected(self):
        """Swahili should be recognized as supported language."""
        text = "Habari yako vipi? Nani anaye weza kusaidia?"
        with patch("apps.nlp.pipeline.language_detector._get_model") as mock_model:
            mock_instance = MagicMock()
            mock_instance.predict.return_value = (
                ["__label__sw", "__label__en", "__label__lg"],
                [0.88, 0.08, 0.04],
            )
            mock_model.return_value = mock_instance

            lang, confidence, flags = detect_language(text)
            assert lang == "sw"
            assert confidence == 0.88

    def test_swahili_phrase_overrides_weak_fasttext_prediction(self):
        """Swahili should come from AfroLID when fastText is weak."""
        text = "Fanya kazi nzuri"
        with patch("apps.nlp.pipeline.language_detector._get_model") as mock_model, \
            patch("apps.nlp.pipeline.language_detector._get_afrolid_model") as mock_afrolid_model:
            mock_fasttext = MagicMock()
            mock_fasttext.predict.return_value = (
                ["__label__en", "__label__sw", "__label__vo"],
                [0.23, 0.22, 0.06],
            )
            mock_model.return_value = mock_fasttext

            mock_afrolid = MagicMock()
            mock_afrolid.classify.return_value = {
                "swa": {"score": 91.0, "name": "Swahili", "script": "Latin"},
                "eng": {"score": 8.0, "name": "English", "script": "Latin"},
            }
            mock_afrolid_model.return_value = mock_afrolid

            lang, confidence, flags = detect_language(text)
            assert lang == "sw"
            assert confidence == 0.91

    def test_swahili_phrase_falls_back_from_unsupported_predictions(self):
        """Common Swahili text should recover even when fastText misses it."""
        text = "Ninaenda sokoni kununua matunda"
        with patch("apps.nlp.pipeline.language_detector._get_model") as mock_model, \
            patch("apps.nlp.pipeline.language_detector._get_afrolid_model") as mock_afrolid_model:
            mock_fasttext = MagicMock()
            mock_fasttext.predict.return_value = (
                ["__label__nl", "__label__eo", "__label__id"],
                [0.18, 0.15, 0.13],
            )
            mock_model.return_value = mock_fasttext

            mock_afrolid = MagicMock()
            mock_afrolid.classify.return_value = {
                "swa": {"score": 88.0, "name": "Swahili", "script": "Latin"},
                "eng": {"score": 7.0, "name": "English", "script": "Latin"},
            }
            mock_afrolid_model.return_value = mock_afrolid

            lang, confidence, flags = detect_language(text)
            assert lang == "sw"
            assert confidence == 0.88

    def test_unsupported_language_still_returns_other(self):
        """Arabic text (unsupported top-1, AfroLID miss) → language='other'."""
        text = "مرحبا بك في برنامج جمع التغذية الراجعة"
        with patch("apps.nlp.pipeline.language_detector._get_model") as mock_model, \
            patch("apps.nlp.pipeline.language_detector._detect_with_afrolid",
                  return_value=("unknown", 0.0, {"needs_language_review": True, "top_predictions": []})):
            mock_instance = MagicMock()
            mock_instance.predict.return_value = (
                ["__label__ar", "__label__en", "__label__fr"],
                [0.91, 0.05, 0.04],
            )
            mock_model.return_value = mock_instance

            lang, confidence, flags = detect_language(text)
            assert lang == "other"
            assert confidence == 0.91

    def test_text_cleaning_removes_urls(self):
        """URLs should be removed during text cleaning."""
        text = "Check this http://example.com and https://test.org website"
        with patch("apps.nlp.pipeline.language_detector._get_model") as mock_model:
            mock_instance = MagicMock()

            def predict_side_effect(clean_text, k):
                # Verify URLs were removed
                assert "http" not in clean_text
                assert "example.com" not in clean_text
                return (["__label__en"], [0.95])

            mock_instance.predict.side_effect = predict_side_effect
            mock_model.return_value = mock_instance

            lang, confidence, flags = detect_language(text)
            assert lang == "en"

    def test_text_cleaning_collapses_whitespace(self):
        """Multiple whitespaces should collapse to single space."""
        text = "This    has    multiple     spaces   "
        with patch("apps.nlp.pipeline.language_detector._get_model") as mock_model:
            mock_instance = MagicMock()

            def predict_side_effect(clean_text, k):
                # Verify whitespace was collapsed
                assert "    " not in clean_text
                assert clean_text.count(" ") <= 5  # At most normal spacing
                return (["__label__en"], [0.95])

            mock_instance.predict.side_effect = predict_side_effect
            mock_model.return_value = mock_instance

            lang, confidence, flags = detect_language(text)
            assert lang == "en"

    def test_model_not_available_returns_unknown(self):
        """Model unavailable should return unknown gracefully."""
        text = "This is a test message"
        with patch("apps.nlp.pipeline.language_detector._get_model") as mock_model:
            mock_model.return_value = None

            lang, confidence, flags = detect_language(text)
            assert lang == "unknown"
            assert confidence == 0.0

    def test_model_predict_exception_handled(self):
        """Model predict exception should be caught and return unknown."""
        text = "This is a test message"
        with patch("apps.nlp.pipeline.language_detector._get_model") as mock_model:
            mock_instance = MagicMock()
            mock_instance.predict.side_effect = Exception("Model error")
            mock_model.return_value = mock_instance

            lang, confidence, flags = detect_language(text)
            assert lang == "unknown"
            assert confidence == 0.0

    def test_return_tuple_structure(self):
        """Return value should be (lang, confidence, review_flags_dict)."""
        text = "This is a test message"
        result = detect_language(text)
        assert isinstance(result, tuple)
        assert len(result) == 3
        lang, confidence, flags = result
        assert isinstance(lang, str)
        assert isinstance(confidence, float)
        assert isinstance(flags, dict)
        assert "needs_language_review" in flags
        assert "top_predictions" in flags

    def test_text_truncated_to_1000_chars(self):
        """Text longer than 1000 chars should be truncated."""
        text = "a" * 2000
        with patch("apps.nlp.pipeline.language_detector._get_model") as mock_model:
            mock_instance = MagicMock()

            def predict_side_effect(truncated_text, k):
                # Verify text was truncated
                assert len(truncated_text) <= 1000
                return (["__label__en"], [0.95])

            mock_instance.predict.side_effect = predict_side_effect
            mock_model.return_value = mock_instance

            lang, confidence, flags = detect_language(text)
            assert lang == "en"

    def test_non_supported_language_returns_other(self):
        """Non-English/non-Swahili fastText output → language='other' (C-06 §4)."""
        text = "Ici ni umwanzo w'igitangazo"
        with patch("apps.nlp.pipeline.language_detector._get_model") as mock_model, \
            patch("apps.nlp.pipeline.language_detector._detect_with_afrolid",
                  return_value=("unknown", 0.0, {"needs_language_review": True, "top_predictions": []})):
            mock_instance = MagicMock()
            mock_instance.predict.return_value = (
                ["__label__rw", "__label__sw", "__label__en"],
                [0.85, 0.10, 0.05],
            )
            mock_model.return_value = mock_instance

            lang, confidence, flags = detect_language(text)
            assert lang == "other"
            assert confidence == 0.85
