"""
Language detection using lingua-language-detector as the primary model,
with fastText and AfroLID as secondary fallbacks.

lingua is loaded lazily on first use and cached for the lifetime of the
worker process. It is restricted to English and Swahili -- the two languages
supported by RefuConnect -- which makes it both fast and highly accurate even
on short messages (where fastText is notoriously unreliable).

Fallback chain:
  1. lingua  (primary -- character n-gram model, built for en+sw only)
  2. fastText (secondary -- broad 176-language model)
  3. AfroLID  (tertiary -- African-language specialist microservice)

If all three models fail or are unavailable, the detector returns
``('unknown', 0.0, {})``.
"""
from __future__ import annotations

import logging
import os
import re
from typing import Optional

from django.conf import settings

logger = logging.getLogger(__name__)

_model = None            # fastText model cache
_afrolid_model = None    # AfroLID local model cache
_lingua_detector = None  # lingua detector cache

# Supported languages for RefuConnect
_SUPPORTED_LANGUAGES = {"en", "sw"}

_AFROLID_TO_SUPPORTED = {
    "eng": "en",
    "swa": "sw",
    "swh": "sw",
    "swc": "sw",
}

# Lingua Language enum codes mapped to our BCP-47 codes
_LINGUA_TO_SUPPORTED = {
    "ENGLISH": "en",
    "SWAHILI": "sw",
}

# Minimum lingua confidence to trust the result without review flag
_LINGUA_REVIEW_THRESHOLD = 0.50


# ---------------------------------------------------------------------------
# Lazy loaders
# ---------------------------------------------------------------------------

def _get_lingua_detector():
    """Return a cached lingua detector restricted to English + Swahili."""
    global _lingua_detector
    if _lingua_detector is not None:
        return _lingua_detector

    try:
        from lingua import Language, LanguageDetectorBuilder  # type: ignore[import]

        _lingua_detector = (
            LanguageDetectorBuilder.from_languages(Language.ENGLISH, Language.SWAHILI)
            .build()
        )
        logger.info("lingua language detector loaded (en + sw)")
    except Exception:
        logger.exception("Failed to load lingua language detector.")
        _lingua_detector = None

    return _lingua_detector


