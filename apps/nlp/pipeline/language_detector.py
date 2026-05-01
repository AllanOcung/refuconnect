"""
Language detection using fastText with AfroLID fallback.

fastText is loaded lazily on first use and cached for the lifetime of the
worker process. If the fastText model is missing or returns low confidence,
AfroLID is attempted as a fallback. If both models are unavailable or fail,
the detector falls back to returning ``('unknown', 0.0, {...})``.
"""
from __future__ import annotations

import logging
import os
import re
from typing import Optional

from django.conf import settings

logger = logging.getLogger(__name__)

_model = None
_afrolid_model = None

# Supported languages for RefuConnect
_SUPPORTED_LANGUAGES = {"en", "sw"}

_AFROLID_TO_SUPPORTED = {
    "eng": "en",
    "swa": "sw",
    "swh": "sw",
    "swc": "sw",
}

# Lightweight lexical hints for cases where fastText is uncertain.
_SWAHILI_HINT_WORDS = {
    "aibu",
    "afya",
    "habari",
    "hali",
    "hewa",
    "kazi",
    "kaka",
    "kijiji",
    "kununua",
    "leo",
    "mimi",
    "ndio",
    "nzuri",
    "pole",
    "sana",
    "sokoni",
    "tafadhali",
    "wewe",
    "ya",
    "yako",
    "yangu",
    "yao",
    "za",
    "zuri",
    "chakula",
    "dawa",
    "maji",
    "msaada",
    "mtu",
    "nyumba",
    "sijambo",
    "sisi",
    "una",
    "wana",
    "wanao",
    "wapi",
    "watu",
    "zote",
    "nina",
    "ninaenda",
    "nime",
}

_ENGLISH_HINT_WORDS = {
    "and",
    "are",
    "been",
    "can",
    "for",
    "from",
    "hello",
    "help",
    "i",
    "is",
    "need",
    "no",
    "not",
    "please",
    "there",
    "the",
    "to",
    "water",
    "with",
    "you",
}


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


def _get_afrolid_model():
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


def _clean_text(text: str) -> str:
    """Clean text: remove URLs, collapse whitespace, strip."""
    # Remove URLs (http, https, www patterns)
    text = re.sub(r"https?://\S+", "", text)
    text = re.sub(r"www\.\S+", "", text)
    # Collapse multiple whitespaces to single space
    text = re.sub(r"\s+", " ", text)
    # Strip leading/trailing whitespace
    return text.strip()


def _heuristic_language_score(text: str) -> tuple[str, float, dict]:
    """Use simple word hints to catch obvious English or Swahili messages."""
    tokens = re.findall(r"[a-z']+", text.lower())
    if not tokens:
        return "unknown", 0.0, {"needs_language_review": False, "top_predictions": []}

    sw_hits = sum(token in _SWAHILI_HINT_WORDS for token in tokens)
    en_hits = sum(token in _ENGLISH_HINT_WORDS for token in tokens)

    if sw_hits == 0 and en_hits == 0:
        return "unknown", 0.0, {"needs_language_review": False, "top_predictions": []}

    if sw_hits >= en_hits and sw_hits >= 2:
        confidence = min(0.84, 0.55 + (0.08 * sw_hits) + (0.02 * len(tokens)))
        confidence = round(confidence, 4)
        return "sw", confidence, {
            "needs_language_review": True,
            "top_predictions": [("sw", confidence), ("en", round(max(0.0, 1.0 - confidence), 4))],
        }

    if en_hits > sw_hits and en_hits >= 2:
        confidence = min(0.84, 0.55 + (0.08 * en_hits) + (0.02 * len(tokens)))
        confidence = round(confidence, 4)
        return "en", confidence, {
            "needs_language_review": True,
            "top_predictions": [("en", confidence), ("sw", round(max(0.0, 1.0 - confidence), 4))],
        }

    return "unknown", 0.0, {"needs_language_review": False, "top_predictions": []}


def _normalize_afrolid_label(label: str) -> str:
    label = (label or "").strip().lower()
    if label in _SUPPORTED_LANGUAGES:
        return label
    return _AFROLID_TO_SUPPORTED.get(label, "unknown")


