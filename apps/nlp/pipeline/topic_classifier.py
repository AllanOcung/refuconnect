"""
apps/nlp/pipeline/topic_classifier.py
"""
from __future__ import annotations

import logging

from django.conf import settings
from transformers import pipeline as hf_pipeline

try:
    from apps.feedback.models import Category, FeedbackCategory
except Exception:
    Category = None
    FeedbackCategory = None

logger = logging.getLogger(__name__)

_MODEL_NAME: str = getattr(
    settings, "TOPIC_CLASSIFIER_MODEL", "facebook/bart-large-mnli"
)
_CONFIDENCE_THRESHOLD: float = float(
    getattr(settings, "NLP_CONFIDENCE_THRESHOLD_TOPIC", 0.70)
)
_HF_CACHE: str = getattr(settings, "HUGGINGFACE_CACHE_DIR", "models/huggingface/")
_MAX_INPUT_CHARS: int = 1800


class TopicClassifier:
    """
    Assigns humanitarian Category labels to a Feedback record.
    """

    _classifier = None  # process-wide singleton

    def __init__(self) -> None:
        if TopicClassifier._classifier is not None:
            return

        logger.info("TopicClassifier: loading zero-shot model %s.", _MODEL_NAME)
        try:
            TopicClassifier._classifier = hf_pipeline(
                "zero-shot-classification",
                model=_MODEL_NAME,
                cache_dir=_HF_CACHE,
                device=-1,
            )
        except Exception as exc:
            logger.critical(
                "Failed to load topic classifier model %s: %s", _MODEL_NAME, exc
            )
            raise

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _active_labels() -> list[str]:
        """Fetch candidate labels from the live Category table."""
        import apps.nlp.pipeline.topic_classifier as _mod
        _Category = _mod.Category
        labels = list(
            _Category.objects.filter(is_active=True).values_list(
                "category_name", flat=True
            )
        )
        if not labels:
            logger.warning("TopicClassifier: no active categories found in DB.")
        return labels

    @staticmethod
    def _ussd_category_names(record) -> set[str]:
        """Return category names pre-selected via USSD (human-assigned, not AI)."""
        return {
            fc.category.category_name
            for fc in record.feedbackcategory_set.filter(is_ai_assigned=False)
        }

    # ── Public interface ──────────────────────────────────────────────────────

    def process(self, record, context: dict) -> tuple:
        """
        Classify *record* and persist FeedbackCategory junction records.
        """
        import apps.nlp.pipeline.topic_classifier as _mod
        _FeedbackCategory = _mod.FeedbackCategory
        _Category = _mod.Category

        feedback_id = record.pk

        candidate_labels = self._active_labels()
        if not candidate_labels:
            context["needs_category_review"] = True
            return record, context

        text: str = (record.message_text_en or record.message_text or "")[
            :_MAX_INPUT_CHARS
        ]
        if not text:
            logger.warning(
                "feedback_id=%s: empty text for topic classification.", feedback_id
            )
            context["needs_category_review"] = True
            return record, context

        try:
            result = TopicClassifier._classifier(
                text,
                candidate_labels=candidate_labels,
                multi_label=True,
            )
        except Exception as exc:
            logger.error(
                "feedback_id=%s: topic classification failed: %s",
                feedback_id,
                exc,
                exc_info=True,
            )
            context["needs_category_review"] = True
            return record, context

        scores: dict[str, float] = dict(zip(result["labels"], result["scores"]))

        accepted = {
            name: score
            for name, score in scores.items()
            if score >= _CONFIDENCE_THRESHOLD
        }

        if not accepted:
            top_name = max(scores, key=scores.__getitem__)
            accepted = {top_name: scores[top_name]}
            context["needs_category_review"] = True
            logger.info(
                "feedback_id=%s: no category above %.2f threshold; "
                "falling back to '%s' (score=%.4f).",
                feedback_id,
                _CONFIDENCE_THRESHOLD,
                top_name,
                scores[top_name],
            )

        ussd_names = self._ussd_category_names(record)

        for name, score in accepted.items():
            try:
                category = self._get_category_by_name(name)
            except Exception:
                logger.warning(
                    "feedback_id=%s: category '%s' not found or inactive; skipping.",
                    feedback_id,
                    name,
                )
                continue

            fc, created = _FeedbackCategory.objects.get_or_create(
                feedback=record,
                category=category,
                defaults={
                    "confidence_score": round(score, 4),
                    "is_ai_assigned": True,
                },
            )

            if not created:
                if not fc.is_ai_assigned:
                    logger.debug(
                        "feedback_id=%s: USSD category '%s' preserved.", feedback_id, name
                    )
                else:
                    fc.confidence_score = round(score, 4)
                    fc.save(update_fields=["confidence_score"])

        logger.debug(
            "feedback_id=%s: assigned categories: %s", feedback_id, list(accepted.keys())
        )
        return record, context

    def _get_category_by_name(self, name: str):
        import apps.nlp.pipeline.topic_classifier as _mod
        _Category = _mod.Category
        return _Category.objects.get(category_name=name, is_active=True)