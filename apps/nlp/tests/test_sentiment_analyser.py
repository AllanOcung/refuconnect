"""
apps/nlp/tests/test_sentiment_analyser.py
"""
from unittest.mock import MagicMock, patch

from django.test import TestCase

HF_PIPELINE = "apps.nlp.pipeline.sentiment_analyser.hf_pipeline"
VADER_PATH = "apps.nlp.pipeline.sentiment_analyser.SentimentIntensityAnalyzer"


def _make_record(language="en", message_text_en="Test message", sentiment_id=None):
    r = MagicMock()
    r.id = 1
    r.language = language
    r.message_text_en = message_text_en
    r.message_text = message_text_en
    r.sentiment_id = sentiment_id
    r.sentiment_confidence = None
    return r


@patch(HF_PIPELINE)
@patch(VADER_PATH)
class SentimentAnalyserTests(TestCase):

    def _get_analyser(self, mock_vader_cls, mock_hf):
        from apps.nlp.pipeline.sentiment_analyser import SentimentAnalyser
        SentimentAnalyser._vader = None
        SentimentAnalyser._xlm = None
        mock_hf.return_value = MagicMock()
        analyser = SentimentAnalyser()
        return analyser, mock_vader_cls.return_value, mock_hf.return_value

    @patch("apps.nlp.pipeline.sentiment_analyser.SentimentAnalyser._get_sentiment_obj")
    def test_positive_vader_compound_maps_to_positive(self, mock_sentiment, mock_vader_cls, mock_hf):
        analyser, mock_vader, _ = self._get_analyser(mock_vader_cls, mock_hf)
        mock_vader.polarity_scores.return_value = {"compound": 0.65, "pos": 0.7, "neu": 0.2, "neg": 0.1}
        mock_sentiment.return_value = MagicMock(pk=1)
        record = _make_record()
        analyser.process(record, {})
        mock_sentiment.assert_called_with("Positive")

    @patch("apps.nlp.pipeline.sentiment_analyser.SentimentAnalyser._get_sentiment_obj")
    def test_negative_vader_compound_maps_to_negative(self, mock_sentiment, mock_vader_cls, mock_hf):
        analyser, mock_vader, _ = self._get_analyser(mock_vader_cls, mock_hf)
        mock_vader.polarity_scores.return_value = {"compound": -0.55, "pos": 0.05, "neu": 0.3, "neg": 0.65}
        mock_sentiment.return_value = MagicMock(pk=2)
        record = _make_record()
        analyser.process(record, {})
        mock_sentiment.assert_called_with("Negative")

    @patch("apps.nlp.pipeline.sentiment_analyser.SentimentAnalyser._get_sentiment_obj")
    def test_neutral_compound_maps_to_neutral(self, mock_sentiment, mock_vader_cls, mock_hf):
        analyser, mock_vader, _ = self._get_analyser(mock_vader_cls, mock_hf)
        mock_vader.polarity_scores.return_value = {"compound": 0.01, "pos": 0.3, "neu": 0.6, "neg": 0.1}
        mock_sentiment.return_value = MagicMock(pk=3)
        record = _make_record()
        analyser.process(record, {})
        mock_sentiment.assert_called_with("Neutral")

    @patch("apps.nlp.pipeline.sentiment_analyser.SentimentAnalyser._get_sentiment_obj")
    def test_low_confidence_maps_to_uncertain(self, mock_sentiment, mock_vader_cls, mock_hf):
        analyser, mock_vader, _ = self._get_analyser(mock_vader_cls, mock_hf)
        # max(pos,neu,neg) < 0.60
        mock_vader.polarity_scores.return_value = {"compound": 0.10, "pos": 0.4, "neu": 0.4, "neg": 0.2}
        mock_sentiment.return_value = MagicMock(pk=4)
        record = _make_record()
        analyser.process(record, {})
        mock_sentiment.assert_called_with("Uncertain")

    @patch("apps.nlp.pipeline.sentiment_analyser.SentimentAnalyser._get_sentiment_obj")
    def test_correct_sentiment_fk_set_on_record(self, mock_sentiment, mock_vader_cls, mock_hf):
        analyser, mock_vader, _ = self._get_analyser(mock_vader_cls, mock_hf)
        mock_vader.polarity_scores.return_value = {"compound": 0.8, "pos": 0.9, "neu": 0.05, "neg": 0.05}
        sentiment_obj = MagicMock(pk=99)
        mock_sentiment.return_value = sentiment_obj
        record = _make_record()
        analyser.process(record, {})
        self.assertEqual(record.sentiment_id, 99)