def _detect_with_afrolid(text: str) -> tuple[str, float, dict]:
    """Run AfroLID and map its output to RefuConnect's supported codes."""
    # Prefer remote afrolid microservice if configured, to isolate heavy deps.
    service_url = getattr(settings, "AFROLID_SERVICE_URL", "")
    if service_url:
        try:
            import requests

            resp = requests.post(f"{service_url.rstrip('/')}/detect", json={"text": text}, timeout=3.0)
            if resp.status_code == 200:
                data = resp.json()
                lang = data.get("language", "unknown")
                confidence = float(data.get("confidence", 0.0))
                top = data.get("top_predictions", [])
                return _normalize_afrolid_label(lang), round(confidence, 4), {
                    "needs_language_review": data.get("needs_language_review", False),
                    "top_predictions": top,
                }
        except Exception:
            logger.exception("Failed to call AfroLID service at %s", service_url)

    model = _get_afrolid_model()
    review_flags = {
        "needs_language_review": False,
        "top_predictions": [],
    }

    if model is None:
        return "unknown", 0.0, review_flags

    try:
        results = model.classify(text, max_outputs=3)
    except Exception:
        logger.exception("AfroLID classification failed for text snippet.")
        return "unknown", 0.0, review_flags

    predictions: list[tuple[str, float]] = []
    for label, meta in results.items():
        mapped_label = _normalize_afrolid_label(label)
        score = float(meta.get("score", 0.0)) / 100.0
        predictions.append((mapped_label, round(score, 4)))

    review_flags["top_predictions"] = predictions
    for lang, confidence in predictions:
        if lang in _SUPPORTED_LANGUAGES:
            if confidence < getattr(settings, "LANGUAGE_CONFIDENCE_THRESHOLD_TRANSLATION", 0.85):
                review_flags["needs_language_review"] = True
            return lang, confidence, review_flags

    review_flags["needs_language_review"] = True
    return "unknown", 0.0, review_flags


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
        language_code: BCP 47 tag (e.g. 'en', 'sw') or 'unknown'.
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

    # Limit to 1000 characters to cap processing time
    text = text[:1000]

    confidence_thresholds = getattr(settings, "LANGUAGE_CONFIDENCE_THRESHOLDS", {})

    if model is not None:
        try:
            labels, probs = model.predict(text, k=3)
            predictions = []
            for label, prob in zip(labels, probs):
                lang = label.replace("__label__", "")
                confidence = float(prob)
                predictions.append((lang, round(confidence, 4)))

            review_flags["top_predictions"] = predictions
            top_lang, top_confidence = predictions[0]

            # Respect top-1 prediction only; lower-ranked labels should not override it.
            if top_lang in _SUPPORTED_LANGUAGES:
                threshold = confidence_thresholds.get(top_lang, 0.85)
                if top_confidence >= threshold:
                    return top_lang, top_confidence, review_flags

                # FastText is uncertain, so fall through to AfroLID.
                review_flags["needs_language_review"] = True
                afrolid_lang, afrolid_confidence, afrolid_flags = _detect_with_afrolid(text)
                if afrolid_lang in _SUPPORTED_LANGUAGES:
                    afrolid_flags["top_predictions"] = afrolid_flags.get("top_predictions", []) or review_flags["top_predictions"]
                    afrolid_flags["needs_language_review"] = True
                    return afrolid_lang, afrolid_confidence, afrolid_flags

                heuristic_lang, heuristic_confidence, heuristic_flags = _heuristic_language_score(text)
                if heuristic_lang in _SUPPORTED_LANGUAGES:
                    heuristic_flags["top_predictions"] = heuristic_flags.get("top_predictions", []) or review_flags["top_predictions"]
                    return heuristic_lang, heuristic_confidence, heuristic_flags

                return top_lang, top_confidence, review_flags

            # FastText top-1 is unsupported, so try AfroLID next.
            afrolid_lang, afrolid_confidence, afrolid_flags = _detect_with_afrolid(text)
            if afrolid_lang in _SUPPORTED_LANGUAGES:
                afrolid_flags["top_predictions"] = afrolid_flags.get("top_predictions", []) or predictions
                return afrolid_lang, afrolid_confidence, afrolid_flags

            review_flags["needs_language_review"] = True
            return "unknown", 0.0, review_flags

        except Exception:
            logger.exception("Language detection failed for text snippet.")

    # FastText unavailable or failed, so try AfroLID first and then heuristics.
    afrolid_lang, afrolid_confidence, afrolid_flags = _detect_with_afrolid(text)
    if afrolid_lang in _SUPPORTED_LANGUAGES:
        return afrolid_lang, afrolid_confidence, afrolid_flags

    heuristic_lang, heuristic_confidence, heuristic_flags = _heuristic_language_score(text)
    if heuristic_lang in _SUPPORTED_LANGUAGES:
        return heuristic_lang, heuristic_confidence, heuristic_flags

    return "unknown", 0.0, review_flags
