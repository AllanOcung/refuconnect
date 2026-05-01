"""
Main NLP pipeline consumer.

Orchestrates all NLP stages for a single Feedback record in the exact sequence
mandated by C-05:

  1.  Set status='Processing' and save (duplicate-processing guard)
  2.  LanguageDetector
  3.  TranslationService
  4.  TopicClassifier
  5.  UrgencyAssessor
  6.  SentimentAnalyser
  7.  LocationExtractor
  8.  Set status='Processed', processed_at=now(), save
  9.  If urgency_level='High' → AlertManager.dispatch(record)

Retry policy
------------
If any pipeline component raises an exception the whole pipeline is retried up
to 3 times with exponential back-off (30 s, 120 s, 300 s).  After all attempts
are exhausted the record is marked 'ProcessingFailed' and AlertManager is
notified so operations staff can investigate.

Constraints (C-05)
------------------
* This module never imports Celery.  It is called *by* the Celery task in
  tasks.py but has no Celery dependency itself.
* Every caught exception is logged with the full traceback and the feedback_id.
* Records already in status='Processed' are silently skipped (idempotency guard).
"""
from __future__ import annotations

import logging
import time

from django.db import transaction
from django.utils import timezone

logger = logging.getLogger(__name__)

# Retry back-off delays in seconds: attempt 1→2 waits 30 s, 2→3 waits 120 s.
_RETRY_DELAYS = [30, 120, 300]


class PipelineContext:
    """
    Lightweight value object threaded through the pipeline stages.

    Tracks per-run state that individual stages need to communicate to the
    controller (translation outcome, urgency rule matched, review flags).
    """

    def __init__(self, feedback_id: int) -> None:
        self.feedback_id = feedback_id
        self.review_flags: dict[str, bool] = {}
        self.translation_failed: bool = False
        self.urgency_rule: str | None = None

    def set_review_flag(self, flag_name: str) -> None:
        self.review_flags[flag_name] = True

    def log_context(self) -> None:
        if self.review_flags:
            logger.info(
                "feedback_id=%d review flags: %s",
                self.feedback_id,
                list(self.review_flags.keys()),
            )


def process_feedback(feedback_id: int) -> None:
    """
    Entry point called by the Celery task in tasks.py.

    Fetches the Feedback record, marks it Processing, then runs the pipeline
    with retry logic.  On success → 'Processed'.  After all retries fail →
    'ProcessingFailed' + AlertManager notification.
    """
    from apps.feedback.models import Feedback
    from apps.nlp.pipeline.alert_manager import AlertManager

    # ── Guard + status='Processing' (atomic, row-locked) ─────────────────────
    try:
        with transaction.atomic():
            try:
                feedback = Feedback.objects.select_for_update().get(
                    feedback_id=feedback_id
                )
            except Feedback.DoesNotExist:
                logger.error(
                    "process_feedback: Feedback feedback_id=%d not found — skipping.",
                    feedback_id,
                )
                return

            if feedback.status in ("Processed", "Archived"):
                logger.info(
                    "process_feedback: feedback_id=%d already '%s' — skipping.",
                    feedback_id,
                    feedback.status,
                )
                return

            # Step 1 — mark Processing immediately so a crashed/retried worker
            # does not pick up the same record again.
            feedback.status = "Processing"
            feedback.save(update_fields=["status"])
        # Row lock released; heavy ML work runs outside the transaction.
    except Exception:
        logger.exception(
            "process_feedback: failed to acquire lock for feedback_id=%d.",
            feedback_id,
        )
        raise

    context = PipelineContext(feedback_id)
    max_attempts = len(_RETRY_DELAYS) + 1  # 3 attempts total

    for attempt in range(1, max_attempts + 1):
        try:
            _run_pipeline(feedback, context)

            # Step 8 — persist enriched record
            feedback.status = "Processed"
            feedback.processed_at = timezone.now()
            feedback.save()
            context.log_context()
            logger.info(
                "process_feedback: feedback_id=%d processed successfully (attempt %d/%d).",
                feedback_id,
                attempt,
                max_attempts,
            )

            # Step 9 — alert if high-urgency (runs after successful save)
            if feedback.urgency_level == "High":
                AlertManager.dispatch(feedback, context.urgency_rule)

            return

        except Exception:
            logger.exception(
                "process_feedback: pipeline attempt %d/%d failed for feedback_id=%d.",
                attempt,
                max_attempts,
                feedback_id,
            )

            if attempt < max_attempts:
                delay = _RETRY_DELAYS[attempt - 1]
                logger.info(
                    "process_feedback: retrying feedback_id=%d in %d s (next attempt %d/%d).",
                    feedback_id,
                    delay,
                    attempt + 1,
                    max_attempts,
                )
                time.sleep(delay)
            else:
                # All retries exhausted — mark failed and notify AlertManager.
                logger.critical(
                    "process_feedback: all %d attempts exhausted for feedback_id=%d. "
                    "Marking ProcessingFailed.",
                    max_attempts,
                    feedback_id,
                )
                context.log_context()
                feedback.status = "ProcessingFailed"
                feedback.save(update_fields=["status"])
                AlertManager.dispatch(feedback, context.urgency_rule)
                raise


