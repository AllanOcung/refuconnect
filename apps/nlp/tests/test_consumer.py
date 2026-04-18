"""
apps/nlp/tests/test_consumer.py
"""
from unittest.mock import MagicMock, call, patch

from django.test import TestCase

CONSUMER_MODULE = "apps.nlp.pipeline.consumer"


def _make_record(pk=1, status="New", urgency_level="Low", sentiment_id=None):
    r = MagicMock()
    r.pk = pk
    r.id = pk
    r.status = status
    r.urgency_level = urgency_level
    r.sentiment_id = sentiment_id
    r.save = MagicMock()
    return r


def _patch_components():
    return {
        "LanguageDetector":   patch(f"{CONSUMER_MODULE}.LanguageDetector"),
        "TranslationService": patch(f"{CONSUMER_MODULE}.TranslationService"),
        "TopicClassifier":    patch(f"{CONSUMER_MODULE}.TopicClassifier"),
        "UrgencyAssessor":    patch(f"{CONSUMER_MODULE}.UrgencyAssessor"),
        "SentimentAnalyser":  patch(f"{CONSUMER_MODULE}.SentimentAnalyser"),
        "LocationExtractor":  patch(f"{CONSUMER_MODULE}.LocationExtractor"),
    }


class _ComponentPatchCtx:
    """Context manager that starts/stops all 6 component patches."""

    def __init__(self):
        self._patches = _patch_components()
        self.mocks: dict = {}

    def __enter__(self):
        for name, p in self._patches.items():
            self.mocks[name] = p.start()
            self.mocks[name].return_value.process.side_effect = lambda r, c: (r, c)
        return self.mocks

    def __exit__(self, *args):
        for p in self._patches.values():
            p.stop()


class PipelineConsumerTests(TestCase):

    @patch(f"{CONSUMER_MODULE}.Feedback", create=True)
    def test_already_processed_record_is_skipped(self, mock_feedback_cls):
        from apps.nlp.pipeline.consumer import PipelineConsumer

        record = _make_record(status="Processed")
        mock_feedback_cls.objects.get.return_value = record

        with _ComponentPatchCtx():
            consumer = PipelineConsumer()
            consumer.run(1)

        record.save.assert_not_called()

    @patch(f"{CONSUMER_MODULE}.Feedback", create=True)
    def test_status_set_to_processing_immediately(self, mock_feedback_cls):
        from apps.nlp.pipeline.consumer import PipelineConsumer

        record = _make_record(status="New")
        mock_feedback_cls.objects.get.return_value = record

        with _ComponentPatchCtx():
            consumer = PipelineConsumer()
            consumer.run(1)

        self.assertEqual(record.status, "Processed")

    @patch(f"{CONSUMER_MODULE}.Feedback", create=True)
    def test_all_components_called_in_order(self, mock_feedback_cls):
        from apps.nlp.pipeline.consumer import PipelineConsumer

        record = _make_record()
        mock_feedback_cls.objects.get.return_value = record
        call_order = []

        def track(name):
            def process(r, c):
                call_order.append(name)
                return r, c
            return process

        with _ComponentPatchCtx() as mocks:
            mocks["LanguageDetector"].return_value.process.side_effect = track("language")
            mocks["TranslationService"].return_value.process.side_effect = track("translation")
            mocks["TopicClassifier"].return_value.process.side_effect = track("topic")
            mocks["UrgencyAssessor"].return_value.process.side_effect = track("urgency")
            mocks["SentimentAnalyser"].return_value.process.side_effect = track("sentiment")
            mocks["LocationExtractor"].return_value.process.side_effect = track("location")
            consumer = PipelineConsumer()
            consumer.run(1)

        self.assertEqual(
            call_order,
            ["language", "translation", "topic", "urgency", "sentiment", "location"],
        )

    @patch(f"{CONSUMER_MODULE}.Feedback", create=True)
    def test_status_set_to_processed_on_success(self, mock_feedback_cls):
        from apps.nlp.pipeline.consumer import PipelineConsumer

        record = _make_record()
        mock_feedback_cls.objects.get.return_value = record

        with _ComponentPatchCtx():
            consumer = PipelineConsumer()
            consumer.run(1)

        self.assertEqual(record.status, "Processed")

    @patch(f"{CONSUMER_MODULE}.PipelineConsumer._dispatch_alert")
    @patch(f"{CONSUMER_MODULE}.Feedback", create=True)
    def test_alert_manager_called_if_urgency_high(self, mock_feedback_cls, mock_dispatch):
        from apps.nlp.pipeline.consumer import PipelineConsumer

        record = _make_record(urgency_level="High")
        mock_feedback_cls.objects.get.return_value = record

        with _ComponentPatchCtx():
            consumer = PipelineConsumer()
            consumer.run(1)

        mock_dispatch.assert_called_once()

    @patch(f"{CONSUMER_MODULE}.PipelineConsumer._mark_failed")
    @patch(f"{CONSUMER_MODULE}.Feedback", create=True)
    def test_status_processing_failed_after_3_failures(self, mock_feedback_cls, mock_mark):
        from apps.nlp.pipeline.consumer import PipelineConsumer

        record = _make_record()
        # Make record.save() raise so _execute_pipeline propagates the exception
        # through all 3 retry attempts, triggering _mark_failed
        record.save.side_effect = Exception("DB save failed")
        mock_feedback_cls.objects.get.return_value = record

        with _ComponentPatchCtx():
            consumer = PipelineConsumer()
            with patch(f"{CONSUMER_MODULE}.time.sleep"):
                consumer.run(1)

        mock_mark.assert_called_once()

    @patch(f"{CONSUMER_MODULE}.Feedback", create=True)
    def test_partial_failure_continues_pipeline(self, mock_feedback_cls):
        """A component failure should not stop subsequent components from running."""
        from apps.nlp.pipeline.consumer import PipelineConsumer

        record = _make_record()
        mock_feedback_cls.objects.get.return_value = record
        ran = []

        with _ComponentPatchCtx() as mocks:
            mocks["LanguageDetector"].return_value.process.side_effect = Exception("lang fail")
            mocks["TranslationService"].return_value.process.side_effect = (
                lambda r, c: (ran.append("translation") or (r, c))
            )
            mocks["TopicClassifier"].return_value.process.side_effect = (
                lambda r, c: (ran.append("topic") or (r, c))
            )
            mocks["UrgencyAssessor"].return_value.process.side_effect = lambda r, c: (r, c)
            mocks["SentimentAnalyser"].return_value.process.side_effect = lambda r, c: (r, c)
            mocks["LocationExtractor"].return_value.process.side_effect = lambda r, c: (r, c)
            consumer = PipelineConsumer()
            consumer.run(1)

        self.assertIn("translation", ran)
        self.assertIn("topic", ran)
        self.assertEqual(record.status, "Processed")