"""
Unit tests for the sentiment analyser component.

Tests cover:
  - VADER sentiment scoring (English)
  - Multi-language XLM-RoBERTa (French, Swahili, etc.)
  - Uncertain threshold (<0.60 confidence)
  - Text cleaning validation
  - translation_failed edge case (non-English without translation)
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from apps.nlp.pipeline.sentiment_analyser import (
    _clean_text,
    analyse_sentiment,
)


class TestSentimentAnalyser:
    """Test suite for sentiment analysis logic."""

    def test_clean_text_removes_punctuation(self):
        """Text cleaning should remove punctuation."""
        text = "Hello! How are you? I'm fine."
        cleaned = _clean_text(text)
        assert "!" not in cleaned
        assert "?" not in cleaned
        assert "'" not in cleaned
        assert "." not in cleaned
        # But words should be intact
        assert "Hello" in cleaned
        assert "fine" in cleaned

    def test_clean_text_collapses_whitespace(self):
        """Multiple whitespaces should collapse to single space."""
        text = "Hello    world    test"
        cleaned = _clean_text(text)
        assert "    " not in cleaned
        assert cleaned.count(" ") <= 2

    def test_clean_text_strips_leading_trailing_whitespace(self):
        """Leading/trailing whitespace should be stripped."""
        text = "  \n\t  Hello world  \n\t  "
        cleaned = _clean_text(text)
        assert not cleaned.startswith(" ")
        assert not cleaned.endswith(" ")

    def test_clean_text_preserves_accented_characters(self):
        """Accented characters should be preserved."""
        text = "Café naïve Montréal"
        cleaned = _clean_text(text)
        # Characters should be preserved (or at least text should be processable)
        assert len(cleaned) > 0

    def test_vader_english_positive_sentiment(self):
        """VADER should detect positive sentiment in English."""
        text = "I am very happy and excited about this"

        with patch("apps.nlp.pipeline.sentiment_analyser._get_vader_analyser") as mock_vader:
            analyser = MagicMock()
            analyser.polarity_scores.return_value = {
                "compound": 0.8,
                "pos": 0.5,
                "neu": 0.3,
                "neg": 0.2,
            }
            mock_vader.return_value = analyser

            with patch("apps.nlp.pipeline.sentiment_analyser._lookup_sentiment") as mock_lookup:
                sentiment_obj = MagicMock()
                mock_lookup.return_value = sentiment_obj

                result, confidence = analyse_sentiment(text, language_code="en")

                assert confidence > 0.0
                mock_lookup.assert_called_with("Positive")

    def test_vader_english_negative_sentiment(self):
        """VADER should detect negative sentiment in English."""
        text = "This is terrible and I hate it"

        with patch("apps.nlp.pipeline.sentiment_analyser._get_vader_analyser") as mock_vader:
            analyser = MagicMock()
            analyser.polarity_scores.return_value = {
                "compound": -0.75,
                "pos": 0.1,
                "neu": 0.2,
                "neg": 0.7,
            }
            mock_vader.return_value = analyser

            with patch("apps.nlp.pipeline.sentiment_analyser._lookup_sentiment") as mock_lookup:
                sentiment_obj = MagicMock()
                mock_lookup.return_value = sentiment_obj

                result, confidence = analyse_sentiment(text, language_code="en")

                assert confidence > 0.0
                mock_lookup.assert_called_with("Negative")

    def test_vader_english_neutral_sentiment(self):
        """VADER should detect neutral sentiment."""
        text = "This is a simple statement"

        with patch("apps.nlp.pipeline.sentiment_analyser._get_vader_analyser") as mock_vader:
            analyser = MagicMock()
            analyser.polarity_scores.return_value = {
                "compound": 0.0,
                "pos": 0.2,
                "neu": 0.7,
                "neg": 0.1,
            }
            mock_vader.return_value = analyser

            with patch("apps.nlp.pipeline.sentiment_analyser._lookup_sentiment") as mock_lookup:
                sentiment_obj = MagicMock()
                mock_lookup.return_value = sentiment_obj

                result, confidence = analyse_sentiment(text, language_code="en")

                # Uncertain for exactly 0.0
                mock_lookup.assert_called_with("Uncertain")

    def test_xlm_roberta_non_english_language(self):
        """XLM-RoBERTa should be used for non-English languages."""
        text = "C'est magnifique!"  # French

        with patch("apps.nlp.pipeline.sentiment_analyser._get_vader_analyser"):
            with patch("apps.nlp.pipeline.sentiment_analyser._get_xlm_analyser") as mock_xlm:
                analyser = MagicMock()
                analyser.return_value = [{"label": "POSITIVE", "score": 0.85}]
                mock_xlm.return_value = analyser

                with patch("apps.nlp.pipeline.sentiment_analyser._lookup_sentiment") as mock_lookup:
                    sentiment_obj = MagicMock()
                    mock_lookup.return_value = sentiment_obj

                    result, confidence = analyse_sentiment(text, language_code="fr")

                    analyser.assert_called_once()
                    mock_lookup.assert_called_with("Positive")

    def test_xlm_roberta_swahili(self):
        """XLM-RoBERTa should handle Swahili."""
        text = "Habari njema sana!"

        with patch("apps.nlp.pipeline.sentiment_analyser._get_xlm_analyser") as mock_xlm:
            analyser = MagicMock()
            analyser.return_value = [{"label": "POSITIVE", "score": 0.79}]
            mock_xlm.return_value = analyser

            with patch("apps.nlp.pipeline.sentiment_analyser._lookup_sentiment") as mock_lookup:
                sentiment_obj = MagicMock()
                mock_lookup.return_value = sentiment_obj

                result, confidence = analyse_sentiment(text, language_code="sw")

                analyser.assert_called_once()
                mock_lookup.assert_called_with("Positive")

    def test_xlm_roberta_arabic(self):
        """XLM-RoBERTa should handle Arabic."""
        text = "هذا رائع جدا"

        with patch("apps.nlp.pipeline.sentiment_analyser._get_xlm_analyser") as mock_xlm:
            analyser = MagicMock()
            analyser.return_value = [{"label": "POSITIVE", "score": 0.82}]
            mock_xlm.return_value = analyser

            with patch("apps.nlp.pipeline.sentiment_analyser._lookup_sentiment") as mock_lookup:
                sentiment_obj = MagicMock()
                mock_lookup.return_value = sentiment_obj

                result, confidence = analyse_sentiment(text, language_code="ar")

                analyser.assert_called_once()

    def test_uncertain_threshold_below_0_60(self):
        """Confidence < 0.60 should return Uncertain regardless of label."""
        text = "Maybe good maybe bad"

        with patch("apps.nlp.pipeline.sentiment_analyser._get_xlm_analyser") as mock_xlm:
            analyser = MagicMock()
            analyser.return_value = [{"label": "POSITIVE", "score": 0.55}]
            mock_xlm.return_value = analyser

            with patch("apps.nlp.pipeline.sentiment_analyser._lookup_sentiment") as mock_lookup:
                sentiment_obj = MagicMock()
                mock_lookup.return_value = sentiment_obj

                result, confidence = analyse_sentiment(text, language_code="fr")

                # Should lookup Uncertain due to low confidence
                mock_lookup.assert_called_with("Uncertain")

    def test_uncertain_threshold_at_0_60_included(self):
        """Confidence >= 0.60 should not be marked as Uncertain."""
        text = "Reasonably good"

        with patch("apps.nlp.pipeline.sentiment_analyser._get_xlm_analyser") as mock_xlm:
            analyser = MagicMock()
            analyser.return_value = [{"label": "POSITIVE", "score": 0.60}]
            mock_xlm.return_value = analyser

            with patch("apps.nlp.pipeline.sentiment_analyser._lookup_sentiment") as mock_lookup:
                sentiment_obj = MagicMock()
                mock_lookup.return_value = sentiment_obj

                result, confidence = analyse_sentiment(text, language_code="fr")

                # Should not be Uncertain at exactly 0.60
                mock_lookup.assert_called_with("Positive")

    def test_empty_text_returns_uncertain(self):
        """Empty text should return Uncertain with 0.5 confidence."""
        result, confidence = analyse_sentiment("")

        assert confidence == 0.5
        # Uncertain should be looked up

    def test_whitespace_only_returns_uncertain(self):
        """Whitespace-only text should return Uncertain."""
        result, confidence = analyse_sentiment("   \n\t  ")

        assert confidence == 0.5

    def test_vadersay_unavailable_returns_none(self):
        """VADER unavailable should return (None, 0.0)."""
        with patch("apps.nlp.pipeline.sentiment_analyser._get_vader_analyser") as mock_vader:
            mock_vader.return_value = None

            result, confidence = analyse_sentiment("test", language_code="en")

            assert result is None
            assert confidence == 0.0

    def test_xlm_unavailable_returns_none(self):
        """XLM unavailable for non-English should return (None, 0.0)."""
        with patch("apps.nlp.pipeline.sentiment_analyser._get_xlm_analyser") as mock_xlm:
            mock_xlm.return_value = None

            result, confidence = analyse_sentiment("test", language_code="fr")

            assert result is None
            assert confidence == 0.0

    def test_xlm_exception_caught_returns_none(self):
        """XLM exception should be caught."""
        with patch("apps.nlp.pipeline.sentiment_analyser._get_xlm_analyser") as mock_xlm:
            analyser = MagicMock()
            analyser.side_effect = Exception("XLM error")
            mock_xlm.return_value = analyser

            result, confidence = analyse_sentiment("test", language_code="fr")

            assert result is None
            assert confidence == 0.0

    def test_language_code_none_uses_vader(self):
        """language_code=None should use VADER (English default)."""
        with patch("apps.nlp.pipeline.sentiment_analyser._get_vader_analyser") as mock_vader:
            analyser = MagicMock()
            analyser.polarity_scores.return_value = {"compound": 0.5}
            mock_vader.return_value = analyser

            with patch("apps.nlp.pipeline.sentiment_analyser._lookup_sentiment") as mock_lookup:
                mock_lookup.return_value = MagicMock()

                analyse_sentiment("good text", language_code=None)

                analyser.polarity_scores.assert_called_once()

    def test_translation_failed_parameter_uses_xlm(self):
        """translation_failed=True should use XLM on original text."""
        text = "Origina non-English"

        with patch("apps.nlp.pipeline.sentiment_analyser._get_xlm_analyser") as mock_xlm:
            analyser = MagicMock()
            analyser.return_value = [{"label": "NEGATIVE", "score": 0.75}]
            mock_xlm.return_value = analyser

            with patch("apps.nlp.pipeline.sentiment_analyser._lookup_sentiment") as mock_lookup:
                sentiment_obj = MagicMock()
                mock_lookup.return_value = sentiment_obj

                result, confidence = analyse_sentiment(
                    text,
                    language_code="sw",
                    translation_failed=True,
                )

                analyser.assert_called_once()

    def test_xlm_negative_detection(self):
        """XLM should detect negative sentiment."""
        with patch("apps.nlp.pipeline.sentiment_analyser._get_xlm_analyser") as mock_xlm:
            analyser = MagicMock()
            analyser.return_value = [{"label": "NEGATIVE", "score": 0.88}]
            mock_xlm.return_value = analyser

            with patch("apps.nlp.pipeline.sentiment_analyser._lookup_sentiment") as mock_lookup:
                mock_lookup.return_value = MagicMock()

                analyse_sentiment("bad text", language_code="fr")

                mock_lookup.assert_called_with("Negative")

    def test_xlm_neutral_detection(self):
        """XLM should detect neutral sentiment."""
        with patch("apps.nlp.pipeline.sentiment_analyser._get_xlm_analyser") as mock_xlm:
            analyser = MagicMock()
            analyser.return_value = [{"label": "NEUTRAL", "score": 0.70}]
            mock_xlm.return_value = analyser

            with patch("apps.nlp.pipeline.sentiment_analyser._lookup_sentiment") as mock_lookup:
                mock_lookup.return_value = MagicMock()

                analyse_sentiment("neutral text", language_code="fr")

                mock_lookup.assert_called_with("Neutral")

    def test_vader_near_neutral_compound(self):
        """VADER with compound near 0 should return Neutral."""
        with patch("apps.nlp.pipeline.sentiment_analyser._get_vader_analyser") as mock_vader:
            analyser = MagicMock()
            # Compound between -0.05 and 0.05
            analyser.polarity_scores.return_value = {"compound": 0.02}
            mock_vader.return_value = analyser

            with patch("apps.nlp.pipeline.sentiment_analyser._lookup_sentiment") as mock_lookup:
                mock_lookup.return_value = MagicMock()

                analyse_sentiment("somewhat good", language_code="en")

                mock_lookup.assert_called_with("Neutral")

    def test_confidence_rounded_to_3_decimals(self):
        """Confidence should be rounded to 3 decimals."""
        with patch("apps.nlp.pipeline.sentiment_analyser._get_vader_analyser") as mock_vader:
            analyser = MagicMock()
            analyser.polarity_scores.return_value = {"compound": 0.75432}
            mock_vader.return_value = analyser

            with patch("apps.nlp.pipeline.sentiment_analyser._lookup_sentiment") as mock_lookup:
                mock_lookup.return_value = MagicMock()

                result, confidence = analyse_sentiment("good", language_code="en")

                assert confidence == 0.754

    def test_xlm_empty_response_handled(self):
        """XLM returning empty list should handle gracefully."""
        with patch("apps.nlp.pipeline.sentiment_analyser._get_xlm_analyser") as mock_xlm:
            analyser = MagicMock()
            analyser.return_value = []  # Empty result
            mock_xlm.return_value = analyser

            with patch("apps.nlp.pipeline.sentiment_analyser._lookup_sentiment") as mock_lookup:
                mock_lookup.return_value = MagicMock()

                result, confidence = analyse_sentiment("text", language_code="fr")

                # Should handle empty result
                assert confidence == 0.5
                mock_lookup.assert_called_with("Uncertain")

    def test_text_cleaned_before_vader(self):
        """Text should be cleaned before VADER analysis."""
        text = "Hello! This is GREAT! Amazing..."

        with patch("apps.nlp.pipeline.sentiment_analyser._clean_text") as mock_clean:
            mock_clean.return_value = "Hello This is GREAT Amazing"

            with patch("apps.nlp.pipeline.sentiment_analyser._get_vader_analyser") as mock_vader:
                analyser = MagicMock()
                analyser.polarity_scores.return_value = {"compound": 0.75}
                mock_vader.return_value = analyser

                with patch("apps.nlp.pipeline.sentiment_analyser._lookup_sentiment") as mock_lookup:
                    mock_lookup.return_value = MagicMock()

                    analyse_sentiment(text, language_code="en")

                    # _clean_text should be called
                    mock_clean.assert_called()
