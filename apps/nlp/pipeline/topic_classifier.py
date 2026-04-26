"""
Topic classification using HuggingFace zero-shot classification.

Uses ``facebook/bart-large-mnli`` by default (can be overridden via
``NLP_ZS_MODEL`` environment variable).  The classifier is loaded lazily
and cached per worker process.  A confidence threshold of 0.70 is applied
so only high-confidence category assignments are returned.

Supports multi-label classification and creates FeedbackCategory records
for each assigned category.
"""
from __future__ import annotations

import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

_classifier = None
_tokenizer = None
_DEFAULT_MODEL = "facebook/bart-large-mnli"
_CONFIDENCE_THRESHOLD = 0.70
_MAX_INPUT_TOKENS = 512


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


def _get_tokenizer():
    global _tokenizer
    if _tokenizer is not None:
        return _tokenizer

    model_name = os.environ.get("NLP_ZS_MODEL", _DEFAULT_MODEL)
    try:
        from transformers import AutoTokenizer  # type: ignore[import]

        _tokenizer = AutoTokenizer.from_pretrained(model_name)
        logger.info("Tokenizer loaded: %s", model_name)
    except Exception:
        logger.exception("Failed to load tokenizer for token counting.")
        _tokenizer = None

    return _tokenizer


def _truncate_to_tokens(text: str, max_tokens: int = _MAX_INPUT_TOKENS) -> str:
    """Truncate text to max_tokens using the transformer tokenizer."""
    tokenizer = _get_tokenizer()
    if tokenizer is None:
        # Fallback: rough estimate (1 token ≈ 4 chars)
        estimated_chars = max_tokens * 4
        return text[:estimated_chars]

    try:
        tokens = tokenizer.encode(text)
        if len(tokens) <= max_tokens:
            return text

        # Decode truncated token sequence
        truncated_tokens = tokens[:max_tokens]
        decoded = tokenizer.decode(truncated_tokens, skip_special_tokens=True)
        return decoded
    except Exception:
        logger.exception("Token truncation failed; using fallback.")
        estimated_chars = max_tokens * 4
        return text[:estimated_chars]


def classify_topics(
    text: str,
    feedback_id: Optional[int] = None,
    ussd_pre_category: Optional[str] = None,
) -> tuple[list[tuple[str, float]], dict]:
    """
    Classify *text* against active Category labels.

    Parameters
    ----------
    text:              English text (translate before calling).
    feedback_id:       Optional feedback ID for creating FeedbackCategory records.
    ussd_pre_category: Optional pre-category from USSD (included with confidence 1.0).

    Returns
    -------
    ([(category_name, confidence), ...], review_flags_dict)
        List of (category_name, confidence) tuples where confidence >= threshold.
        Ordered by confidence descending.
        review_flags_dict contains 'needs_category_review' flag.
    """
    from apps.feedback.models import Category, FeedbackCategory, Feedback

    review_flags = {"needs_category_review": False}

    active_labels = list(
        Category.objects.filter(is_active=True).values_list("category_name", flat=True)
    )
    if not active_labels:
        logger.warning("No active categories found for topic classification.")
        return [], review_flags

    classifier = _get_classifier()
    if classifier is None:
        return [], review_flags

    # Truncate to 512 tokens
    truncated = _truncate_to_tokens(text, _MAX_INPUT_TOKENS)

    results = []

    try:
        result = classifier(truncated, candidate_labels=active_labels, multi_label=True)
        classified = [
            (label, round(score, 3))
            for label, score in zip(result["labels"], result["scores"])
            if score >= _CONFIDENCE_THRESHOLD
        ]
        # Sort by score descending (highest confidence first)
        classified = sorted(classified, key=lambda x: x[1], reverse=True)
        results.extend(classified)
    except Exception:
        logger.exception("Topic classification failed.")

    # Add USSD pre-category if provided
    if ussd_pre_category:
        # Check if already in results
        category_names = [cat for cat, _ in results]
        if ussd_pre_category not in category_names:
            results.insert(0, (ussd_pre_category, 1.0))
        logger.info("USSD pre-category added: %s", ussd_pre_category)

    # Set review flag if no categories found
    if not results:
        review_flags["needs_category_review"] = True

    # Create FeedbackCategory records if feedback_id provided
    if feedback_id is not None and results:
        try:
            feedback = Feedback.objects.get(feedback_id=feedback_id)
            for category_name, confidence in results:
                try:
                    category = Category.objects.get(category_name=category_name)
                    # Use get_or_create to skip duplicates
                    FeedbackCategory.objects.get_or_create(
                        feedback=feedback,
                        category=category,
                        defaults={"confidence_score": confidence, "is_ai_assigned": True},
                    )
                except Category.DoesNotExist:
                    logger.warning(
                        "Category not found: %s. Skipping FeedbackCategory creation.",
                        category_name,
                    )
        except Feedback.DoesNotExist:
            logger.warning("Feedback not found: %d. Skipping FeedbackCategory creation.", feedback_id)
        except Exception:
            logger.exception("Failed to create FeedbackCategory records.")

    return results, review_flags
