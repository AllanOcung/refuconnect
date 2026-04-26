"""
Sentiment analysis using VADER for English and XLM-RoBERTa for other languages.

VADER is rule-based and works well on short, social-media-style text in English.
For non-English text, XLM-RoBERTa (cross-lingual multilingual model) is used.
The NLP pipeline translates to English first when possible for best accuracy.
"""
from __future__ import annotations

import logging
import re
import string
from typing import Optional

logger = logging.getLogger(__name__)

_vader_analyser = None
_xlm_analyser = None


def _get_vader_analyser():
    global _vader_analyser
    if _vader_analyser is None:
        try:
            from vaderSentiment.vaderSentiment import (  # type: ignore[import]
                SentimentIntensityAnalyzer,
            )

            _vader_analyser = SentimentIntensityAnalyzer()
        except Exception:
            logger.exception("Failed to initialise VADER sentiment analyser.")
    return _vader_analyser


def _get_xlm_analyser():
    global _xlm_analyser
    if _xlm_analyser is not None:
        return _xlm_analyser

    try:
        from transformers import pipeline  # type: ignore[import]

        _xlm_analyser = pipeline(
            "sentiment-analysis",
            model="xlm-roberta-base",
            device=-1,  # CPU
        )
        logger.info("XLM-RoBERTa sentiment analyser loaded.")
    except Exception:
        logger.exception("Failed to load XLM-RoBERTa sentiment analyser.")
        _xlm_analyser = None

    return _xlm_analyser


def _clean_text(text: str) -> str:
    """
    Clean text for sentiment analysis.

    Removes punctuation (except accented chars), collapses whitespace, strips.
    """
    # Remove punctuation (keep alphanumeric, spaces, accented chars)
    # Keep unicode letters but remove ASCII punctuation
    text = "".join(
        c if c not in string.punctuation else " " for c in text
    )
    # Collapse multiple whitespaces
    text = re.sub(r"\s+", " ", text)
    # Strip leading/trailing whitespace
    return text.strip()


def analyse_sentiment(
    text: str,
    language_code: Optional[str] = None,
    translation_failed: bool = False,
) -> tuple[Optional[object], float]:
    """
    Analyse the sentiment of *text*.

    Parameters
    ----------
    text:                Text to analyze (English preferred, but multi-language supported).
    language_code:       BCP 47 language code. If 'en' or None, uses VADER.
                        Otherwise uses XLM-RoBERTa.
    translation_failed:  If True (translation not available), use XLM-RoBERTa on original.

    Returns
    -------
    (Sentiment instance | None, confidence: float)
        The ``Sentiment`` ORM object matched from the database lookup table,
        and a confidence score in [0, 1].
        Returns ``(None, 0.0)`` if analysis is unavailable.
    """
    from apps.feedback.models import Sentiment  # deferred to avoid circular import

    if not text or not text.strip():
        return _lookup_sentiment("Uncertain"), 0.5

    # Clean text
    cleaned_text = _clean_text(text)

    # Use VADER for English
    if language_code is None or language_code == "en":
        analyser = _get_vader_analyser()
        if analyser is None:
            return None, 0.0

        scores = analyser.polarity_scores(cleaned_text)
        compound: float = scores["compound"]

        if compound >= 0.05:
            label = "Positive"
            confidence = min(compound, 1.0)
        elif compound <= -0.05:
            label = "Negative"
            confidence = min(abs(compound), 1.0)
        elif compound == 0.0:
            label = "Uncertain"
            confidence = 0.5
        else:
            # Near-neutral
            label = "Neutral"
            confidence = 1.0 - abs(compound)

        sentiment_obj = _lookup_sentiment(label)
        return sentiment_obj, round(confidence, 3)

    # Use XLM-RoBERTa for non-English
    analyser = _get_xlm_analyser()
    if analyser is None:
        logger.warning("XLM-RoBERTa analyser unavailable for language: %s", language_code)
        return None, 0.0

    try:
        result = analyser(cleaned_text[:512])  # Limit to 512 chars for model
        if not result:
            return _lookup_sentiment("Uncertain"), 0.5

        # result is a list: [{"label": "POSITIVE|NEGATIVE|NEUTRAL", "score": float}]
        output = result[0]
        label_raw = output.get("label", "NEUTRAL").upper()
        score = float(output.get("score", 0.5))

        # Map to Sentiment labels
        if label_raw == "POSITIVE":
            label = "Positive"
        elif label_raw == "NEGATIVE":
            label = "Negative"
        else:
            label = "Neutral"

        # Apply uncertain threshold: if confidence < 0.60, mark as uncertain
        if score < 0.60:
            label = "Uncertain"

        sentiment_obj = _lookup_sentiment(label)
        return sentiment_obj, round(score, 3)

    except Exception:
        logger.exception("XLM-RoBERTa sentiment analysis failed for language: %s", language_code)
        return None, 0.0


def _lookup_sentiment(label: str):
    """Return the Sentiment ORM object for *label*, or None if not found."""
    try:
        from apps.feedback.models import Sentiment

        return Sentiment.objects.get(sentiment_label=label)
    except Exception:
        logger.warning("Sentiment lookup failed for label '%s'.", label)
        return None
