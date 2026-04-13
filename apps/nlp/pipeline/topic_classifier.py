"""
Topic classification using HuggingFace zero-shot classification.

Uses ``facebook/bart-large-mnli`` by default (can be overridden via
``NLP_ZS_MODEL`` environment variable).  The classifier is loaded lazily
and cached per worker process.  A confidence threshold of 0.40 is applied
so only meaningful category assignments are returned.
"""
from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

_classifier = None
_DEFAULT_MODEL = "facebook/bart-large-mnli"
_CONFIDENCE_THRESHOLD = 0.40
_MAX_INPUT_CHARS = 512


def _get_classifier():
    global _classifier
    if _classifier is not None:
        return _classifier

    model_name = os.environ.get("NLP_ZS_MODEL", _DEFAULT_MODEL)
    try:
        from transformers import pipeline  # type: ignore[import]

        _classifier = pipeline(
            "zero-shot-classification",
            model=model_name,
            # Run on CPU; set device=0 to use GPU if available
            device=-1,
        )
        logger.info("Zero-shot classifier loaded: %s", model_name)
    except Exception:
        logger.exception(
            "Failed to load zero-shot classifier '%s'. Topic classification disabled.",
            model_name,
        )
        _classifier = None

    return _classifier


def classify_topics(text: str) -> list[tuple[str, float]]:
    """
    Classify *text* against active Category labels.

    Parameters
    ----------
    text: English text (translate before calling).

    Returns
    -------
    List of (category_name, confidence) tuples where confidence >= threshold.
    Ordered by confidence descending.
    """
    from apps.feedback.models import Category

    active_labels = list(
        Category.objects.filter(is_active=True).values_list("category_name", flat=True)
    )
    if not active_labels:
        logger.warning("No active categories found for topic classification.")
        return []

    classifier = _get_classifier()
    if classifier is None:
        return []

    truncated = text[:_MAX_INPUT_CHARS]
    try:
        result = classifier(truncated, candidate_labels=active_labels, multi_label=True)
        return [
            (label, round(score, 3))
            for label, score in zip(result["labels"], result["scores"])
            if score >= _CONFIDENCE_THRESHOLD
        ]
    except Exception:
        logger.exception("Topic classification failed.")
        return []
