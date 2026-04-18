from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)


_HIGH_SINGLE = [
    "emergency", "violence", "attack", "attacked", "rape", "assault",
    "death", "died", "dying", "killed", "starving", "starvation",
    "flood", "fire", "burning", "threat", "threatened", "armed", "weapon",
    "abduction", "kidnap", "trafficking", "torture", "suicide",
    "collapsed", "unconscious", "shooting", "bombing", "danger",
    "haemorrhag", "hemorrhag", "miscarriage", "sos",
]

_HIGH_PHRASES = [
    "sexual abuse", "sexual assault", "child abuse", "no food",
    "no food for days", "critically ill", "immediate help",
    "help now", "not breathing",
]

_MEDIUM_SINGLE = [
    "sick", "injured", "illness", "fever", "malaria", "cholera",
    "hospital", "clinic", "medicine", "missing", "unsafe", "broken",
    "damaged", "blocked", "delayed", "denied", "refused", "closed",
    "complaint", "concern", "harassment", "bribery", "corruption",
    "hungry", "thirsty", "stolen", "leaking",
]

_MEDIUM_PHRASES = [
    "no medicine", "no water", "no shelter", "water problem",
]

_HIGH_URGENCY = "High"
_MEDIUM_URGENCY = "Medium"
_LOW_URGENCY = "Low"


#  Pattern compilation 

def _single_pattern(tokens: list[str]) -> re.Pattern:
    """Compile a single alternation pattern for a list of single-word tokens."""
    alternation = "|".join(re.escape(t) for t in tokens)
    return re.compile(r"\b(?:" + alternation + r")\b", re.IGNORECASE)


def _phrase_patterns(phrases: list[str]) -> list[tuple[str, re.Pattern]]:
    """
    Compile one word-boundary pattern per phrase.
    Whitespace in phrases is replaced with ``\\s+`` to tolerate varied spacing.
    """
    result = []
    for phrase in phrases:
        escaped = re.escape(phrase).replace(r"\ ", r"\s+")
        result.append((phrase, re.compile(r"\b" + escaped + r"\b", re.IGNORECASE)))
    return result


class UrgencyAssessor:
    

    _high_single: re.Pattern | None = None
    _high_phrases: list[tuple[str, re.Pattern]] = []
    _medium_single: re.Pattern | None = None
    _medium_phrases: list[tuple[str, re.Pattern]] = []
    _initialised: bool = False

    def __init__(self) -> None:
        if UrgencyAssessor._initialised:
            return
        UrgencyAssessor._high_single = _single_pattern(_HIGH_SINGLE)
        UrgencyAssessor._high_phrases = _phrase_patterns(_HIGH_PHRASES)
        UrgencyAssessor._medium_single = _single_pattern(_MEDIUM_SINGLE)
        UrgencyAssessor._medium_phrases = _phrase_patterns(_MEDIUM_PHRASES)
        UrgencyAssessor._initialised = True
        logger.debug(
            "UrgencyAssessor: compiled patterns for %d high and %d medium keywords.",
            len(_HIGH_SINGLE) + len(_HIGH_PHRASES),
            len(_MEDIUM_SINGLE) + len(_MEDIUM_PHRASES),
        )

    #  Public interface 

    def process(self, record, context: dict) -> tuple:
        """
        Evaluate urgency for *record*. Mutates record in place; does NOT save.
        """
        feedback_id = record.pk
        text: str = record.message_text_en or record.message_text or ""

        if not text.strip():
            record.urgency_level = _LOW_URGENCY
            context["urgency_rule"] = "default:empty"
            return record, context

        # Rule 1 – High urgency: phrases first (more specific), then single tokens.
        for phrase, pattern in UrgencyAssessor._high_phrases:
            if pattern.search(text):
                record.urgency_level = _HIGH_URGENCY
                context["urgency_rule"] = f"keyword:{phrase}"
                logger.info(
                    "feedback_id=%s: HIGH urgency — matched phrase '%s'.",
                    feedback_id,
                    phrase,
                )
                return record, context

        m = UrgencyAssessor._high_single.search(text)
        if m:
            record.urgency_level = _HIGH_URGENCY
            context["urgency_rule"] = f"keyword:{m.group(0).lower()}"
            logger.info(
                "feedback_id=%s: HIGH urgency — matched keyword '%s'.",
                feedback_id,
                m.group(0).lower(),
            )
            return record, context

        # Rule 2 – Medium urgency: phrases first, then single tokens.
        for phrase, pattern in UrgencyAssessor._medium_phrases:
            if pattern.search(text):
                record.urgency_level = _MEDIUM_URGENCY
                context["urgency_rule"] = f"keyword:{phrase}"
                logger.info(
                    "feedback_id=%s: MEDIUM urgency — matched phrase '%s'.",
                    feedback_id,
                    phrase,
                )
                return record, context

        m = UrgencyAssessor._medium_single.search(text)
        if m:
            record.urgency_level = _MEDIUM_URGENCY
            context["urgency_rule"] = f"keyword:{m.group(0).lower()}"
            logger.info(
                "feedback_id=%s: MEDIUM urgency — matched keyword '%s'.",
                feedback_id,
                m.group(0).lower(),
            )
            return record, context

        # Rule 3 – Compound signal (reprocessing path only).
        # SentimentAnalyser runs before this step in the live pipeline, but
        # sentiment_id may be absent on a record's first pass.
        if record.sentiment_id is not None:
            negative = (
                hasattr(record, "sentiment")
                and record.sentiment.sentiment_label == "Negative"
            )
            high_risk = {"Protection/Safety", "Health"}
            assigned = {
                fc.category.category_name
                for fc in record.feedbackcategory_set.select_related("category")
            }
            if negative and assigned & high_risk:
                record.urgency_level = _MEDIUM_URGENCY
                context["urgency_rule"] = "sentiment+category"
                logger.info(
                    "feedback_id=%s: MEDIUM urgency — negative sentiment + high-risk category.",
                    feedback_id,
                )
                return record, context

        # Rule 4 – Default.
        record.urgency_level = _LOW_URGENCY
        context["urgency_rule"] = "default"
        logger.debug("feedback_id=%s: LOW urgency (default).", feedback_id)
        return record, context