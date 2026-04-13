"""
Sentiment analysis using VADER.

VADER is rule-based and works well on short, social-media-style text in English.
For non-English text the NLP pipeline translates to English first.
"""
from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)

_analyser = None


def _get_analyser():
    global _analyser
    if _analyser is None:
        try:
            from vaderSentiment.vaderSentiment import (  # type: ignore[import]
                SentimentIntensityAnalyzer,
            )

            _analyser = SentimentIntensityAnalyzer()
        except Exception:
            logger.exception("Failed to initialise VADER sentiment analyser.")
    return _analyser


def analyse_sentiment(text: str) -> tuple[Optional[object], float]:
    """
    Analyse the sentiment of *text* (expected to be English).

    Returns
    -------
    (Sentiment instance | None, confidence: float)
        The ``Sentiment`` ORM object matched from the database lookup table,
        and a confidence score in [0, 1].
        Returns ``(None, 0.0)`` if VADER is unavailable.
    """
    from apps.feedback.models import Sentiment  # deferred to avoid circular import

    analyser = _get_analyser()
    if analyser is None:
        return None, 0.0

    if not text or not text.strip():
        return _lookup_sentiment("Uncertain"), 0.5

    scores = analyser.polarity_scores(text)
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
        # Near-neutral — small absolute compound value
        label = "Neutral"
        confidence = 1.0 - abs(compound)

    sentiment_obj = _lookup_sentiment(label)
    return sentiment_obj, round(confidence, 3)


def _lookup_sentiment(label: str):
    """Return the Sentiment ORM object for *label*, or None if not found."""
    try:
        from apps.feedback.models import Sentiment

        return Sentiment.objects.get(sentiment_label=label)
    except Exception:
        logger.warning("Sentiment lookup failed for label '%s'.", label)
        return None
