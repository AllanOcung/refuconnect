from __future__ import annotations

import logging
import re

from django.conf import settings
from transformers import pipeline as hf_pipeline
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

logger = logging.getLogger(__name__)

_XLM_MODEL: str = getattr(
    settings, "SENTIMENT_MODEL", "cardiffnlp/twitter-xlm-roberta-base-sentiment"
)
_HF_CACHE: str = getattr(settings, "HUGGINGFACE_CACHE_DIR", "models/huggingface/")
_CONFIDENCE_THRESHOLD: float = float(
    getattr(settings, "NLP_CONFIDENCE_THRESHOLD_SENTIMENT", 0.60)
)

_LABEL_MAP: dict[str, str] = {
    "LABEL_0": "Negative",
    "LABEL_1": "Neutral",
    "LABEL_2": "Positive",
}

_PUNCT_RE = re.compile(r"([!?.]){3,}")
_SPACE_RE = re.compile(r"\s+")


def _clean(text: str) -> str:
    text = _PUNCT_RE.sub(r"\1", text)
    return _SPACE_RE.sub(" ", text).strip()


class SentimentAnalyser:

    _vader: SentimentIntensityAnalyzer | None = None
    _xlm: object | None = None

    def __init__(self) -> None:
        if SentimentAnalyser._vader is None:
            try:
                SentimentAnalyser._vader = SentimentIntensityAnalyzer()
                logger.debug("SentimentAnalyser: VADER initialised.")
            except Exception as exc:
                logger.critical("Failed to initialise VADER: %s", exc)
                raise

        if SentimentAnalyser._xlm is None:
            logger.info("SentimentAnalyser: loading XLM-RoBERTa model %s.", _XLM_MODEL)
            try:
                SentimentAnalyser._xlm = hf_pipeline(
                    "text-classification",
                    model=_XLM_MODEL,
                    cache_dir=_HF_CACHE,
                    device=-1,
                )
            except Exception as exc:
                logger.critical(
                    "Failed to load XLM sentiment model %s: %s", _XLM_MODEL, exc
                )
                raise

    # ── Classifiers ──────────────────────────────────────────────────────────

    def _classify_vader(self, text: str) -> tuple[str, float]:
        """
        Use VADER compound score for the sentiment label.
        Use max(pos, neu, neg) for confidence, per spec section C-10.
        """
        scores = SentimentAnalyser._vader.polarity_scores(text)
        compound: float = scores["compound"]

        if compound >= 0.05:
            label = "Positive"
        elif compound <= -0.05:
            label = "Negative"
        else:
            label = "Neutral"

        # Confidence = the winning component score (max of pos/neu/neg)
        confidence = round(max(scores["pos"], scores["neu"], scores["neg"]), 4)
        return label, confidence

    def _classify_xlm(self, text: str) -> tuple[str, float]:
        result = SentimentAnalyser._xlm(text[:512], truncation=True)[0]
        label = _LABEL_MAP.get(result["label"], "Neutral")
        return label, float(result["score"])

    # ── DB lookup ─────────────────────────────────────────────────────────────

    def _get_sentiment_obj(self, label: str):
        """Return the Sentiment ORM object for *label*, or None if not found."""
        try:
            from apps.feedback.models import Sentiment
            return Sentiment.objects.get(sentiment_label=label)
        except Exception as exc:
            logger.warning("Sentiment lookup failed for label '%s': %s", label, exc)
            return None

    # ── Public interface ──────────────────────────────────────────────────────

    def process(self, record, context: dict) -> tuple:
        """
        Determine sentiment for *record*. Mutates record in place; does NOT save.

        Prefers ``message_text_en`` unless translation is known to have failed.
        Falls back to raw ``message_text`` for non-English records and routes
        them through XLM-RoBERTa.
        """
        feedback_id = record.pk
        translation_ok = not context.get("translation_failed", False)
        use_translated = bool(record.message_text_en) and translation_ok

        text = _clean((record.message_text_en if use_translated else record.message_text) or "")

        if not text:
            logger.warning(
                "feedback_id=%s: empty text for sentiment analysis; marking Uncertain.",
                feedback_id,
            )
            record.sentiment_id = getattr(self._get_sentiment_obj("Uncertain"), "pk", None)
            record.sentiment_confidence = 0.0
            context["needs_sentiment_review"] = True
            return record, context

        if not use_translated and record.message_text_en:
            context["sentiment_on_untranslated"] = True

        is_english = record.language == "en" or (
            use_translated and record.language not in (None, "unknown", "other")
        )

        try:
            if is_english:
                label, confidence = self._classify_vader(text)
            else:
                label, confidence = self._classify_xlm(text)
        except Exception as exc:
            logger.error(
                "feedback_id=%s: sentiment classification failed: %s",
                feedback_id,
                exc,
                exc_info=True,
            )
            return record, context

        if confidence < _CONFIDENCE_THRESHOLD:
            logger.info(
                "feedback_id=%s: low sentiment confidence %.4f; marking Uncertain.",
                feedback_id,
                confidence,
            )
            label = "Uncertain"
            context["needs_sentiment_review"] = True

        sentiment_obj = self._get_sentiment_obj(label)
        if sentiment_obj is not None:
            record.sentiment_id = sentiment_obj.pk
            record.sentiment_confidence = round(confidence, 4)
        else:
            logger.error(
                "feedback_id=%s: could not resolve Sentiment record for '%s'.",
                feedback_id,
                label,
            )

        logger.debug(
            "feedback_id=%s: sentiment=%s confidence=%.4f", feedback_id, label, confidence
        )
        return record, context