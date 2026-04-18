from __future__ import annotations

import logging
import os
import re

try:
    import fasttext
except ImportError:
    fasttext = None
from django.conf import settings

logger = logging.getLogger(__name__)

SUPPORTED_LANGUAGES: frozenset[str] = frozenset(
    {"en", "sw", "lg", "rw", "ar", "fr", "so", "din"}
)

_CONFIDENCE_THRESHOLD: float = float(
    getattr(settings, "NLP_CONFIDENCE_THRESHOLD_LANGUAGE", 0.90)
)
_MIN_TEXT_LENGTH: int = 10
_MAX_TEXT_LENGTH: int = 1000

_URL_RE = re.compile(r"https?://\S+|www\.\S+", re.IGNORECASE)
_MULTI_SPACE_RE = re.compile(r"\s+")


def _clean_text(text: str) -> str:
    text = _URL_RE.sub("", text)
    text = _MULTI_SPACE_RE.sub(" ", text).strip()
    return text[:_MAX_TEXT_LENGTH]


class LanguageDetector:

    _model = None  # process-wide singleton

    def __init__(self) -> None:
        if LanguageDetector._model is not None:
            return

        model_path: str = getattr(settings, "FASTTEXT_MODEL_PATH", "")

        if not model_path or not os.path.isfile(model_path):
            logger.warning(
                "fastText model not found at '%s'; language detection will return 'unknown'.",
                model_path,
            )
            return

        try:
            fasttext.FastText.eprint = lambda *args, **kwargs: None
            LanguageDetector._model = fasttext.load_model(model_path)
            logger.info("fastText model loaded from %s.", model_path)
        except Exception as exc:
            logger.critical("Failed to load fastText model from %s: %s", model_path, exc)
            raise

    def process(self, record, context: dict) -> tuple:
        """
        Detect language for *record*.  Mutates record fields in place; does NOT save.

        Returns:
            (record, context) tuple.
        """
        feedback_id = record.pk

        # USSD records carry a user-selected language that is authoritative.
        if record.language and getattr(record, "channel", None) == "USSD":
            record.language_confidence = 1.0
            logger.debug(
                "feedback_id=%s: USSD language hint '%s' trusted.",
                feedback_id,
                record.language,
            )
            return record, context

        text: str = record.message_text or ""

        if len(text) < _MIN_TEXT_LENGTH:
            record.language = "unknown"
            record.language_confidence = 0.5
            context["needs_lang_review"] = True
            logger.warning(
                "feedback_id=%s: text too short (%d chars); language set to 'unknown'.",
                feedback_id,
                len(text),
            )
            return record, context

        if LanguageDetector._model is None:
            record.language = "unknown"
            record.language_confidence = 0.0
            context["needs_lang_review"] = True
            logger.warning(
                "feedback_id=%s: model unavailable; language set to 'unknown'.", feedback_id
            )
            return record, context

        cleaned = _clean_text(text)

        try:
            labels, confidences = LanguageDetector._model.predict(cleaned, k=3)
        except Exception as exc:
            logger.error(
                "feedback_id=%s: fastText prediction failed: %s",
                feedback_id,
                exc,
                exc_info=True,
            )
            record.language = "unknown"
            record.language_confidence = 0.0
            context["needs_lang_review"] = True
            return record, context

        top_label: str = labels[0].replace("__label__", "")
        top_confidence: float = round(float(confidences[0]), 4)

        if top_label not in SUPPORTED_LANGUAGES:
            top_label = "other"

        if top_confidence < _CONFIDENCE_THRESHOLD:
            context["needs_lang_review"] = True
            logger.info(
                "feedback_id=%s: low language confidence %.4f for '%s'; flagged for review.",
                feedback_id,
                top_confidence,
                top_label,
            )

        record.language = top_label
        record.language_confidence = top_confidence

        logger.debug(
            "feedback_id=%s: language=%s confidence=%.4f",
            feedback_id,
            record.language,
            record.language_confidence,
        )
        return record, context