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
from pathlib import Path
from typing import Optional

from filelock import FileLock, Timeout

logger = logging.getLogger(__name__)

_classifier = None
_tokenizer = None
_DEFAULT_MODEL = "facebook/bart-large-mnli"
_CONFIDENCE_THRESHOLD = 0.70
_MAX_INPUT_TOKENS = 512
_MODEL_INIT_LOCK = "/tmp/refuconnect_topic_classifier_init.lock"

# Exact DB category names (must match Category.category_name seeds).
# Verbose descriptions are used as NLI hypotheses so the model understands
# humanitarian context — short names score poorly on ambiguous messages.
_CATEGORY_DESCRIPTIONS: dict[str, str] = {
    "Food Security": "food access, nutrition, or food distribution problems",
    "Healthcare": "medical services, health facility access, medicine availability, or health emergencies",
    "Shelter & Housing": "accommodation conditions, settlement infrastructure, or non-food item distribution",
    "Water & Sanitation": "clean water access, hygiene, sanitation, or WASH services",
    "Education": "school access, learning materials, teacher availability, or child education programs",
    "Protection & Safety": "personal safety threats, gender-based violence, child protection, exploitation, or physical security concerns",
    "Livelihoods & Employment": "income generation, vocational training, employment, or economic support",
    "Legal Aid & Documentation": "refugee status determination, registration, documentation, or legal rights",
    "Psychosocial Support": "mental health, trauma counselling, or community social support",
    "Infrastructure": "roads, electricity, internet connectivity, or camp and settlement infrastructure",
    "General Feedback": "general feedback that does not fit any specific thematic category",
}


def _get_cache_dir() -> str:
    """Return a writable cache directory for HuggingFace assets."""
    cache_dir = os.environ.get("HUGGINGFACE_CACHE_DIR")
    if not cache_dir:
        cache_dir = "/app/models/huggingface"

    Path(cache_dir).mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("HF_HOME", cache_dir)
    os.environ.setdefault("HUGGINGFACE_HUB_CACHE", cache_dir)
    os.environ.setdefault("TRANSFORMERS_CACHE", cache_dir)
    return cache_dir


def _get_classifier():
    global _classifier
    if _classifier is not None:
        return _classifier

    model_name = os.environ.get("NLP_ZS_MODEL", _DEFAULT_MODEL)
    try:
        from transformers import pipeline  # type: ignore[import]

        cache_dir = _get_cache_dir()

        # Avoid multi-worker stampede when the model is first downloaded.
        lock = FileLock(_MODEL_INIT_LOCK, timeout=2)
        with lock:
            _classifier = pipeline(
                "zero-shot-classification",
                model=model_name,
                # Run on CPU; set device=0 to use GPU if available
                device=-1,
                model_kwargs={"cache_dir": cache_dir},
            )
            logger.info("Zero-shot classifier loaded: %s", model_name)
    except Timeout:
        logger.warning(
            "Zero-shot classifier init lock busy; skipping topic classification for this run."
        )
        _classifier = None
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

        cache_dir = _get_cache_dir()

        lock = FileLock(_MODEL_INIT_LOCK, timeout=2)
        with lock:
            _tokenizer = AutoTokenizer.from_pretrained(model_name, cache_dir=cache_dir)
            logger.info("Tokenizer loaded: %s", model_name)
    except Timeout:
        logger.warning("Tokenizer init lock busy; using character-based truncation fallback.")
        _tokenizer = None
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


def _get_feedback_and_text(
    text_or_feedback,
    feedback_id: Optional[int],
) -> tuple[Optional[object], str, Optional[int]]:
    """Resolve `(feedback_obj, text_to_classify, feedback_id)` from inputs."""
    feedback = None
    source_text = ""

    if hasattr(text_or_feedback, "message_text"):
        feedback = text_or_feedback
        source_text = (feedback.message_text_en or feedback.message_text or "").strip()
        feedback_id = feedback_id or getattr(feedback, "feedback_id", None)
    else:
        source_text = str(text_or_feedback or "").strip()

    return feedback, source_text, feedback_id


def _resolve_candidate_labels() -> tuple[list[str], dict[str, str]]:
    """
    Return ``(descriptions, desc_to_db_name)`` for active categories.

    *descriptions* are the verbose NLI hypothesis strings passed to the
    classifier.  *desc_to_db_name* maps each description back to the exact
    DB ``Category.category_name`` for persistence.
    """
    from apps.feedback.models import Category

    active_names: list[str] = list(
        Category.objects.filter(is_active=True).values_list("category_name", flat=True)
    )
    if not active_names:
        return [], {}

    descriptions: list[str] = []
    desc_to_db: dict[str, str] = {}

    for db_name in active_names:
        desc = _CATEGORY_DESCRIPTIONS.get(db_name)
        if desc is None:
            # Unknown category — use name itself as hypothesis
            desc = db_name
        descriptions.append(desc)
        desc_to_db[desc] = db_name

    return descriptions, desc_to_db


def classify_topics(
    text_or_feedback,
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

    feedback, source_text, feedback_id = _get_feedback_and_text(text_or_feedback, feedback_id)
    if not source_text:
        review_flags["needs_category_review"] = True
        return [], review_flags

    candidate_descriptions, desc_to_db = _resolve_candidate_labels()
    if not candidate_descriptions:
        logger.warning("No active categories found for topic classification.")
        review_flags["needs_category_review"] = True
        return [], review_flags

    classifier = _get_classifier()
    if classifier is None:
        return [], review_flags

    # Truncate to 512 tokens
    truncated = _truncate_to_tokens(source_text, _MAX_INPUT_TOKENS)

    results = []

    try:
        result = classifier(truncated, candidate_labels=candidate_descriptions, multi_label=True)
        # Map verbose description back to DB category name
        scored = [
            (desc_to_db.get(label, label), round(score, 3))
            for label, score in zip(result["labels"], result["scores"])
        ]
        classified = [item for item in scored if item[1] >= _CONFIDENCE_THRESHOLD]
        # Sort by score descending (highest confidence first)
        classified = sorted(classified, key=lambda x: x[1], reverse=True)
        if classified:
            results.extend(classified)
        elif scored:
            # Fallback: top label, flag for manual review.
            fallback_label, fallback_score = scored[0]
            results.append((fallback_label, fallback_score))
            review_flags["needs_category_review"] = True
        else:
            review_flags["needs_category_review"] = True
    except Exception:
        logger.exception("Topic classification failed.")
        review_flags["needs_category_review"] = True

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
            if feedback is None:
                feedback = Feedback.objects.get(feedback_id=feedback_id)

            # Preserve manual USSD categories (is_ai_assigned=False); add AI
            # categories without overriding existing non-AI assignments.
            manual_category_ids = set(
                FeedbackCategory.objects.filter(
                    feedback=feedback,
                    is_ai_assigned=False,
                ).values_list("category_id", flat=True)
            )

            for category_name, confidence in results:
                try:
                    category = Category.objects.get(category_name__iexact=category_name)

                    # If a manual category already exists, keep it untouched.
                    if category.category_id in manual_category_ids:
                        continue

                    created_row, _created = FeedbackCategory.objects.get_or_create(
                        feedback=feedback,
                        category=category,
                        defaults={"confidence_score": confidence, "is_ai_assigned": True},
                    )

                    # If AI row already exists, refresh confidence to latest score.
                    if not _created and created_row.is_ai_assigned:
                        created_row.confidence_score = confidence
                        created_row.save(update_fields=["confidence_score"])
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
