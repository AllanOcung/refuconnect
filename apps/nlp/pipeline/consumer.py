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
"""
from __future__ import annotations

import logging

from django.db import transaction
from django.utils import timezone

logger = logging.getLogger(__name__)


def process_feedback(feedback_id: int) -> None:
    """
    Execute the full NLP pipeline for the Feedback record identified by
    *feedback_id*.

    On success the record status is set to 'Processed'.
    On any unhandled exception the status is set to 'ProcessingFailed' and
    the exception is re-raised so Celery can retry the task.
    """
    from apps.feedback.models import Feedback, FeedbackCategory, Category, Alert

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

    try:
        _run_pipeline(feedback)
        feedback.status = "Processed"
        feedback.processed_at = timezone.now()
        feedback.save()
        logger.info("Feedback %d processed successfully.", feedback_id)

    except Exception as exc:
        logger.exception("NLP pipeline failed for feedback %d.", feedback_id)
        feedback.status = "ProcessingFailed"
        feedback.save(update_fields=["status"])
        raise


def _run_pipeline(feedback) -> None:
    """Execute all pipeline stages mutating *feedback* in place."""
    from apps.nlp.pipeline.language_detector import detect_language
    from apps.nlp.pipeline.translation_service import translate_to_english
    from apps.nlp.pipeline.sentiment_analyser import analyse_sentiment
    from apps.nlp.pipeline.urgency_assessor import assess_urgency
    from apps.nlp.pipeline.location_extractor import extract_location
    from apps.nlp.pipeline.topic_classifier import classify_topics
    from apps.feedback.models import FeedbackCategory, Category, Alert

    # ── 1. Language detection ─────────────────────────────────────────────────
    language, lang_confidence = detect_language(feedback.message_text)
    feedback.language = language
    feedback.language_confidence = lang_confidence

    # ── 2. Translation to English ─────────────────────────────────────────────
    if language not in ("en", "unknown"):
        english_text = translate_to_english(feedback.message_text, language)
    else:
        english_text = feedback.message_text
    feedback.message_text_en = english_text

    # ── 3. Sentiment analysis ─────────────────────────────────────────────────
    sentiment_obj, sentiment_conf = analyse_sentiment(english_text)
    feedback.sentiment = sentiment_obj
    feedback.sentiment_confidence = sentiment_conf

    # ── 4. Urgency assessment ─────────────────────────────────────────────────
    feedback.urgency_level = assess_urgency(english_text)

    # ── 5. Location extraction ────────────────────────────────────────────────
    location = extract_location(english_text)
    if location and not feedback.location:
        feedback.location = location

    # ── 6. Topic classification ───────────────────────────────────────────────
    topic_results = classify_topics(english_text)
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

    # ── 7. Auto-create alert for high-urgency feedback ────────────────────────
    if feedback.urgency_level == "High" and not hasattr(feedback, "alert"):
        try:
            Alert.objects.create(
                feedback=feedback,
                priority_level="High",
                description=(
                    f"Auto-generated: high urgency detected in Feedback #{feedback.feedback_id}. "
                    f"Sentiment: {feedback.sentiment or 'N/A'}."
                ),
            )
        except Exception:
            # Alert creation is best-effort — don't fail the entire pipeline
            logger.exception(
                "Failed to create auto-alert for feedback %d.", feedback.feedback_id
            )
