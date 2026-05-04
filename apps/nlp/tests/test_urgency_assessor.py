"""
Unit tests for the C-09 UrgencyAssessor component.

Tests cover:
  - High-urgency keyword detection (Rule 1)
  - Medium-urgency keyword detection (Rule 2)
  - Default low urgency (Rule 4)
  - Word-boundary matching (no false positives)
  - Rule 3: negative sentiment + Protection & Safety / Healthcare → Medium
  - assess_feedback_urgency() with Feedback-like objects
  - Urgency rule context / audit string format
"""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock, PropertyMock

from apps.nlp.pipeline.urgency_assessor import assess_urgency, assess_feedback_urgency


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_feedback(message_text_en="", message_text="", sentiment_name=None, categories=()):
    """Build a minimal Feedback-like mock for assess_feedback_urgency tests."""
    fb = MagicMock()
    fb.feedback_id = 999
    fb.message_text_en = message_text_en
    fb.message_text = message_text

    # sentiment FK mock
    if sentiment_name:
        fb.sentiment = MagicMock()
        fb.sentiment.sentiment_name = sentiment_name
    else:
        fb.sentiment = None

    # feedback_categories queryset mock
    fb.feedback_categories.values_list.return_value = list(categories)
    return fb


# ── Rule 1: High-urgency keywords ─────────────────────────────────────────────

class TestHighUrgencyKeywords:

    def test_keyword_death(self):
        urgency, rule = assess_urgency("My child has died from cholera")
        assert urgency == "High"
        assert "keyword:" in rule

    def test_keyword_emergency(self):
        urgency, rule = assess_urgency("This is an emergency! We need help immediately")
        assert urgency == "High"
        assert "keyword:" in rule

    def test_keyword_violence(self):
        urgency, rule = assess_urgency("There was violence in the camp last night")
        assert urgency == "High"
        assert "keyword:" in rule

    def test_keyword_attack(self):
        urgency, rule = assess_urgency("armed attack on the settlement")
        assert urgency == "High"

    def test_keyword_rape(self):
        urgency, rule = assess_urgency("A woman reported rape near the water point")
        assert urgency == "High"
        assert "rape" in rule

    def test_keyword_assault(self):
        urgency, rule = assess_urgency("He suffered a violent assault last night")
        assert urgency == "High"

    def test_keyword_dying(self):
        urgency, rule = assess_urgency("The baby is dying and we have no medicine")
        assert urgency == "High"

    def test_keyword_killed(self):
        urgency, rule = assess_urgency("Two people were killed near the gate")
        assert urgency == "High"

    def test_keyword_starving(self):
        urgency, rule = assess_urgency("The children are starving")
        assert urgency == "High"

    def test_keyword_flood(self):
        urgency, rule = assess_urgency("A flood destroyed the shelter last night")
        assert urgency == "High"

    def test_keyword_fire(self):
        urgency, rule = assess_urgency("There is a fire in block 4")
        assert urgency == "High"

    def test_keyword_burning(self):
        urgency, rule = assess_urgency("The tents are burning")
        assert urgency == "High"

    def test_keyword_threat(self):
        urgency, rule = assess_urgency("I received a threat from my neighbour")
        assert urgency == "High"

    def test_keyword_armed(self):
        urgency, rule = assess_urgency("Armed men entered the compound")
        assert urgency == "High"

    def test_keyword_weapon(self):
        urgency, rule = assess_urgency("He was carrying a weapon")
        assert urgency == "High"

    def test_keyword_kidnap(self):
        urgency, rule = assess_urgency("My son was kidnapped yesterday")
        assert urgency == "High"

    def test_keyword_torture(self):
        urgency, rule = assess_urgency("Detainees reported torture")
        assert urgency == "High"

    def test_keyword_suicide(self):
        urgency, rule = assess_urgency("She is talking about suicide")
        assert urgency == "High"

    def test_keyword_collapsed(self):
        urgency, rule = assess_urgency("The roof collapsed on the family")
        assert urgency == "High"

    def test_keyword_unconscious(self):
        urgency, rule = assess_urgency("The man is unconscious on the ground")
        assert urgency == "High"

    def test_keyword_critically_ill(self):
        urgency, rule = assess_urgency("The patient is critically ill")
        assert urgency == "High"

    def test_keyword_sexual_abuse(self):
        urgency, rule = assess_urgency("She reported sexual abuse by a guard")
        assert urgency == "High"

    def test_keyword_child_abuse(self):
        urgency, rule = assess_urgency("There are signs of child abuse in the shelter")
        assert urgency == "High"

    def test_multiline_text(self):
        text = "The situation is very bad\nWe have an emergency\nPlease send help"
        urgency, rule = assess_urgency(text)
        assert urgency == "High"

    def test_case_insensitive(self):
        urgency, rule = assess_urgency("EMERGENCY! URGENT HELP NEEDED!")
        assert urgency == "High"

    def test_rule_context_contains_keyword(self):
        urgency, rule = assess_urgency("emergency supplies needed")
        assert urgency == "High"
        assert "emergency" in rule.lower()


