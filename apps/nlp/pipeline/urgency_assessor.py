"""
Urgency assessment using a keyword-weighted rule engine.

A hybrid approach is used: first scan for explicit high-urgency signals,
then medium-urgency signals, and default to 'Low'.
"""
from __future__ import annotations

import re

# ── Keyword lexicons ──────────────────────────────────────────────────────────

_HIGH_URGENCY_PATTERNS = re.compile(
    r"\b("
    r"urgent|emergency|dying|dead|death|killed|attack|attacked|"
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
    r"problem|issue|complain|concern|"
    r"hungry|thirsty|water.problem|no.water|no.shelter|"
    r"broken|damaged|leaking|"
    r"harassment|bribery|corruption|"
    r"delayed|denied|refused"
    r")\b",
    re.IGNORECASE,
)


def assess_urgency(text: str) -> str:
    """
    Classify the urgency of *text* as 'High', 'Medium', or 'Low'.

    Parameters
    ----------
    text: English text (translate before calling for best accuracy).

    Returns
    -------
    One of 'High', 'Medium', 'Low'.
    """
    if not text:
        return "Low"

    if _HIGH_URGENCY_PATTERNS.search(text):
        return "High"

    if _MEDIUM_URGENCY_PATTERNS.search(text):
        return "Medium"

    return "Low"
