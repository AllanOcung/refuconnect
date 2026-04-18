from __future__ import annotations

import logging
import time
import traceback
from datetime import datetime, timezone

from .language_detector import LanguageDetector
from .location_extractor import LocationExtractor
from .sentiment_analyser import SentimentAnalyser
from .topic_classifier import TopicClassifier
from .translation_service import TranslationService
from .urgency_assessor import UrgencyAssessor

from apps.feedback.models import Feedback


logger = logging.getLogger(__name__)

_RETRY_DELAYS: list[int] = [30, 120, 300]
_MAX_RETRIES: int = 3
_TERMINAL_STATUSES: frozenset[str] = frozenset({"Processed", "Archived"})


class PipelineConsumer:

    def __init__(self) -> None:
        self._language_detector   = LanguageDetector()
        self._translation_service = TranslationService()
        self._topic_classifier    = TopicClassifier()
        self._urgency_assessor    = UrgencyAssessor()
        self._sentiment_analyser  = SentimentAnalyser()
        self._location_extractor  = LocationExtractor()

    def run(self, feedback_id: int) -> None:
        

        try:
            record = Feedback.objects.get(pk=feedback_id)
        except Feedback.DoesNotExist:
            logger.error("feedback_id=%s: record not found; aborting.", feedback_id)
            return

        if record.status in _TERMINAL_STATUSES:
            logger.info(
                "feedback_id=%s: status is '%s'; skipping.", feedback_id, record.status
            )
            return

        last_exc: Exception | None = None
        
        # Design note: per-step exceptions are caught inside _execute_pipeline and do NOT
        # propagate (graceful degradation per spec C-15). The retry loop here handles
        # failures that occur OUTSIDE the step loop (e.g. DB save, record fetch).
        # This satisfies both "partial failure continues pipeline" and "retry 3 times on failure".

        for attempt in range(1, _MAX_RETRIES + 1):
            try:
                self._execute_pipeline(record)
                return
            except Exception as exc:
                last_exc = exc
                logger.error(
                    "feedback_id=%s: attempt %d/%d failed: %s\n%s",
                    feedback_id,
                    attempt,
                    _MAX_RETRIES,
                    exc,
                    traceback.format_exc(),
                )
                if attempt < _MAX_RETRIES:
                    delay = _RETRY_DELAYS[attempt - 1]
                    logger.info("feedback_id=%s: retrying in %ds.", feedback_id, delay)
                    time.sleep(delay)

        self._mark_failed(record, last_exc)

    def _execute_pipeline(self, record) -> None:
        feedback_id = record.pk

        record.status = "Processing"
        record.save(update_fields=["status"])

        logger.info("feedback_id=%s: pipeline started.", feedback_id)

        context: dict = {}

        steps = [
            ("LanguageDetector",   self._language_detector),
            ("TranslationService", self._translation_service),
            ("TopicClassifier",    self._topic_classifier),
            ("UrgencyAssessor",    self._urgency_assessor),
            ("SentimentAnalyser",  self._sentiment_analyser),
            ("LocationExtractor",  self._location_extractor),
        ]

        for step_name, component in steps:
            try:
                record, context = component.process(record, context)
                logger.debug("feedback_id=%s: %s completed.", feedback_id, step_name)
            except Exception as exc:
                logger.error(
                    "feedback_id=%s: %s failed (continuing): %s\n%s",
                    feedback_id,
                    step_name,
                    exc,
                    traceback.format_exc(),
                )
                context[f"{step_name.lower()}_failed"] = True
                context["needs_manual_review"] = True

        record.status = "Processed"
        record.processed_at = datetime.now(tz=timezone.utc)
        record.save()
        logger.info("feedback_id=%s: pipeline completed.", feedback_id)

        if record.urgency_level == "High":
            self._dispatch_alert(record, context)

    def _mark_failed(self, record, exc: Exception | None) -> None:
        feedback_id = record.pk
        try:
            record.status = "ProcessingFailed"
            record.save(update_fields=["status"])
        except Exception as save_exc:
            logger.critical(
                "feedback_id=%s: could not persist ProcessingFailed status: %s",
                feedback_id,
                save_exc,
            )
        logger.critical(
            "feedback_id=%s: all %d retries exhausted. final error: %s",
            feedback_id,
            _MAX_RETRIES,
            exc,
        )
        self._notify_failure(feedback_id)

    def _dispatch_alert(self, record, context: dict) -> None:
        from apps.alerts.services import AlertManager
        try:
            

            AlertManager.dispatch(record)
            logger.info(
                "feedback_id=%s: AlertManager.dispatch called (urgency_rule=%s).",
                record.pk,
                context.get("urgency_rule", "unknown"),
            )
        except Exception as exc:
            logger.error(
                "feedback_id=%s: AlertManager.dispatch failed: %s",
                record.pk,
                exc,
                exc_info=True,
            )

    def _notify_failure(self, feedback_id: int) -> None:
        from apps.alerts.services import AlertManager
        try:
            

            AlertManager.notify_processing_failure(feedback_id)
        except Exception as exc:
            logger.error(
                "feedback_id=%s: AlertManager failure notification failed: %s",
                feedback_id,
                exc,
            )