# ── Rule 2: Medium-urgency keywords ───────────────────────────────────────────

class TestMediumUrgencyKeywords:

    def test_keyword_sick(self):
        urgency, rule = assess_urgency("My child is very sick")
        assert urgency == "Medium"
        assert "keyword:" in rule

    def test_keyword_injured(self):
        urgency, rule = assess_urgency("He is injured and needs treatment")
        assert urgency == "Medium"

    def test_keyword_broken(self):
        urgency, rule = assess_urgency("The water pump is broken")
        assert urgency == "Medium"

    def test_keyword_unsafe(self):
        urgency, rule = assess_urgency("The path to school feels unsafe")
        assert urgency == "Medium"

    def test_keyword_missing(self):
        urgency, rule = assess_urgency("My daughter has been missing since Tuesday")
        assert urgency == "Medium"

    def test_keyword_closed(self):
        urgency, rule = assess_urgency("The health clinic is closed again")
        assert urgency == "Medium"

    def test_keyword_refused(self):
        urgency, rule = assess_urgency("We were refused access to the distribution")
        assert urgency == "Medium"

    def test_keyword_denied(self):
        urgency, rule = assess_urgency("We were denied registration")
        assert urgency == "Medium"

    def test_keyword_delayed(self):
        urgency, rule = assess_urgency("Food distribution has been delayed for weeks")
        assert urgency == "Medium"

    def test_keyword_damaged(self):
        urgency, rule = assess_urgency("The shelter roof is damaged")
        assert urgency == "Medium"

    def test_keyword_blocked(self):
        urgency, rule = assess_urgency("The road to the clinic is blocked")
        assert urgency == "Medium"

    def test_keyword_complaint(self):
        urgency, rule = assess_urgency("I have a complaint about food distribution")
        assert urgency == "Medium"

    def test_keyword_no_medicine(self):
        urgency, rule = assess_urgency("There is no medicine at the clinic")
        assert urgency == "Medium"


# ── Rule 1 priority over Rule 2 ───────────────────────────────────────────────

class TestRulePriority:

    def test_high_takes_priority_over_medium(self):
        urgency, rule = assess_urgency("emergency but also sick")
        assert urgency == "High"

    def test_first_high_keyword_wins(self):
        urgency, rule = assess_urgency("death and violence in the settlement")
        assert urgency == "High"


# ── Rule 4: Default low ────────────────────────────────────────────────────────

class TestDefaultLow:

    def test_no_keywords_returns_low(self):
        urgency, rule = assess_urgency("Things are generally okay")
        assert urgency == "Low"
        assert rule == "default"

    def test_empty_text_returns_low(self):
        urgency, rule = assess_urgency("")
        assert urgency == "Low"
        assert rule == "default"


# ── Word-boundary false-positive prevention ───────────────────────────────────

class TestWordBoundary:

    def test_fire_does_not_match_firefox(self):
        urgency, rule = assess_urgency("I use Firefox browser")
        assert urgency == "Low"

    def test_fire_does_not_match_fireplace(self):
        urgency, rule = assess_urgency("We have a cosy fireplace")
        assert urgency == "Low"

    def test_complaint_matches_standalone(self):
        urgency, rule = assess_urgency("I have a complaint about service")
        assert urgency == "Medium"

    def test_complain_also_matches(self):
        """'complain' shares the stem and \b allows it to match."""
        urgency, rule = assess_urgency("I complain often")
        # 'complaint' pattern won't match 'complain' (different word boundary)
        # but 'complain' itself is not in the list — should be Low
        assert urgency == "Low"

    def test_sick_does_not_match_sickness(self):
        """'sick' with \b should still match inside 'sickness'? No — 'sickness' ends in 'ness'."""
        # Actually \bsick\b does NOT match 'sickness' because 'k' is followed by 'n' (word char)
        urgency, rule = assess_urgency("She has a sickness")
        assert urgency == "Low"

    def test_death_does_not_match_underneath(self):
        urgency, rule = assess_urgency("The water is underneath the tank")
        assert urgency == "Low"


# ── Rule 3: sentiment + category combination ──────────────────────────────────

