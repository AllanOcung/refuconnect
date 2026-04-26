"""
Language detection using fasttext's lid.176.bin model.

The model is loaded lazily on first use and cached for the lifetime of the
worker process.  Set ``FASTTEXT_MODEL_PATH`` in the environment to point to
the model binary.  If the file does not exist (e.g. in CI), the detector
falls back gracefully to returning ``('unknown', 0.0, {...})``.
"""
from __future__ import annotations

import logging
import os
import re
from typing import Optional

from django.conf import settings

logger = logging.getLogger(__name__)

_model = None

# Supported languages for RefuConnect
_SUPPORTED_LANGUAGES = {"en", "sw", "lg", "rw", "ar", "fr", "so", "din"}


def _get_model():
    global _model
    if _model is not None:
        return _model

    model_path = getattr(settings, "FASTTEXT_MODEL_PATH", "")
    if not model_path or not os.path.isfile(model_path):
        logger.warning(
            "fasttext model not found at '%s'. Language detection will return 'unknown'.",
            model_path,
        )
        return None

    try:
        import fasttext  # type: ignore[import]

        fasttext.FastText.eprint = lambda x: None  # suppress noisy stderr
        _model = fasttext.load_model(model_path)
        logger.info("fasttext model loaded from %s", model_path)
    except Exception:
        logger.exception("Failed to load fasttext model.")
        _model = None

    return _model


def _clean_text(text: str) -> str:
    """Clean text: remove URLs, collapse whitespace, strip."""
    # Remove URLs (http, https, www patterns)
    text = re.sub(r"https?://\S+", "", text)
    text = re.sub(r"www\.\S+", "", text)
    # Collapse multiple whitespaces to single space
    text = re.sub(r"\s+", " ", text)
    # Strip leading/trailing whitespace
    return text.strip()


def detect_language(
    text: str,
    ussd_language: Optional[str] = None,
) -> tuple[str, float, dict]:
    """
    Detect the BCP 47 language code of *text*.

    Parameters
    ----------
    text: The text to detect language for.
    ussd_language: Optional USSD language hint. If provided and non-empty, trusted without model.

    Returns
    -------
    (language_code, confidence, review_flags_dict)
        language_code: BCP 47 tag (e.g. 'en', 'sw', 'lg') or 'unknown'.
        confidence: float in [0, 1].
        review_flags_dict: Dict with 'needs_language_review' bool and top 3 predictions list.
    """
    review_flags = {
        "needs_language_review": False,
        "top_predictions": [],
    }

    # Trust USSD language hint if provided
    if ussd_language and ussd_language.strip():
        return ussd_language.strip(), 1.0, review_flags

    # Clean text
    text = _clean_text(text)

    # Short text detection
    if len(text) < 10:
        return "unknown", 0.0, review_flags

    model = _get_model()
    if model is None:
        return "unknown", 0.0, review_flags

    # Limit to 1000 characters to cap processing time
    text = text[:1000]

    try:
        labels, probs = model.predict(text, k=3)
        predictions = []
        for label, prob in zip(labels, probs):
            lang = label.replace("__label__", "")
            confidence = float(prob)
            predictions.append((lang, round(confidence, 4)))

        # Return top prediction if in supported set, otherwise unknown
        for lang, confidence in predictions:
            if lang in _SUPPORTED_LANGUAGES:
                review_flags["top_predictions"] = predictions
                # Set review flag if confidence below 0.85
                if confidence < 0.85:
                    review_flags["needs_language_review"] = True
                return lang, confidence, review_flags

        # Top prediction not in supported set
        review_flags["top_predictions"] = predictions
        review_flags["needs_language_review"] = True
        return "unknown", 0.0, review_flags

    except Exception:
        logger.exception("Language detection failed for text snippet.")
        return "unknown", 0.0, review_flags