def _get_model():
    """Return a cached fastText LID model."""
    global _model
    if _model is not None:
        return _model

    model_path = getattr(settings, "FASTTEXT_MODEL_PATH", "")
    if not model_path or not os.path.isfile(model_path):
        logger.warning(
            "fasttext model not found at '%s'. fastText detection will be skipped.",
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


def _get_afrolid_model():
    """Return a cached AfroLID local model (used when the microservice is absent)."""
    global _afrolid_model
    if _afrolid_model is not None:
        return _afrolid_model

    model_path = getattr(settings, "AFROLID_MODEL_PATH", "")
    if not model_path or not os.path.isdir(model_path):
        logger.warning(
            "AfroLID model directory not found at '%s'. AfroLID fallback will be skipped.",
            model_path,
        )
        return None

    try:
        from afrolid.main import classifier as AfrolidClassifier  # type: ignore[import]
    except Exception:
        logger.exception("AfroLID package is not available; fallback skipped.")
        return None

    try:
        _afrolid_model = AfrolidClassifier(logger, model_path)
        logger.info("AfroLID model loaded from %s", model_path)
    except Exception:
        logger.exception("Failed to load AfroLID model from %s.", model_path)
        _afrolid_model = None

    return _afrolid_model


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _clean_text(text: str) -> str:
    """Remove URLs and collapse whitespace."""
    text = re.sub(r"https?://\S+", "", text)
    text = re.sub(r"www\.\S+", "", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _normalize_afrolid_label(label: str) -> str:
    label = (label or "").strip().lower()
    if label in _SUPPORTED_LANGUAGES:
        return label
    return _AFROLID_TO_SUPPORTED.get(label, "unknown")


def _detect_with_lingua(text: str) -> tuple[str, float, dict]:
    """Run lingua and return (lang, confidence, flags)."""
    detector = _get_lingua_detector()
    if detector is None:
        return "unknown", 0.0, {"needs_language_review": False, "top_predictions": []}

    try:
        from lingua import Language  # type: ignore[import]

        detected = detector.detect_language_of(text)
        if detected is None:
            return "unknown", 0.0, {"needs_language_review": False, "top_predictions": []}

        lang_key = detected.name  # e.g. "SWAHILI"
        lang_code = _LINGUA_TO_SUPPORTED.get(lang_key, "unknown")

        confidence = round(detector.compute_language_confidence(text, detected), 4)

        # Collect both languages for transparency
        top_predictions = []
        for lng in (Language.ENGLISH, Language.SWAHILI):
            c = round(detector.compute_language_confidence(text, lng), 4)
            code = _LINGUA_TO_SUPPORTED.get(lng.name, "unknown")
            top_predictions.append((code, c))
        top_predictions.sort(key=lambda x: x[1], reverse=True)

        needs_review = confidence < _LINGUA_REVIEW_THRESHOLD
        return lang_code, confidence, {
            "needs_language_review": needs_review,
            "top_predictions": top_predictions,
        }
    except Exception:
        logger.exception("lingua detection failed.")
        return "unknown", 0.0, {"needs_language_review": False, "top_predictions": []}


def _detect_with_fasttext(text: str) -> tuple[str, float, dict]:
    """Run fastText and return best supported-language prediction."""
    model = _get_model()
    if model is None:
        return "unknown", 0.0, {"needs_language_review": False, "top_predictions": []}

    try:
        labels, probs = model.predict(text, k=5)
        predictions = [
            (label.replace("__label__", ""), round(float(prob), 4))
            for label, prob in zip(labels, probs)
        ]

        # Return the highest-confidence supported language from the top-5
        for lang, confidence in predictions:
            if lang in _SUPPORTED_LANGUAGES:
                needs_review = confidence < getattr(
                    settings, "LANGUAGE_CONFIDENCE_THRESHOLDS", {}
                ).get(lang, 0.85)
                return lang, confidence, {
                    "needs_language_review": needs_review,
                    "top_predictions": predictions,
                }

        # No supported language in top-5
        top_lang, top_confidence = predictions[0]
        return "other", top_confidence, {
            "needs_language_review": True,
            "top_predictions": predictions,
        }
    except Exception:
        logger.exception("fastText detection failed.")
        return "unknown", 0.0, {"needs_language_review": False, "top_predictions": []}


def _detect_with_afrolid(text: str) -> tuple[str, float, dict]:
    """Run AfroLID (microservice first, then local model) and return result."""
    service_url = getattr(settings, "AFROLID_SERVICE_URL", "")
    if service_url:
        try:
            import requests

            resp = requests.post(
                f"{service_url.rstrip('/')}/detect",
                json={"text": text},
                timeout=3.0,
            )
            if resp.status_code == 200:
                data = resp.json()
                lang = _normalize_afrolid_label(data.get("language", "unknown"))
                confidence = round(float(data.get("confidence", 0.0)), 4)
                top = data.get("top_predictions", [])
                return lang, confidence, {
                    "needs_language_review": data.get("needs_language_review", False),
                    "top_predictions": top,
                }
        except Exception:
            logger.exception("Failed to call AfroLID service at %s", service_url)

    local_model = _get_afrolid_model()
    review_flags: dict = {"needs_language_review": False, "top_predictions": []}

    if local_model is None:
        return "unknown", 0.0, review_flags

    try:
        results = local_model.classify(text, max_outputs=3)
    except Exception:
        logger.exception("AfroLID local classification failed.")
        return "unknown", 0.0, review_flags

    predictions: list[tuple[str, float]] = []
    for label, meta in results.items():
        mapped = _normalize_afrolid_label(label)
        score = round(float(meta.get("score", 0.0)) / 100.0, 4)
        predictions.append((mapped, score))

    review_flags["top_predictions"] = predictions
    for lang, confidence in predictions:
        if lang in _SUPPORTED_LANGUAGES:
            threshold = getattr(settings, "LANGUAGE_CONFIDENCE_THRESHOLD_TRANSLATION", 0.75)
            review_flags["needs_language_review"] = confidence < threshold
            return lang, confidence, review_flags

    review_flags["needs_language_review"] = True
    return "unknown", 0.0, review_flags


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def detect_language(
    text: str,
    ussd_language: Optional[str] = None,
) -> tuple[str, float, dict]:
    """
    Detect the BCP 47 language code of *text*.

    Detection order:
      1. lingua  (primary model -- always run on actual message text)
      2. fastText (secondary -- only if lingua is unavailable)
      3. AfroLID  (tertiary -- only if both above are unavailable)
      4. USSD language hint (fallback -- used only when models are uncertain)

    The USSD hint reflects the language the user *selected in the menu*, not
    necessarily the language they *typed in*. A user may pick English but write
    in Swahili. We therefore detect the actual text first and only fall back to
    the hint when the model confidence is below 0.80.

    Returns
    -------
    (language_code, confidence, review_flags_dict)
        language_code: 'en', 'sw', 'other', or 'unknown'.
        confidence: float in [0, 1].
        review_flags_dict: {'needs_language_review': bool, 'top_predictions': list}
    """
    # Threshold below which we consider a model result "uncertain" and allow
    # the USSD menu selection to act as a tiebreaker.
    _USSD_HINT_FALLBACK_THRESHOLD = 0.80

    review_flags: dict = {"needs_language_review": False, "top_predictions": []}

    # Clean and length-check
    text = _clean_text(text)
    if len(text) < 10:
        # Short text: trust USSD hint if available, else flag for review
        if ussd_language and ussd_language.strip() in _SUPPORTED_LANGUAGES:
            return ussd_language.strip(), 1.0, review_flags
        return "unknown", 0.50, {"needs_language_review": True, "top_predictions": []}

    text = text[:1000]

    # 1. lingua -- primary (always detect the actual message text)
    lingua_lang, lingua_conf, lingua_flags = _detect_with_lingua(text)
    if lingua_lang in _SUPPORTED_LANGUAGES and lingua_conf >= _USSD_HINT_FALLBACK_THRESHOLD:
        if ussd_language and ussd_language.strip() != lingua_lang:
            logger.info(
                "USSD menu selection '%s' overridden by lingua detection '%s' (conf=%.2f)",
                ussd_language,
                lingua_lang,
                lingua_conf,
            )
        return lingua_lang, lingua_conf, lingua_flags

    # 2. fastText -- secondary
    ft_lang, ft_conf, ft_flags = _detect_with_fasttext(text)
    if ft_lang in _SUPPORTED_LANGUAGES and ft_conf >= _USSD_HINT_FALLBACK_THRESHOLD:
        return ft_lang, ft_conf, ft_flags

    # 3. AfroLID -- tertiary
    afrolid_lang, afrolid_conf, afrolid_flags = _detect_with_afrolid(text)
    if afrolid_lang in _SUPPORTED_LANGUAGES and afrolid_conf >= _USSD_HINT_FALLBACK_THRESHOLD:
        return afrolid_lang, afrolid_conf, afrolid_flags

    # 4. All models uncertain -- fall back to USSD menu selection if available
    if ussd_language and ussd_language.strip() in _SUPPORTED_LANGUAGES:
        logger.info(
            "All models uncertain; using USSD menu hint '%s' as fallback.", ussd_language
        )
        review_flags["needs_language_review"] = True
        review_flags["top_predictions"] = lingua_flags.get("top_predictions", [])
        return ussd_language.strip(), 0.75, review_flags

    # Return best low-confidence model result if one exists
    if lingua_lang in _SUPPORTED_LANGUAGES:
        return lingua_lang, lingua_conf, lingua_flags
    if ft_lang in _SUPPORTED_LANGUAGES:
        return ft_lang, ft_conf, ft_flags
    if afrolid_lang in _SUPPORTED_LANGUAGES:
        return afrolid_lang, afrolid_conf, afrolid_flags

    # Nothing identified a supported language
    review_flags["needs_language_review"] = True
    top = lingua_flags.get("top_predictions") or ft_flags.get("top_predictions") or []
    review_flags["top_predictions"] = top
    best_conf = lingua_conf or ft_conf or afrolid_conf
    return "other", best_conf, review_flags
