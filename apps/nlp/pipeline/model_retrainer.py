"""
AI model retrainer utilities.

Provides functions to log training runs and (in a real deployment) trigger
fine-tuning jobs on new labelled data.  The actual training logic would run
on a GPU instance external to the Django app; this module records metadata
and provides the interface for scheduling retraining.
"""
from __future__ import annotations

import logging
from collections import Counter
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


def log_training_run(
    model_type: str,
    model_version: str,
    training_data: list[dict[str, Any]],
    trained_by: str,
    accuracy_english: float | None = None,
    accuracy_swahili: float | None = None,
    accuracy_local_lang: float | None = None,
    bias_test_results: dict | None = None,
) -> "AIModelLog":
    """
    Record a completed training run in ``AIModelLog``.

    Parameters
    ----------
    model_type:        One of 'sentiment', 'topic_classifier', 'language_detector'.
    model_version:     Semantic version string, e.g. '1.3.0' or 'v20260412'.
    training_data:     List of labelled samples as dicts with at least a
                       'language' key for summary statistics.
    trained_by:        Email or identifier of the person/system that triggered training.
    accuracy_*:        Accuracy percentages on the respective language test sets.
    bias_test_results: Free-form dict from the bias test harness.

    Returns
    -------
    The created ``AIModelLog`` instance.
    """
    from apps.nlp.models import AIModelLog

    lang_counts = Counter(item.get("language", "unknown") for item in training_data)
    summary = (
        f"Trained on {len(training_data)} samples. "
        f"Language distribution: {dict(lang_counts)}."
    )

    log = AIModelLog.objects.create(
        model_type=model_type,
        model_version=model_version,
        training_data_summary=summary,
        accuracy_english=accuracy_english,
        accuracy_swahili=accuracy_swahili,
        accuracy_local_lang=accuracy_local_lang,
        bias_test_results=bias_test_results,
        trained_by=trained_by,
        trained_at=datetime.now(timezone.utc),
    )

    logger.info(
        "Logged training run: model_type=%s version=%s by=%s",
        model_type,
        model_version,
        trained_by,
    )
    return log


def prepare_sentiment_training_data() -> list[dict]:
    """
    Extract labelled feedback records from the database for retraining.

    Returns a list of dicts: {'text': str, 'label': str, 'language': str}.
    Only records that have been manually reviewed (reviewed_by is set) are
    included to ensure label quality.
    """
    from apps.feedback.models import Feedback

    records = (
        Feedback.objects.filter(
            status="Processed",
            reviewed_by__isnull=False,
            sentiment__isnull=False,
            message_text_en__isnull=False,
        )
        .select_related("sentiment")
        .values("message_text_en", "sentiment__sentiment_label", "language")
    )

    return [
        {
            "text": r["message_text_en"],
            "label": r["sentiment__sentiment_label"],
            "language": r["language"],
        }
        for r in records
        if r["message_text_en"]
    ]
