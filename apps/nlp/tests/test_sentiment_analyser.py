"""Unit tests for C-10 SentimentAnalyser."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from apps.nlp.pipeline.sentiment_analyser import (
    _clean_text,
    _map_xlm_label,
    analyse_feedback_sentiment,
    analyse_sentiment,
)


def _make_feedback(*, message_text: str, message_text_en: str = "", language: str = "en"):
    fb = MagicMock()
    fb.message_text = message_text
    fb.message_text_en = message_text_en
    fb.language = language
    fb.sentiment = None
    fb.sentiment_confidence = None
    return fb


class TestTextCleaning:
    def test_clean_text_collapses_whitespace(self):
        cleaned = _clean_text("Hello    world\n\nagain")
        assert cleaned == "Hello world again"

    def test_clean_text_reduces_excessive_punctuation(self):
        cleaned = _clean_text("Help!!! Why???")
        assert cleaned == "Help! Why?"


class TestVaderLogic:
    def test_vader_positive_from_compound(self):
        with patch("apps.nlp.pipeline.sentiment_analyser._get_vader_analyser") as mock_vader:
            analyser = MagicMock()
            analyser.polarity_scores.return_value = {
                "compound": 0.80,
                "pos": 0.82,
                "neu": 0.10,
                "neg": 0.08,
            }
            mock_vader.return_value = analyser
            with patch("apps.nlp.pipeline.sentiment_analyser._lookup_sentiment") as mock_lookup:
                mock_lookup.return_value = MagicMock()
                _, conf = analyse_sentiment("great news", language_code="en")
                assert conf == 0.82
                mock_lookup.assert_called_with("Positive")

    def test_vader_negative_from_compound(self):
        with patch("apps.nlp.pipeline.sentiment_analyser._get_vader_analyser") as mock_vader:
            analyser = MagicMock()
            analyser.polarity_scores.return_value = {
                "compound": -0.30,
                "pos": 0.10,
                "neu": 0.20,
                "neg": 0.70,
            }
            mock_vader.return_value = analyser
            with patch("apps.nlp.pipeline.sentiment_analyser._lookup_sentiment") as mock_lookup:
                mock_lookup.return_value = MagicMock()
                analyse_sentiment("terrible", language_code="en")
                mock_lookup.assert_called_with("Negative")

    def test_vader_neutral_between_thresholds(self):
        with patch("apps.nlp.pipeline.sentiment_analyser._get_vader_analyser") as mock_vader:
            analyser = MagicMock()
            analyser.polarity_scores.return_value = {
                "compound": 0.00,
                "pos": 0.15,
                "neu": 0.75,
                "neg": 0.10,
            }
            mock_vader.return_value = analyser
            with patch("apps.nlp.pipeline.sentiment_analyser._lookup_sentiment") as mock_lookup:
                mock_lookup.return_value = MagicMock()
                analyse_sentiment("statement", language_code="en")
                mock_lookup.assert_called_with("Neutral")

    def test_vader_low_confidence_forces_uncertain(self):
        with patch("apps.nlp.pipeline.sentiment_analyser._get_vader_analyser") as mock_vader:
            analyser = MagicMock()
            analyser.polarity_scores.return_value = {
                "compound": 0.40,
                "pos": 0.35,
                "neu": 0.34,
                "neg": 0.31,
            }
            mock_vader.return_value = analyser
            with patch("apps.nlp.pipeline.sentiment_analyser._lookup_sentiment") as mock_lookup:
                mock_lookup.return_value = MagicMock()
                analyse_sentiment("mixed", language_code="en")
                mock_lookup.assert_called_with("Uncertain")


class TestXlmLogic:
    def test_map_labels_label_0_1_2(self):
        assert _map_xlm_label("LABEL_0") == "Negative"
        assert _map_xlm_label("LABEL_1") == "Neutral"
        assert _map_xlm_label("LABEL_2") == "Positive"

    def test_xlm_label_mapping_negative(self):
        with patch("apps.nlp.pipeline.sentiment_analyser._get_xlm_analyser") as mock_xlm:
            analyser = MagicMock()
            analyser.return_value = [{"label": "LABEL_0", "score": 0.91}]
            mock_xlm.return_value = analyser
            with patch("apps.nlp.pipeline.sentiment_analyser._lookup_sentiment") as mock_lookup:
                mock_lookup.return_value = MagicMock()
                analyse_sentiment("mbaya", language_code="sw")
                mock_lookup.assert_called_with("Negative")

    def test_xlm_low_confidence_forces_uncertain(self):
        with patch("apps.nlp.pipeline.sentiment_analyser._get_xlm_analyser") as mock_xlm:
            analyser = MagicMock()
            analyser.return_value = [{"label": "LABEL_2", "score": 0.55}]
            mock_xlm.return_value = analyser
            with patch("apps.nlp.pipeline.sentiment_analyser._lookup_sentiment") as mock_lookup:
                mock_lookup.return_value = MagicMock()
                analyse_sentiment("bien", language_code="fr")
                mock_lookup.assert_called_with("Uncertain")

    def test_xlm_empty_response_returns_uncertain(self):
        with patch("apps.nlp.pipeline.sentiment_analyser._get_xlm_analyser") as mock_xlm:
            analyser = MagicMock()
            analyser.return_value = []
            mock_xlm.return_value = analyser
            with patch("apps.nlp.pipeline.sentiment_analyser._lookup_sentiment") as mock_lookup:
                mock_lookup.return_value = MagicMock()
                _, conf = analyse_sentiment("text", language_code="fr")
                assert conf == 0.5
                mock_lookup.assert_called_with("Uncertain")


class TestFeedbackApi:
    def test_feedback_api_uses_translated_text_when_available(self):
        fb = _make_feedback(
            message_text="Ninateseka",
            message_text_en="I am suffering",
            language="sw",
        )

        with patch("apps.nlp.pipeline.sentiment_analyser.analyse_sentiment") as mock_analyse:
            mock_sentiment = MagicMock()
            mock_analyse.return_value = (mock_sentiment, 0.88)

            sentiment_obj, conf, ctx = analyse_feedback_sentiment(fb, translation_failed=False)

            mock_analyse.assert_called_once_with(
                "I am suffering",
                language_code="en",
                translation_failed=False,
            )
            assert sentiment_obj is mock_sentiment
            assert conf == 0.88
            assert fb.sentiment is mock_sentiment
            assert fb.sentiment_confidence == 0.88
            assert ctx["sentiment_used_untranslated_text"] is False

    def test_feedback_api_uses_original_text_when_translation_failed(self):
        fb = _make_feedback(
            message_text="Ninateseka",
            message_text_en="I am suffering",
            language="sw",
        )

        with patch("apps.nlp.pipeline.sentiment_analyser.analyse_sentiment") as mock_analyse:
            mock_sentiment = MagicMock()
            mock_analyse.return_value = (mock_sentiment, 0.73)

            _, _, ctx = analyse_feedback_sentiment(fb, translation_failed=True)

            mock_analyse.assert_called_once_with(
                "Ninateseka",
                language_code="sw",
                translation_failed=True,
            )
            assert ctx["sentiment_used_untranslated_text"] is True

    def test_empty_text_returns_uncertain_confidence(self):
        with patch("apps.nlp.pipeline.sentiment_analyser._lookup_sentiment") as mock_lookup:
            mock_lookup.return_value = MagicMock()
            _, conf = analyse_sentiment("   ")
            assert conf == 0.5
            mock_lookup.assert_called_with("Uncertain")
