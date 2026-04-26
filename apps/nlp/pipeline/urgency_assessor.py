"""
Urgency assessment using a keyword-weighted rule engine with multi-signal support.

A hybrid approach is used:
  - Rule 1: Scan for explicit high-urgency keywords
  - Rule 2: Scan for medium-urgency keywords
  - Rule 3: Combine category and sentiment signals
  - Default to 'Low'
"""
from __future__ import annotations

import re
from typing import Optional

# ── Keyword lexicons ──────────────────────────────────────────────────────────

_HIGH_URGENCY_PATTERNS = re.compile(
    r"\b("
    r"urgent|urgency|emergency|dying|died|dead|death|killed|attack|attacked|"
    r"violence|rape|sexual.assault|abused|"
    r"flood|fire|collapsed|"
    r"critical|immediate.help|help.now|sos|"
    r"danger|threat|threatened|shooting|bombing|"
    r"child.abuse|trafficking|kidnap|"
    r"no.food|starving|starvation|"
    r"haemorrhag|hemorrhag|miscarriage|"
    r"unconscious|not.breathing"
    r")\b",
    re.IGNORECASE,
)

_MEDIUM_URGENCY_PATTERNS = re.compile(
    r"\b("
    r"sick|illness|fever|malaria|cholera|hospital|clinic|medicine|"
    r"missing|lost|stolen|"
    r"problem|issue|complain|complaint|concern|"
    r"hungry|thirsty|water.problem|no.water|no.shelter|"
    r"broken|damaged|leaking|"
    r"harassment|bribery|corruption|"
    r"delayed|denied|refused"
    r")\b",
    re.IGNORECASE,
)

# Categories that signal high urgency when combined with negative sentiment
_HIGH_URGENCY_CATEGORIES = {"Health", "Violence", "Exploitation"}


def assess_urgency(
    text: str,
    category: Optional[str] = None,
    sentiment: Optional[str] = None,
) -> tuple[str, str]:
    """
    Classify the urgency of *text* as 'High', 'Medium', or 'Low'.

    Parameters
    ----------
    text:     English text (translate before calling for best accuracy).
    category: Optional category from topic classification.
    sentiment: Optional sentiment label ('Positive', 'Negative', 'Neutral', 'Uncertain').

    Returns
    -------
    (urgency_level, urgency_rule)
        urgency_level: One of 'High', 'Medium', 'Low'
        urgency_rule: Description of which rule triggered
                     (e.g. 'keyword:death' or 'category+sentiment:Health+Negative' or 'default')
    """
    if not text:
        return "Low", "default"

    # Rule 1: High-urgency keywords
    high_match = _HIGH_URGENCY_PATTERNS.search(text)
    if high_match:
        matched_keyword = high_match.group(0)
        return "High", f"keyword:{matched_keyword}"

    # Rule 2: Medium-urgency keywords
    medium_match = _MEDIUM_URGENCY_PATTERNS.search(text)
    if medium_match:
        matched_keyword = medium_match.group(0)
        return "Medium", f"keyword:{matched_keyword}"

    # Rule 3: Category + Sentiment combination
    if category and sentiment:
        if category in _HIGH_URGENCY_CATEGORIES and sentiment == "Negative":
            return "High", f"category+sentiment:{category}+{sentiment}"

    return "Low", "default"
