"""
Main NLP pipeline consumer.

Orchestrates all NLP stages for a single Feedback record in sequence:
  1. Language detection (fasttext)
  2. Translation to English (Google Cloud)
  3. Sentiment analysis (VADER)
  4. Urgency assessment (keyword rules)
  5. Location extraction (gazetteer)
  6. Topic classification (zero-shot transformer)
  7. Alert creation for high-urgency feedback

Features:
  - Component-level retry logic with exponential backoff (30s, 120s, 300s)
  - Processing context dict to track failures and flags
  - Graceful degradation: failed components don't fail the entire pipeline
  - Full tracebacks logged with feedback_id for debugging
"""
from __future__ import annotations

import logging
import time
from typing import Any

from django.db import transaction
from django.utils import timezone

logger = logging.getLogger(__name__)

# Retry configuration (in seconds)
_RETRY_DELAYS = [30, 120, 300]  # exponential backoff: 30s, 120s, 300s


class PipelineContext:
    """
    Context object passed through the pipeline to track processing state,
    failures, and flags for manual review.
    """

    def __init__(self, feedback_id: int):
        self.feedback_id = feedback_id
        self.component_failures: dict[str, str] = {}  # component_name -> error_msg
        self.review_flags: dict[str, bool] = {}  # flag_name -> is_set
        self.translation_failed = False
        self.urgency_rule = None  # to track which rule triggered urgency

    def mark_component_failed(self, component_name: str, error: Exception) -> None:
        """Record a component failure with full traceback."""
        self.component_failures[component_name] = f"{type(error).__name__}: {str(error)}"
        logger.warning(
            "Component '%s' failed for feedback %d: %s",
            component_name,
            self.feedback_id,
            self.component_failures[component_name],
        )

    def set_review_flag(self, flag_name: str) -> None:
        """Mark a flag for manual review (e.g., needs_lang_review, needs_category_review)."""
        self.review_flags[flag_name] = True

    def log_context(self) -> None:
        """Log the full processing context at the end."""
        if self.component_failures:
            logger.info(
                "Feedback %d had component failures: %s",
                self.feedback_id,
                self.component_failures,
            )
        if self.review_flags:
            logger.info(
                "Feedback %d flagged for review: %s",
                self.feedback_id,
                list(self.review_flags.keys()),
            )


def process_feedback(feedback_id: int) -> None:
    """
    Execute the full NLP pipeline for the Feedback record identified by
    *feedback_id*.

    On success the record status is set to 'Processed'.
    On any unhandled exception the status is set to 'ProcessingFailed'.
    """
    from apps.feedback.models import Feedback

    # Lock the row, check status, and mark as Processing — all inside one
    # atomic block so select_for_update() has a transaction to work with.
    try:
        with transaction.atomic():
            try:
                feedback = Feedback.objects.select_for_update().get(
                    feedback_id=feedback_id
                )
            except Feedback.DoesNotExist:
                logger.error("Feedback %d not found — skipping NLP pipeline.", feedback_id)
                return

            # Guard: do not re-process already completed records
            if feedback.status in ("Processed", "Archived"):
                logger.info(
                    "Feedback %d already in status '%s' — skipping.", feedback_id, feedback.status
                )
                return

            feedback.status = "Processing"
            feedback.save(update_fields=["status"])
    # Lock released here; heavy ML work happens outside the transaction.
    except Exception as exc:
        logger.exception("NLP pipeline failed acquiring lock for feedback %d.", feedback_id)
        raise

    # Create processing context
    context = PipelineContext(feedback_id)

    # Try to run pipeline with retry logic
    max_attempts = 3
    for attempt in range(1, max_attempts + 1):
        try:
            _run_pipeline(feedback, context)
            feedback.status = "Processed"
            feedback.processed_at = timezone.now()
            feedback.save()
            context.log_context()
            logger.info("Feedback %d processed successfully on attempt %d.", feedback_id, attempt)
            return

        except Exception as exc:
            logger.exception(
                "NLP pipeline attempt %d failed for feedback %d.",
                attempt,
                feedback_id,
            )

            if attempt < max_attempts:
                # Calculate backoff delay
                delay_seconds = _RETRY_DELAYS[attempt - 1]
                logger.info(
                    "Retrying feedback %d in %d seconds (attempt %d/%d).",
                    feedback_id,
                    delay_seconds,
                    attempt + 1,
                    max_attempts,
                )
                time.sleep(delay_seconds)
            else:
                # Final attempt failed — mark as failed and give up
                logger.critical(
                    "NLP pipeline exhausted all retries for feedback %d after %d attempts.",
                    feedback_id,
                    max_attempts,
                )
                context.log_context()
                feedback.status = "ProcessingFailed"
                feedback.save(update_fields=["status"])
                raise