class TestRule3SentimentCategory:

    def test_healthcare_negative_gives_medium(self):
        """Healthcare + Negative → Medium (C-09 spec)."""
        urgency, rule = assess_urgency("No keywords here", category="Healthcare", sentiment="Negative")
        assert urgency == "Medium"
        assert "sentiment+category" in rule
        assert "Healthcare" in rule

    def test_protection_safety_negative_gives_medium(self):
        """Protection & Safety + Negative → Medium."""
        urgency, rule = assess_urgency("Plain text", category="Protection & Safety", sentiment="Negative")
        assert urgency == "Medium"
        assert "sentiment+category" in rule
        assert "Protection & Safety" in rule

    def test_healthcare_positive_gives_low(self):
        urgency, rule = assess_urgency("No keywords", category="Healthcare", sentiment="Positive")
        assert urgency == "Low"
        assert rule == "default"

    def test_healthcare_neutral_gives_low(self):
        urgency, rule = assess_urgency("Normal message", category="Healthcare", sentiment="Neutral")
        assert urgency == "Low"
        assert rule == "default"

    def test_unknown_category_negative_gives_low(self):
        urgency, rule = assess_urgency("Just some text", category="Education", sentiment="Negative")
        assert urgency == "Low"
        assert rule == "default"

    def test_rule1_beats_rule3(self):
        """Keyword match in Rule 1 fires before Rule 3 is evaluated."""
        urgency, rule = assess_urgency("fire broke out", category="Healthcare", sentiment="Negative")
        assert urgency == "High"
        assert "keyword:" in rule


# ── assess_feedback_urgency() — Feedback-object API ──────────────────────────

class TestAssessFeedbackUrgency:

    def test_returns_three_tuple(self):
        fb = _make_feedback(message_text_en="Everything is fine")
        result = assess_feedback_urgency(fb)
        assert len(result) == 3
        level, rule, ctx = result
        assert level == "Low"
        assert rule == "default"
        assert isinstance(ctx, dict)

    def test_high_keyword_from_message_text_en(self):
        fb = _make_feedback(message_text_en="There is an emergency in block 3")
        level, rule, ctx = assess_feedback_urgency(fb)
        assert level == "High"
        assert "emergency" in rule

    def test_falls_back_to_message_text_when_no_en(self):
        fb = _make_feedback(message_text_en="", message_text="armed attack on refugees")
        level, rule, ctx = assess_feedback_urgency(fb)
        assert level == "High"

    def test_medium_keyword(self):
        fb = _make_feedback(message_text_en="The road to the clinic is blocked")
        level, rule, ctx = assess_feedback_urgency(fb)
        assert level == "Medium"
        assert "keyword:blocked" in rule

    def test_rule3_protection_safety_negative(self):
        fb = _make_feedback(
            message_text_en="Plain message",
            sentiment_name="Negative",
            categories=["Protection & Safety"],
        )
        level, rule, ctx = assess_feedback_urgency(fb)
        assert level == "Medium"
        assert "sentiment+category" in rule

    def test_rule3_healthcare_negative(self):
        fb = _make_feedback(
            message_text_en="No urgent words",
            sentiment_name="Negative",
            categories=["Healthcare"],
        )
        level, rule, ctx = assess_feedback_urgency(fb)
        assert level == "Medium"

    def test_rule3_no_match_positive_sentiment(self):
        fb = _make_feedback(
            message_text_en="No urgent words",
            sentiment_name="Positive",
            categories=["Healthcare"],
        )
        level, rule, ctx = assess_feedback_urgency(fb)
        assert level == "Low"

    def test_rule3_no_match_non_urgent_category(self):
        fb = _make_feedback(
            message_text_en="No urgent words",
            sentiment_name="Negative",
            categories=["Education"],
        )
        level, rule, ctx = assess_feedback_urgency(fb)
        assert level == "Low"

    def test_context_dict_has_urgency_rule(self):
        fb = _make_feedback(message_text_en="We have an emergency")
        level, rule, ctx = assess_feedback_urgency(fb)
        assert "urgency_rule" in ctx
        assert ctx["urgency_rule"] == rule

    def test_no_sentiment_set_rule3_skipped(self):
        """If sentiment is None (first-pass pipeline), Rule 3 is skipped."""
        fb = _make_feedback(
            message_text_en="General feedback with no keywords",
            sentiment_name=None,
            categories=["Healthcare"],
        )
        level, rule, ctx = assess_feedback_urgency(fb)
        assert level == "Low"

    def test_unicode_text_handled(self):
        """Unicode characters around a keyword should not break matching."""
        fb = _make_feedback(message_text_en="There is an emergency: çédilla naïve café")
        level, rule, ctx = assess_feedback_urgency(fb)
        assert level == "High"
        assert "emergency" in rule

