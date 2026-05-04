"""
C-09 UrgencyAssessor — rule-based urgency classification.

Rules applied in strict priority order (first match wins):
  Rule 1: High-urgency keyword match  → urgency_level='High'
  Rule 2: Medium-urgency keyword match → urgency_level='Medium'
  Rule 3: Negative sentiment + Protection & Safety or Healthcare category
          → urgency_level='Medium'  (only fires during reprocessing after
            SentimentAnalyser has run; safe to skip on first pass)
  Rule 4: Default → urgency_level='Low'

The matched rule is stored in urgency_rule / context dict for audit logging.
"""
from __future__ import annotations

import logging
import re
from typing import Optional

logger = logging.getLogger(__name__)

# ── Keyword lexicons (compiled once at module import) ─────────────────────────
# C-09 exact keyword list — word-boundary matching prevents false positives
# (e.g. "fire" won't match "Firefox"; "attack" won't match "attacked" is fine
#  since the stem matches under \b).

_HIGH_URGENCY_PATTERNS = re.compile(
    r"\b(?:"
    r"emergency|violence|attack|rape|assault"
    r"|death|died|dying|killed"
    r"|critically ill|no food for days|starving"
    r"|flood|fire|burning"
    r"|threat|armed|weapon"
    r"|abduction|kidnap(?:ped|ping)?|torture"
    r"|sexual abuse|child abuse"
    r"|suicide|collapsed|unconscious"
    r")\b",
    re.IGNORECASE,
)

_MEDIUM_URGENCY_PATTERNS = re.compile(
    r"\b(?:"
    r"sick|injured|broken|unsafe"
    r"|no medicine|missing|closed"
    r"|refused|denied|delayed|damaged|blocked|complaint"
    r")\b",
    re.IGNORECASE,
)

# DB Category names checked in Rule 3 (must match Category.category_name seeds)
_RULE3_CATEGORIES = {"Protection & Safety", "Healthcare"}
_NEGATIVE_SENTIMENT = "Negative"


# ── Internal helpers ──────────────────────────────────────────────────────────

def _run_keyword_rules(text: str) -> tuple[Optional[str], Optional[str]]:
    """Apply Rules 1 and 2 to *text*. Returns (level, rule) or (None, None)."""
    m = _HIGH_URGENCY_PATTERNS.search(text)
    if m:
        return "High", f"keyword:{m.group(0).lower()}"
    m = _MEDIUM_URGENCY_PATTERNS.search(text)
    if m:
        return "Medium", f"keyword:{m.group(0).lower()}"
    return None, None


def _sentiment_label(feedback) -> Optional[str]:
    """Safely extract the sentiment label string from a Feedback object."""
    sentiment = getattr(feedback, "sentiment", None)
    if sentiment is None:
        return None
    # sentiment may be a FK Sentiment object or a plain string
    return getattr(sentiment, "sentiment_name", None) or str(sentiment)


# ── Public API ────────────────────────────────────────────────────────────────

def assess_feedback_urgency(feedback) -> tuple[str, str, dict]:
    """
    Assess urgency of a Feedback record (C-09 primary entry point).

    Reads ``message_text_en`` (falls back to ``message_text``), the related
    ``feedback_categories``, and the ``sentiment`` FK to apply all four rules.

    Parameters
    ----------
    feedback : Feedback model instance

    Returns
    -------
    (urgency_level, urgency_rule, context)
        urgency_level : 'High', 'Medium', or 'Low'
        urgency_rule  : audit string, e.g. 'keyword:fire' or
                        'sentiment+category:Protection & Safety'
        context       : dict with full rule details for consumer logging
    """
    text = (
        getattr(feedback, "message_text_en", None)
        or getattr(feedback, "message_text", None)
        or ""
    ).strip()

    # Rules 1 & 2 — keyword scan
    if text:
        level, rule = _run_keyword_rules(text)
        if level:
            ctx = {"urgency_rule": rule, "source": "keyword", "text_sample": text[:120]}
            logger.debug("Urgency=%s via %s (feedback_id=%s)", level, rule,
                         getattr(feedback, "feedback_id", "?"))
            return level, rule, ctx

    # Rule 3 — negative sentiment + high-risk category
    # (only active during reprocessing after SentimentAnalyser has run)
    sentiment = _sentiment_label(feedback)
    if sentiment == _NEGATIVE_SENTIMENT:
        try:
            assigned = set(
                feedback.feedback_categories.values_list(
                    "category__category_name", flat=True
                )
            )
        except Exception:
            assigned = set()

        matched = _RULE3_CATEGORIES & assigned
        if matched:
            cat_str = ", ".join(sorted(matched))
            rule = f"sentiment+category:{cat_str}"
            ctx = {"urgency_rule": rule, "source": "rule3",
                   "matched_categories": list(matched)}
            logger.debug("Urgency=Medium via %s (feedback_id=%s)", rule,
                         getattr(feedback, "feedback_id", "?"))
            return "Medium", rule, ctx

    # Rule 4 — default
    return "Low", "default", {"urgency_rule": "default", "source": "default"}


def assess_urgency(
    text: str,
    category: Optional[str] = None,
    sentiment: Optional[str] = None,
) -> tuple[str, str]:
    """
    Lightweight text-based API kept for unit tests and ad-hoc callers.

    Applies Rules 1–3.  For Rule 3, pass the DB category name
    (e.g. ``'Healthcare'`` or ``'Protection & Safety'``) and
    ``sentiment='Negative'``.

    Returns
    -------
    (urgency_level, urgency_rule)
    """
    if not text:
        return "Low", "default"

    level, rule = _run_keyword_rules(text)
    if level:
        return level, rule

    # Rule 3
    if sentiment == _NEGATIVE_SENTIMENT and category in _RULE3_CATEGORIES:
        rule = f"sentiment+category:{category}"
        return "Medium", rule

    return "Low", "default"