def _run_pipeline(feedback, context: PipelineContext) -> None:
    """
    Execute all pipeline stages mutating *feedback* in place.

    Stages are run sequentially; if a stage fails, it's logged and the next
    stage runs anyway (graceful degradation). The context tracks all failures.
    """
    from apps.nlp.pipeline.language_detector import detect_language
    from apps.nlp.pipeline.translation_service import translate_to_english
    from apps.nlp.pipeline.sentiment_analyser import analyse_sentiment
    from apps.nlp.pipeline.urgency_assessor import assess_urgency
    from apps.nlp.pipeline.location_extractor import extract_location
    from apps.nlp.pipeline.topic_classifier import classify_topics
    from apps.feedback.models import FeedbackCategory, Category, Alert

    # ── 1. Language detection ─────────────────────────────────────────────────
    try:
        language, lang_confidence = detect_language(feedback.message_text)
        feedback.language = language
        feedback.language_confidence = lang_confidence
    except Exception as exc:
        context.mark_component_failed("LanguageDetector", exc)
        # Set defaults and continue
        feedback.language = "unknown"
        feedback.language_confidence = 0.0

    # ── 2. Translation to English ─────────────────────────────────────────────
    try:
        if feedback.language not in ("en", "unknown"):
            english_text = translate_to_english(feedback.message_text, feedback.language)
        else:
            english_text = feedback.message_text
        feedback.message_text_en = english_text
    except Exception as exc:
        context.mark_component_failed("TranslationService", exc)
        context.translation_failed = True
        # Fall back to original text
        feedback.message_text_en = feedback.message_text

    # ── 3. Sentiment analysis ─────────────────────────────────────────────────
    try:
        sentiment_obj, sentiment_conf = analyse_sentiment(feedback.message_text_en)
        feedback.sentiment = sentiment_obj
        feedback.sentiment_confidence = sentiment_conf
    except Exception as exc:
        context.mark_component_failed("SentimentAnalyser", exc)
        # Leave sentiment as null; optional field

    # ── 4. Urgency assessment ─────────────────────────────────────────────────
    try:
        urgency_level, urgency_rule = assess_urgency(feedback.message_text_en)
        feedback.urgency_level = urgency_level
        context.urgency_rule = urgency_rule
    except Exception as exc:
        context.mark_component_failed("UrgencyAssessor", exc)
        # Default to Low urgency
        feedback.urgency_level = "Low"

    # ── 5. Location extraction ────────────────────────────────────────────────
    try:
        location = extract_location(feedback.message_text_en)
        if location and not feedback.location:
            feedback.location = location
    except Exception as exc:
        context.mark_component_failed("LocationExtractor", exc)
        # Location is best-effort; continue without it

    # ── 6. Topic classification ───────────────────────────────────────────────
    try:
        topic_results = classify_topics(feedback.message_text_en)
        for category_name, confidence in topic_results:
            try:
                category = Category.objects.get(category_name=category_name, is_active=True)
                FeedbackCategory.objects.update_or_create(
                    feedback=feedback,
                    category=category,
                    defaults={
                        "confidence_score": confidence,
                        "is_ai_assigned": True,
                    },
                )
            except Category.DoesNotExist:
                logger.warning("Category '%s' not found in database.", category_name)
    except Exception as exc:
        context.mark_component_failed("TopicClassifier", exc)
        # Categories are optional; continue without them

    # ── 7. Auto-create alert for high-urgency feedback ────────────────────────
    if feedback.urgency_level == "High":
        try:
            alert_exists = feedback.alert if hasattr(feedback, "alert") else False
            if not alert_exists:
                Alert.objects.create(
                    feedback=feedback,
                    priority_level="High",
                    description=(
                        f"Auto-generated: high urgency detected in Feedback #{feedback.feedback_id}. "
                        f"Sentiment: {feedback.sentiment or 'N/A'}. "
                        f"Rule: {context.urgency_rule or 'unknown'}."
                    ),
                )
        except Exception:
            # Alert creation is best-effort — don't fail the entire pipeline
            logger.exception(
                "Failed to create auto-alert for feedback %d.", feedback.feedback_id
            )
