"""
apps/nlp/tests/test_translation_service.py
"""
from unittest.mock import MagicMock, call, patch

from django.test import SimpleTestCase


def _make_record(language="sw", message_text="Habari hii ni muhimu sana", message_text_en=None):
    r = MagicMock()
    r.id = 42
    r.language = language
    r.message_text = message_text
    r.message_text_en = message_text_en
    return r


GOOGLE_PATH = "apps.nlp.pipeline.translation_service._translate_google"
AZURE_PATH = "apps.nlp.pipeline.translation_service._translate_azure"
CACHE_PATH = "apps.nlp.pipeline.translation_service._get_redis"


class TranslationServiceTests(SimpleTestCase):

    def _get_service(self):
        from apps.nlp.pipeline.translation_service import TranslationService
        return TranslationService()

    def _mock_cache(self, mock_get_redis, cached_value=None):
        cache = MagicMock()
        cache.get.return_value = cached_value
        mock_get_redis.return_value = cache
        return cache

    @patch(CACHE_PATH)
    def test_english_text_not_sent_to_api(self, mock_get_redis):
        cache = self._mock_cache(mock_get_redis)
        svc = self._get_service()
        record = _make_record(language="en", message_text="Hello world")
        svc.process(record, {})
        self.assertEqual(record.message_text_en, "Hello world")
        cache.get.assert_not_called()

    @patch(GOOGLE_PATH)
    @patch(CACHE_PATH)
    def test_cache_hit_returns_without_api_call(self, mock_get_redis, mock_google):
        self._mock_cache(mock_get_redis, cached_value="Cached translation")
        svc = self._get_service()
        record = _make_record()
        svc.process(record, {})
        self.assertEqual(record.message_text_en, "Cached translation")
        mock_google.assert_not_called()

    @patch(AZURE_PATH)
    @patch(GOOGLE_PATH)
    @patch(CACHE_PATH)
    def test_google_failure_falls_through_to_azure(
        self, mock_get_redis, mock_google, mock_azure
    ):
        self._mock_cache(mock_get_redis)
        mock_google.side_effect = Exception("quota exceeded")
        mock_azure.return_value = "Azure translation"
        svc = self._get_service()
        record = _make_record()
        svc.process(record, {})
        self.assertEqual(record.message_text_en, "Azure translation")

    @patch(AZURE_PATH)
    @patch(GOOGLE_PATH)
    @patch(CACHE_PATH)
    def test_both_apis_failing_sets_translation_failed(
        self, mock_get_redis, mock_google, mock_azure
    ):
        self._mock_cache(mock_get_redis)
        mock_google.side_effect = Exception("Google down")
        mock_azure.side_effect = Exception("Azure down")
        svc = self._get_service()
        record = _make_record(message_text="Original text")
        context = {}
        svc.process(record, context)
        self.assertTrue(context.get("translation_failed"))
        self.assertEqual(record.message_text_en, "Original text")

    @patch(GOOGLE_PATH)
    @patch(CACHE_PATH)
    def test_successful_translation_is_cached(self, mock_get_redis, mock_google):
        cache = self._mock_cache(mock_get_redis)
        mock_google.return_value = "Translated text"
        svc = self._get_service()
        record = _make_record()
        svc.process(record, {})
        cache.set.assert_called_once()
        args = cache.set.call_args[0]
        self.assertEqual(args[1], "Translated text")

    @patch(GOOGLE_PATH)
    @patch(CACHE_PATH)
    def test_text_over_5000_chars_is_truncated(self, mock_get_redis, mock_google):
        self._mock_cache(mock_get_redis)
        mock_google.return_value = "Truncated translation"
        svc = self._get_service()
        long_text = "x" * 6000
        record = _make_record(message_text=long_text)
        svc.process(record, {})
        actual_text_sent = mock_google.call_args[0][0]
        self.assertEqual(len(actual_text_sent), 5000)
