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
This module runs the pipeline exactly *once* per call.  If any component raises,
the exception propagates to the caller and the record is left in status
'Processing' so a later attempt can re-run it.  Retry scheduling (exponential
back-off) and the terminal 'ProcessingFailed' transition live in the Celery
task layer (``apps.nlp.tasks.process_feedback_nlp``), which re-queues the task
without blocking the worker between attempts.  Previously the back-off was a
blocking ``time.sleep`` inside the worker, which froze the single worker for up
to several minutes on a failing record and stalled the whole queue.

Constraints (C-05)
------------------
* This module never imports Celery.  It is called *by* the Celery task in
  tasks.py but has no Celery dependency itself.
* Every caught exception is logged with the full traceback and the feedback_id.
* Records already in status='Processed' are silently skipped (idempotency guard).
"""
from __future__ import annotations

import logging

from django.db import transaction
from django.utils import timezone

logger = logging.getLogger(__name__)


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
        # True only when the pipeline auto-extracted a location and wrote it to
        # the record. Used to decide whether 'location' is included in the final
        # save's update_fields — so a location the submitter provided via a
        # follow-up reply (written directly to the DB after this run loaded the
        # record) is never clobbered by a stale in-memory value.
        self.location_set: bool = False

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
    Run the NLP pipeline once for a single Feedback record.

    Fetches the record, marks it 'Processing' (idempotently, row-locked), then
    runs stages 2–7.  On success → 'Processed' + high-urgency alert dispatch.

    On failure the exception propagates to the caller and the record is left in
    'Processing'.  Retry scheduling and the terminal 'ProcessingFailed'
    transition are handled by the Celery task layer (see module docstring) so
    the worker is never blocked sleeping between attempts.
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

            # Mark Processing immediately so a crashed/retried worker does not
            # pick up the same record again.
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

    # Single run. On exception the record stays 'Processing'; the Celery task
    # decides whether to reschedule or mark the record ProcessingFailed.
    _run_pipeline(feedback, context)

    # Persist enriched record. Save only the fields this pipeline computes via
    # update_fields, so concurrently-updated columns (notably 'location', which
    # the submitter can set with a follow-up SMS/WhatsApp reply) are not
    # overwritten by stale values loaded at the start of this run.
    feedback.status = "Processed"
    feedback.processed_at = timezone.now()
    update_fields = [
        "language",
        "language_confidence",
        "message_text_en",
        "urgency_level",
        "sentiment",
        "sentiment_confidence",
        "status",
        "processed_at",
    ]
    if context.location_set:
        update_fields.append("location")
    feedback.save(update_fields=update_fields)
    context.log_context()
    logger.info(
        "process_feedback: feedback_id=%d processed successfully.",
        feedback_id,
    )

    # Alert if high-urgency (runs after successful save)
    if feedback.urgency_level == "High":
        AlertManager.dispatch(feedback, context.urgency_rule)


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
    from apps.nlp.pipeline.urgency_assessor import assess_feedback_urgency
    from apps.nlp.pipeline.sentiment_analyser import analyse_feedback_sentiment
    from apps.nlp.pipeline.location_extractor import extract_location
    # TopicClassifier persists FeedbackCategory rows internally (C-08).

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
        settings, "LANGUAGE_CONFIDENCE_THRESHOLD_TRANSLATION", 0.75
    )
    force_translate_languages = set(
        getattr(settings, "LANGUAGES_ALWAYS_TRANSLATE", ("sw",))
    )
    should_force_translate = language in force_translate_languages

    should_translate = (
        language not in ("en", "unknown")
        and (
            should_force_translate
            or (lang_confidence is not None and lang_confidence >= confidence_threshold)
        )
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
        if (
            language not in ("en", "unknown")
            and not should_force_translate
            and lang_confidence is not None
        ):
            if lang_confidence < confidence_threshold:
                context.set_review_flag("low_confidence_translation_skipped")
        english_text = feedback.message_text

    feedback.message_text_en = english_text

    # ── Step 4: Topic classification ─────────────────────────────────────────
    topic_result = classify_topics(feedback)
    if isinstance(topic_result, tuple) and len(topic_result) == 2:
        _topic_results, topic_flags = topic_result
    else:
        _topic_results = topic_result or []
        topic_flags = {}

    if topic_flags.get("needs_category_review"):
        context.set_review_flag("needs_category_review")

    # ── Step 5: Urgency assessment ────────────────────────────────────────────
    urgency_level, urgency_rule, urgency_ctx = assess_feedback_urgency(feedback)
    feedback.urgency_level = urgency_level
    context.urgency_rule = urgency_rule

    # ── Step 6: Sentiment analysis ────────────────────────────────────────────
    sentiment_obj, sentiment_conf, sentiment_ctx = analyse_feedback_sentiment(
        feedback,
        translation_failed=context.translation_failed,
    )
    if sentiment_ctx.get("sentiment_used_untranslated_text"):
        context.set_review_flag("sentiment_used_untranslated_text")
    feedback.sentiment = sentiment_obj
    feedback.sentiment_confidence = sentiment_conf

    # ── Step 7: Location extraction ───────────────────────────────────────────
    location_result = extract_location(feedback.message_text_en)
    if isinstance(location_result, tuple):
        location, _loc_conf, _loc_type = location_result
    else:
        location = location_result

    if location:
        # Read the current location straight from the DB rather than trusting the
        # in-memory value, which may be stale: the submitter can supply a location
        # via a follow-up reply (written by the channel adapter) after this run
        # started. Only persist an auto-extracted location when none exists, and
        # never overwrite a submitter-provided one.
        from apps.feedback.models import Feedback

        current_location = (
            Feedback.objects.filter(pk=feedback.pk)
            .values_list("location", flat=True)
            .first()
        )
        if not current_location:
            feedback.location = location
            context.location_set = True
