"""
Language detection using fasttext's lid.176.bin model.

The model is loaded lazily on first use and cached for the lifetime of the
worker process.  Set ``FASTTEXT_MODEL_PATH`` in the environment to point to
the model binary.  If the file does not exist (e.g. in CI), the detector
falls back gracefully to returning ``('unknown', 0.0)``.
"""
from __future__ import annotations

import logging
import os
from typing import Optional

from django.conf import settings

logger = logging.getLogger(__name__)

_model = None


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


def detect_language(text: str) -> tuple[str, float]:
    """
    Detect the BCP 47 language code of *text*.

    Returns
    -------
    (language_code, confidence)
        language_code is a BCP 47 tag (e.g. 'en', 'sw', 'lg').
        confidence is a float in [0, 1].
    """
    model = _get_model()
    if model is None:
        return "unknown", 0.0

    # fasttext dislikes newlines
    sanitised = text.replace("\n", " ").strip()
    if not sanitised:
        return "unknown", 0.0

    # Limit to 1 000 characters to cap processing time
    sanitised = sanitised[:1000]

    try:
        labels, probs = model.predict(sanitised, k=1)
        lang = labels[0].replace("__label__", "")
        confidence = float(probs[0])
        return lang, round(confidence, 4)
    except Exception:
        logger.exception("Language detection failed for text snippet.")
        return "unknown", 0.0
