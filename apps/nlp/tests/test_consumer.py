"""
Unit tests for the NLP pipeline consumer.

Tests cover:
  - Retry logic with exponential backoff
  - Processing context tracking
  - Component failure handling (graceful degradation)
  - Status lifecycle management
  - Alert creation for high-urgency feedback
"""
from __future__ import annotations

from datetime import timedelta
from unittest import mock

import pytest
from django.utils import timezone

from apps.feedback.models import Feedback, Sentiment, Category, Alert
from apps.nlp.pipeline.consumer import process_feedback, PipelineContext


@pytest.mark.django_db
class TestPipelineConsumer:
    """Test suite for the main consumer orchestrator."""

    @pytest.fixture
    def feedback(self):
        """Create a test feedback record."""
        return Feedback.objects.create(
            message_text="Test message about water shortage",
            channel="SMS",
            status="New",
            submitted_at=timezone.now(),
        )

    @pytest.fixture
    def categories(self):
        """Create test categories."""
        return {
            "wash": Category.objects.create(
                category_name="WASH",
                description="Water, Sanitation, Hygiene",
                is_active=True,
            ),
        }

    def test_already_processed_record_skipped(self, feedback):
        """Already-processed record should be skipped without re-processing."""
        feedback.status = "Processed"
        feedback.processed_at = timezone.now()
        feedback.save()

        with mock.patch(
            "apps.nlp.pipeline.consumer._run_pipeline"
        ) as mock_run:
            process_feedback(feedback.feedback_id)
            mock_run.assert_not_called()

    def test_archived_record_skipped(self, feedback):
        """Archived record should be skipped."""
        feedback.status = "Archived"
        feedback.save()

        with mock.patch(
            "apps.nlp.pipeline.consumer._run_pipeline"
        ) as mock_run:
            process_feedback(feedback.feedback_id)
            mock_run.assert_not_called()

    def test_status_set_to_processing_immediately(self, feedback):
        """Status should be set to 'Processing' before pipeline runs."""
        with mock.patch(
            "apps.nlp.pipeline.consumer._run_pipeline"
        ) as mock_run:
            def side_effect(*args, **kwargs):
                # Check status inside the pipeline
                f = Feedback.objects.get(feedback_id=feedback.feedback_id)
                assert f.status == "Processing"

            mock_run.side_effect = side_effect
            process_feedback(feedback.feedback_id)

    def test_successful_processing_sets_processed_status(self, feedback):
        """Successful processing should set status to 'Processed'."""
        with mock.patch(
            "apps.nlp.pipeline.consumer._run_pipeline"
        ):
            process_feedback(feedback.feedback_id)
            feedback.refresh_from_db()
            assert feedback.status == "Processed"
            assert feedback.processed_at is not None

    def test_all_pipeline_components_called_in_order(self, feedback):
        """C-05 pipeline order: Language → Translation → Topic → Urgency → Sentiment → Location."""
        call_order = []

        def mock_detect(text):
            call_order.append("detect_language")
            return "sw", 0.95  # Non-English to trigger translation

        def mock_translate(text, lang, ctx_dict=None):
            call_order.append("translate")
            return text  # plain string return — handled by consumer

        def mock_classify(text):
            call_order.append("classify_topics")
            return [], {}

        def mock_urgency(_feedback):
            call_order.append("urgency")
            return "Low", "default", {}

        def mock_sentiment(_feedback, translation_failed=False):
            call_order.append("sentiment")
            return None, 0.0, {"sentiment_used_untranslated_text": False}

        def mock_location(text):
            call_order.append("location")
            return None

        with mock.patch(
            "apps.nlp.pipeline.language_detector.detect_language",
            side_effect=mock_detect,
        ), mock.patch(
            "apps.nlp.pipeline.translation_service.translate_to_english",
            side_effect=mock_translate,
        ), mock.patch(
            "apps.nlp.pipeline.topic_classifier.classify_topics",
            side_effect=mock_classify,
        ), mock.patch(
            "apps.nlp.pipeline.urgency_assessor.assess_feedback_urgency",
            side_effect=mock_urgency,
        ), mock.patch(
            "apps.nlp.pipeline.sentiment_analyser.analyse_feedback_sentiment",
            side_effect=mock_sentiment,
        ), mock.patch(
            "apps.nlp.pipeline.location_extractor.extract_location",
            side_effect=mock_location,
        ):
            process_feedback(feedback.feedback_id)

        assert call_order == [
            "detect_language",
            "translate",
            "classify_topics",
            "urgency",
            "sentiment",
            "location",
        ]

    def test_component_failure_propagates_and_leaves_processing(self, feedback):
        """A component raising must propagate and leave the record in 'Processing'.

        Retry scheduling and the terminal 'ProcessingFailed' transition now live
        in the Celery task layer (see apps.nlp.tests.test_tasks), so a single
        consumer run only marks 'Processing' and re-raises.
        """
        with mock.patch(
            "apps.nlp.pipeline.language_detector.detect_language",
            side_effect=ValueError("Model not found"),
        ):
            with pytest.raises(ValueError):
                process_feedback(feedback.feedback_id)

        feedback.refresh_from_db()
        assert feedback.status == "Processing"

    def test_concurrent_location_reply_not_clobbered(self, feedback):
        """A submitter-provided location written mid-pipeline must survive the save.

        The submitter can supply a location via a follow-up SMS/WhatsApp reply,
        which the channel adapter writes straight to the DB after the pipeline has
        already loaded the record. The pipeline must not overwrite it with the
        stale (empty) in-memory value. Here the sentiment stage simulates that
        concurrent reply landing, and location extraction finds nothing.
        """
        assert not feedback.location

        def sentiment_writes_location(_feedback, translation_failed=False):
            # Simulate the location reply arriving while the pipeline runs.
            Feedback.objects.filter(pk=_feedback.pk).update(location="Kakuma")
            return None, 0.0, {"sentiment_used_untranslated_text": False}

        with mock.patch(
            "apps.nlp.pipeline.language_detector.detect_language",
            return_value=("en", 0.95),
        ), mock.patch(
            "apps.nlp.pipeline.translation_service.translate_to_english",
            return_value=("text", {}),
        ), mock.patch(
            "apps.nlp.pipeline.topic_classifier.classify_topics",
            return_value=([], {}),
        ), mock.patch(
            "apps.nlp.pipeline.urgency_assessor.assess_feedback_urgency",
            return_value=("Low", "default", {}),
        ), mock.patch(
            "apps.nlp.pipeline.sentiment_analyser.analyse_feedback_sentiment",
            side_effect=sentiment_writes_location,
        ), mock.patch(
            "apps.nlp.pipeline.location_extractor.extract_location",
            return_value=None,
        ):
            process_feedback(feedback.feedback_id)

        feedback.refresh_from_db()
        assert feedback.status == "Processed"
        assert feedback.location == "Kakuma"

    def test_alert_created_for_high_urgency(self, feedback):
        """High-urgency feedback should trigger auto-alert creation after save."""
        with mock.patch(
            "apps.nlp.pipeline.language_detector.detect_language",
            return_value=("en", 0.95),
        ), mock.patch(
            "apps.nlp.pipeline.translation_service.translate_to_english",
            return_value="emergency! help needed!",
        ), mock.patch(
            "apps.nlp.pipeline.topic_classifier.classify_topics",
            return_value=([], {}),
        ), mock.patch(
            "apps.nlp.pipeline.urgency_assessor.assess_feedback_urgency",
            return_value=("High", "keyword:emergency", {}),
        ), mock.patch(
            "apps.nlp.pipeline.sentiment_analyser.analyse_feedback_sentiment",
            return_value=(None, 0.0, {"sentiment_used_untranslated_text": False}),
        ), mock.patch(
            "apps.nlp.pipeline.location_extractor.extract_location",
            return_value=None,
        ):
            process_feedback(feedback.feedback_id)

        feedback.refresh_from_db()
        assert feedback.status == "Processed"
        alert = Alert.objects.get(feedback=feedback)
        assert alert.priority_level == "High"
        assert "emergency" in alert.description.lower()

    def test_no_alert_for_low_urgency(self, feedback):
        """Low-urgency feedback should not create an alert."""
        with mock.patch(
            "apps.nlp.pipeline.language_detector.detect_language",
            return_value=("en", 0.95),
        ), mock.patch(
            "apps.nlp.pipeline.translation_service.translate_to_english",
            return_value=("text", {}),
        ), mock.patch(
            "apps.nlp.pipeline.topic_classifier.classify_topics",
            return_value=([], {}),
        ), mock.patch(
            "apps.nlp.pipeline.urgency_assessor.assess_feedback_urgency",
            return_value=("Low", "default", {}),
        ), mock.patch(
            "apps.nlp.pipeline.sentiment_analyser.analyse_feedback_sentiment",
            return_value=(None, 0.0, {"sentiment_used_untranslated_text": False}),
        ), mock.patch(
            "apps.nlp.pipeline.location_extractor.extract_location",
            return_value=("Location", 0.9, "settlement"),
        ):
            process_feedback(feedback.feedback_id)

        assert not Alert.objects.filter(feedback=feedback).exists()

    def test_low_confidence_swahili_still_translates(self, feedback):
        """Swahili should be translated even below the generic confidence threshold."""
        with mock.patch(
            "apps.nlp.pipeline.language_detector.detect_language",
            return_value=("sw", 0.30),
        ), mock.patch(
            "apps.nlp.pipeline.translation_service.translate_to_english",
            return_value=("Translated Swahili text", {}),
        ) as mock_translate, mock.patch(
            "apps.nlp.pipeline.topic_classifier.classify_topics",
            return_value=([], {}),
        ), mock.patch(
            "apps.nlp.pipeline.urgency_assessor.assess_feedback_urgency",
            return_value=("Low", "default", {}),
        ), mock.patch(
            "apps.nlp.pipeline.sentiment_analyser.analyse_feedback_sentiment",
            return_value=(None, 0.0, {"sentiment_used_untranslated_text": False}),
        ), mock.patch(
            "apps.nlp.pipeline.location_extractor.extract_location",
            return_value=None,
        ):
            process_feedback(feedback.feedback_id)

        feedback.refresh_from_db()
        assert feedback.status == "Processed"
        assert feedback.message_text_en == "Translated Swahili text"
        mock_translate.assert_called_once()

    def test_low_confidence_non_swahili_skips_translation(self, feedback):
        """Non-whitelisted low-confidence language should skip translation."""
        feedback.message_text = "Habari yako"
        feedback.save(update_fields=["message_text"])

        with mock.patch(
            "apps.nlp.pipeline.language_detector.detect_language",
            return_value=("fr", 0.30),
        ), mock.patch(
            "apps.nlp.pipeline.translation_service.translate_to_english",
        ) as mock_translate, mock.patch(
            "apps.nlp.pipeline.topic_classifier.classify_topics",
            return_value=([], {}),
        ), mock.patch(
            "apps.nlp.pipeline.urgency_assessor.assess_feedback_urgency",
            return_value=("Low", "default", {}),
        ), mock.patch(
            "apps.nlp.pipeline.sentiment_analyser.analyse_feedback_sentiment",
            return_value=(None, 0.0, {"sentiment_used_untranslated_text": False}),
        ), mock.patch(
            "apps.nlp.pipeline.location_extractor.extract_location",
            return_value=None,
        ):
            process_feedback(feedback.feedback_id)

        feedback.refresh_from_db()
        assert feedback.status == "Processed"
        assert feedback.message_text_en == "Habari yako"
        mock_translate.assert_not_called()

    def test_nonexistent_feedback_handled_gracefully(self):
        """Nonexistent feedback should be logged and skipped."""
        with mock.patch(
            "apps.nlp.pipeline.consumer._run_pipeline"
        ) as mock_run:
            process_feedback(99999)  # Nonexistent ID
            mock_run.assert_not_called()


@pytest.mark.django_db
class TestPipelineContext:
    """Test suite for PipelineContext."""

    def test_context_tracks_review_flags(self):
        """Context should track review flags."""
        ctx = PipelineContext(feedback_id=1)
        ctx.set_review_flag("needs_lang_review")
        ctx.set_review_flag("needs_category_review")

        assert ctx.review_flags["needs_lang_review"] is True
        assert ctx.review_flags["needs_category_review"] is True

    def test_context_translation_failed_flag(self):
        """Context should track translation failures."""
        ctx = PipelineContext(feedback_id=1)
        assert ctx.translation_failed is False
        ctx.translation_failed = True
        assert ctx.translation_failed is True

    def test_context_urgency_rule_stored(self):
        """Context should store the urgency rule matched by UrgencyAssessor."""
        ctx = PipelineContext(feedback_id=42)
        assert ctx.urgency_rule is None
        ctx.urgency_rule = "keyword:emergency"
        assert ctx.urgency_rule == "keyword:emergency"
