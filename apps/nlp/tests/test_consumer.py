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

    def test_component_failure_causes_processing_failed(self, feedback):
        """Any component raising must propagate, retry, and ultimately produce ProcessingFailed."""
        with mock.patch(
            "apps.nlp.pipeline.language_detector.detect_language",
            side_effect=ValueError("Model not found"),
        ), mock.patch(
            "apps.nlp.pipeline.consumer.time.sleep"
        ), mock.patch(
            "apps.nlp.pipeline.alert_manager.AlertManager.dispatch"
        ) as mock_alert:
            with pytest.raises(ValueError):
                process_feedback(feedback.feedback_id)

        feedback.refresh_from_db()
        assert feedback.status == "ProcessingFailed"
        # AlertManager must be notified on terminal failure
        mock_alert.assert_called_once()

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

    def test_retry_logic_with_exponential_backoff(self, feedback):
        """Failed attempts should retry with correct delays (30s, 120s, 300s)."""
        attempt_count = [0]
        delays_recorded = []

        def mock_run_pipeline(f, ctx):
            attempt_count[0] += 1
            if attempt_count[0] < 3:
                raise ValueError(f"Simulated failure {attempt_count[0]}")

        with mock.patch(
            "apps.nlp.pipeline.consumer._run_pipeline",
            side_effect=mock_run_pipeline,
        ), mock.patch(
            "apps.nlp.pipeline.consumer.time.sleep",
            side_effect=lambda delay: delays_recorded.append(delay),
        ):
            process_feedback(feedback.feedback_id)

        # Should have retried twice with correct delays
        assert delays_recorded == [30, 120]
        # Final status should be Processed (success on 3rd attempt)
        feedback.refresh_from_db()
        assert feedback.status == "Processed"

    def test_final_failure_after_3_retries(self, feedback):
        """After 3 failed attempts, status should be ProcessingFailed."""
        with mock.patch(
            "apps.nlp.pipeline.consumer._run_pipeline",
            side_effect=ValueError("Persistent failure"),
        ), mock.patch(
            "apps.nlp.pipeline.consumer.time.sleep"
        ):
            with pytest.raises(ValueError):
                process_feedback(feedback.feedback_id)

        feedback.refresh_from_db()
        assert feedback.status == "ProcessingFailed"

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
