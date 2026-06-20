"""
Unit tests for the NLP Celery task layer (apps.nlp.tasks).

Retry scheduling and the terminal 'ProcessingFailed' transition were moved out
of the synchronous consumer (which used a blocking ``time.sleep`` that froze the
worker) and into the Celery task, which reschedules non-blockingly via
``self.retry``. These tests verify that wiring:

  - a failure below the retry ceiling schedules a retry with the right back-off
    and does NOT mark the record failed;
  - once retries are exhausted the record is marked 'ProcessingFailed' and ops
    are alerted;
  - the ``_mark_processing_failed`` helper behaves on its own.
"""
from __future__ import annotations

from unittest import mock

import pytest
from celery.exceptions import Retry
from django.utils import timezone

from apps.feedback.models import Alert, Feedback
from apps.nlp.tasks import _mark_processing_failed, process_feedback_nlp


@pytest.mark.django_db
class TestProcessFeedbackNlpTask:
    @pytest.fixture
    def feedback(self):
        return Feedback.objects.create(
            message_text="Test message",
            channel="SMS",
            status="Processing",
            submitted_at=timezone.now(),
        )

    def test_success_invokes_pipeline_once(self, feedback):
        with mock.patch(
            "apps.nlp.pipeline.consumer.process_feedback"
        ) as mock_proc:
            process_feedback_nlp.apply(args=[feedback.feedback_id])
            mock_proc.assert_called_once_with(feedback.feedback_id)

    def test_failure_below_max_schedules_retry_with_backoff(self, feedback):
        """First failure reschedules with the 30s back-off; no terminal marking.

        ``self.retry`` is stubbed to raise ``Retry`` (its real signalling
        exception) so the test asserts the back-off wiring in a single execution
        without depending on eager re-run semantics. With
        CELERY_TASK_EAGER_PROPAGATES the Retry surfaces out of ``apply``.
        """
        with mock.patch(
            "apps.nlp.pipeline.consumer.process_feedback",
            side_effect=ValueError("boom"),
        ), mock.patch.object(
            process_feedback_nlp, "retry", side_effect=Retry("retry")
        ) as mock_retry:
            with pytest.raises(Retry):
                process_feedback_nlp.apply(
                    args=[feedback.feedback_id], retries=0, throw=True
                )

        assert mock_retry.call_args.kwargs.get("countdown") == 30
        feedback.refresh_from_db()
        assert feedback.status != "ProcessingFailed"
        assert not Alert.objects.filter(feedback=feedback).exists()

    def test_retries_exhausted_marks_processing_failed(self, feedback):
        """When retries are spent, the record is marked failed and ops alerted."""
        with mock.patch(
            "apps.nlp.pipeline.consumer.process_feedback",
            side_effect=ValueError("boom"),
        ):
            # retries == max_retries (3): the task should not retry again.
            process_feedback_nlp.apply(args=[feedback.feedback_id], retries=3)

        feedback.refresh_from_db()
        assert feedback.status == "ProcessingFailed"
        assert Alert.objects.filter(feedback=feedback).exists()

    def test_mark_processing_failed_helper(self, feedback):
        _mark_processing_failed(feedback.feedback_id)

        feedback.refresh_from_db()
        assert feedback.status == "ProcessingFailed"
        assert Alert.objects.filter(feedback=feedback).exists()

    def test_mark_processing_failed_missing_record_is_safe(self):
        # Should not raise for a nonexistent feedback_id.
        _mark_processing_failed(999999)
