"""
apps/nlp/tests/test_language_detector.py
"""
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase


def _make_record(**kwargs):
    record = MagicMock()
    record.pk = kwargs.get("id", 1)
    record.id = kwargs.get("id", 1)
    record.language = kwargs.get("language", None)
    record.language_confidence = kwargs.get("language_confidence", None)
    record.channel = kwargs.get("channel", "SMS")
    record.message_text = kwargs.get("message_text", "Hello this is a test message")
    return record


FASTTEXT_PATH = "apps.nlp.pipeline.language_detector.fasttext"
ISFILE_PATH = "apps.nlp.pipeline.language_detector.os.path.isfile"


@patch(FASTTEXT_PATH)
class LanguageDetectorTests(SimpleTestCase):

    def _get_detector(self, mock_fasttext):
        """Return a fresh LanguageDetector with a mocked model."""
        from apps.nlp.pipeline.language_detector import LanguageDetector

        LanguageDetector._model = None  # reset singleton between tests
        mock_model = MagicMock()
        mock_fasttext.load_model.return_value = mock_model

        # Patch isfile so the model-path guard passes, and provide a fake path
        with patch(ISFILE_PATH, return_value=True), \
             patch("django.conf.settings.FASTTEXT_MODEL_PATH", "/fake/model.bin", create=True):
            detector = LanguageDetector()

        return detector, mock_model

    def test_short_text_sets_language_unknown(self, mock_fasttext):
        detector, mock_model = self._get_detector(mock_fasttext)
        record = _make_record(message_text="Hi")
        context = {}
        detector.process(record, context)
        self.assertEqual(record.language, "unknown")
        self.assertEqual(record.language_confidence, 0.50)
        self.assertTrue(context.get("needs_lang_review"))
        mock_model.predict.assert_not_called()

    def test_ussd_language_hint_trusted_without_model(self, mock_fasttext):
        detector, mock_model = self._get_detector(mock_fasttext)
        record = _make_record(language="lg", channel="USSD")
        context = {}
        detector.process(record, context)
        self.assertEqual(record.language_confidence, 1.0)
        mock_model.predict.assert_not_called()

    def test_unsupported_language_mapped_to_other(self, mock_fasttext):
        detector, mock_model = self._get_detector(mock_fasttext)
        mock_model.predict.return_value = (["__label__xyz"], [0.95])
        record = _make_record(message_text="Some long enough message here")
        context = {}
        detector.process(record, context)
        self.assertEqual(record.language, "other")

    def test_low_confidence_sets_needs_lang_review(self, mock_fasttext):
        detector, mock_model = self._get_detector(mock_fasttext)
        mock_model.predict.return_value = (["__label__en"], [0.75])
        record = _make_record(message_text="Some long enough message here")
        context = {}
        detector.process(record, context)
        self.assertTrue(context.get("needs_lang_review"))
        self.assertEqual(record.language, "en")

    def test_model_loaded_once_not_per_call(self, mock_fasttext):
        from apps.nlp.pipeline.language_detector import LanguageDetector

        LanguageDetector._model = None
        mock_fasttext.load_model.return_value = MagicMock()
        mock_fasttext.load_model.return_value.predict.return_value = (
            ["__label__en"], [0.98]
        )

        with patch(ISFILE_PATH, return_value=True), \
             patch("django.conf.settings.FASTTEXT_MODEL_PATH", "/fake/model.bin", create=True):
            d = LanguageDetector()
            # Create second instance — should reuse singleton, not reload
            LanguageDetector()

        d.process(_make_record(), {})
        d.process(_make_record(), {})
        self.assertEqual(mock_fasttext.load_model.call_count, 1)

    def test_supported_language_set_correctly(self, mock_fasttext):
        detector, mock_model = self._get_detector(mock_fasttext)
        mock_model.predict.return_value = (["__label__sw"], [0.97])
        record = _make_record(message_text="Habari za asubuhi hii nzuri sana")
        context = {}
        detector.process(record, context)
        self.assertEqual(record.language, "sw")
        self.assertAlmostEqual(record.language_confidence, 0.97, places=2)