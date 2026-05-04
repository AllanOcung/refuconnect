"""C-10 sentiment analysis.

English text uses VADER (rule-based, fast). Non-English text uses
CardiffNLP XLM-RoBERTa sentiment model.
"""
from __future__ import annotations

import logging
import re
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
            model="cardiffnlp/twitter-xlm-roberta-base-sentiment",
            device=-1,
        )
        logger.info("CardiffNLP XLM-RoBERTa sentiment analyser loaded.")
    except Exception:
        logger.exception("Failed to load CardiffNLP XLM-RoBERTa sentiment analyser.")
        _xlm_analyser = None

    return _xlm_analyser


def _clean_text(text: str) -> str:
    """
    Clean text for sentiment analysis.

    Strips excessive punctuation runs, collapses whitespace, and trims edges.
    """
    text = re.sub(r"([!?.,;:])\1+", r"\1", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _map_xlm_label(label_raw: str) -> str:
    mapping = {
        "LABEL_0": "Negative",
        "LABEL_1": "Neutral",
        "LABEL_2": "Positive",
        "NEGATIVE": "Negative",
        "NEUTRAL": "Neutral",
        "POSITIVE": "Positive",
    }
    return mapping.get((label_raw or "").upper(), "Neutral")


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
    if not text or not text.strip():
        return _lookup_sentiment("Uncertain"), 0.5

    cleaned_text = _clean_text(text)
    if not cleaned_text:
        return _lookup_sentiment("Uncertain"), 0.5

    use_vader = language_code in (None, "en") and not translation_failed

    if use_vader:
        analyser = _get_vader_analyser()
        if analyser is None:
            return None, 0.0

        scores = analyser.polarity_scores(cleaned_text)
        compound: float = scores["compound"]

        if compound >= 0.05:
            label = "Positive"
        elif compound <= -0.05:
            label = "Negative"
        else:
            label = "Neutral"
        confidence = max(
            float(scores.get("pos", 0.0)),
            float(scores.get("neu", 0.0)),
            float(scores.get("neg", 0.0)),
        )

        if confidence < 0.60:
            label = "Uncertain"

        sentiment_obj = _lookup_sentiment(label)
        return sentiment_obj, round(confidence, 3)

    analyser = _get_xlm_analyser()
    if analyser is None:
        logger.warning("XLM-RoBERTa analyser unavailable for language: %s", language_code)
        return None, 0.0

    try:
        result = analyser(cleaned_text[:512])
        if not result:
            return _lookup_sentiment("Uncertain"), 0.5

        output = result[0]
        label_raw = str(output.get("label", "LABEL_1"))
        score = float(output.get("score", 0.0))
        label = _map_xlm_label(label_raw)

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


def analyse_feedback_sentiment(
    feedback,
    *,
    translation_failed: bool = False,
) -> tuple[Optional[object], float, dict[str, bool]]:
    """
    Analyse and assign sentiment on a Feedback-like object without saving.

    Returns:
        (sentiment_obj, confidence, context)
    """
    context: dict[str, bool] = {"sentiment_used_untranslated_text": False}

    translated_text = (feedback.message_text_en or "").strip()
    original_text = (feedback.message_text or "").strip()
    language = (feedback.language or "unknown").lower()

    if translated_text and translation_failed:
        text_for_sentiment = original_text
        language_code = language
        context["sentiment_used_untranslated_text"] = True
    elif language == "en":
        text_for_sentiment = translated_text or original_text
        language_code = "en"
    elif translated_text and not translation_failed:
        text_for_sentiment = translated_text
        language_code = "en"
    else:
        text_for_sentiment = original_text
        language_code = language

    sentiment_obj, confidence = analyse_sentiment(
        text_for_sentiment,
        language_code=language_code,
        translation_failed=translation_failed and language_code != "en",
    )

    feedback.sentiment = sentiment_obj
    feedback.sentiment_confidence = confidence
    return sentiment_obj, confidence, context