def _run_pipeline(feedback, context: PipelineContext) -> None:
    """
    Execute pipeline stages 2–7 in the order specified by C-05.

    Any exception propagates immediately to the caller (process_feedback) so
    the retry logic can decide whether to retry or give up.  There is NO
    per-component try/except; every exception is logged with a full traceback
    by the outer handler in process_feedback.
    """
    from django.conf import settings

    from apps.nlp.pipeline.language_detector import detect_language
    from apps.nlp.pipeline.translation_service import translate_to_english
    from apps.nlp.pipeline.topic_classifier import classify_topics
    from apps.nlp.pipeline.urgency_assessor import assess_urgency
    from apps.nlp.pipeline.sentiment_analyser import analyse_sentiment
    from apps.nlp.pipeline.location_extractor import extract_location
    from apps.feedback.models import FeedbackCategory, Category

    # ── Step 2: Language detection ────────────────────────────────────────────
    ussd_hint = (
        feedback.language
        if feedback.channel == "USSD" and feedback.language not in ("unknown", None)
        else None
    )
    lang_result = (
        detect_language(feedback.message_text, ussd_language=ussd_hint)
        if ussd_hint
        else detect_language(feedback.message_text)
    )

    if isinstance(lang_result, tuple) and len(lang_result) == 3:
        language, lang_confidence, lang_flags = lang_result
    elif isinstance(lang_result, tuple) and len(lang_result) == 2:
        language, lang_confidence = lang_result
        lang_flags = {}
    else:
        raise ValueError(
            f"detect_language returned unexpected type {type(lang_result)!r} "
            f"for feedback_id={feedback.feedback_id}"
        )

    feedback.language = language
    feedback.language_confidence = lang_confidence
    if lang_flags.get("needs_language_review"):
        context.set_review_flag("needs_language_review")

    logger.debug(
        "_run_pipeline: feedback_id=%d lang=%s conf=%.4f",
        feedback.feedback_id,
        language,
        lang_confidence,
    )

    # ── Step 3: Translation to English ───────────────────────────────────────
    confidence_threshold = getattr(
        settings, "LANGUAGE_CONFIDENCE_THRESHOLD_TRANSLATION", 0.85
    )
    should_translate = (
        language not in ("en", "unknown")
        and lang_confidence is not None
        and lang_confidence >= confidence_threshold
    )

    if should_translate:
        translation_result = translate_to_english(
            feedback.message_text,
            language,
            {"feedback_id": feedback.feedback_id},
        )
        if isinstance(translation_result, tuple):
            english_text, trans_ctx = translation_result
            if trans_ctx.get("translation_failed"):
                context.translation_failed = True
                context.set_review_flag("translation_failed")
        else:
            english_text = translation_result
    else:
        if language not in ("en", "unknown") and lang_confidence is not None:
            if lang_confidence < confidence_threshold:
                context.set_review_flag("low_confidence_translation_skipped")
        english_text = feedback.message_text

    feedback.message_text_en = english_text

    # ── Step 4: Topic classification ─────────────────────────────────────────
    topic_result = classify_topics(feedback.message_text_en)
    if isinstance(topic_result, tuple) and len(topic_result) == 2:
        topic_results, topic_flags = topic_result
    else:
        topic_results = topic_result or []
        topic_flags = {}

    if topic_flags.get("needs_category_review"):
        context.set_review_flag("needs_category_review")

    for category_name, confidence in topic_results:
        try:
            category = Category.objects.get(category_name=category_name, is_active=True)
            FeedbackCategory.objects.update_or_create(
                feedback=feedback,
                category=category,
                defaults={"confidence_score": confidence, "is_ai_assigned": True},
            )
        except Category.DoesNotExist:
            logger.warning(
                "_run_pipeline: category '%s' not found in DB — skipping FeedbackCategory. "
                "feedback_id=%d",
                category_name,
                feedback.feedback_id,
            )

    # ── Step 5: Urgency assessment ────────────────────────────────────────────
    urgency_level, urgency_rule = assess_urgency(feedback.message_text_en)
    feedback.urgency_level = urgency_level
    context.urgency_rule = urgency_rule

    # ── Step 6: Sentiment analysis ────────────────────────────────────────────
    sentiment_obj, sentiment_conf = analyse_sentiment(feedback.message_text_en)
    feedback.sentiment = sentiment_obj
    feedback.sentiment_confidence = sentiment_conf

    # ── Step 7: Location extraction ───────────────────────────────────────────
    location_result = extract_location(feedback.message_text_en)
    if isinstance(location_result, tuple):
        location, _loc_conf, _loc_type = location_result
    else:
        location = location_result

    if location and not feedback.location:
        feedback.location = location
