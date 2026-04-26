"""
Unit tests for the urgency assessor component.

Tests cover:
  - High-urgency keyword detection
  - Medium-urgency keyword detection
  - Default low urgency
  - Word-boundary matching (no false positives)
  - Urgency rule context tracking
"""
from __future__ import annotations

import pytest

from apps.nlp.pipeline.urgency_assessor import assess_urgency


class TestUrgencyAssessor:
    """Test suite for urgency assessment logic."""

    def test_high_urgency_keyword_death(self):
        """Death-related keywords should trigger high urgency."""
        text = "My child has died from cholera"
        urgency, rule = assess_urgency(text)
        assert urgency == "High"
        assert "keyword:" in rule

    def test_high_urgency_keyword_emergency(self):
        """Emergency keyword should trigger high urgency."""
        text = "This is an emergency! We need help immediately"
        urgency, rule = assess_urgency(text)
        assert urgency == "High"
        assert "keyword:" in rule

    def test_high_urgency_keyword_violence(self):
        """Violence-related keywords should trigger high urgency."""
        text = "There was violence in the camp last night"
        urgency, rule = assess_urgency(text)
        assert urgency == "High"
        assert "keyword:" in rule

    def test_high_urgency_keyword_attack(self):
        """Attack keyword should trigger high urgency."""
        text = "armed attack on the settlement"
        urgency, rule = assess_urgency(text)
        assert urgency == "High"

    def test_medium_urgency_keyword_sick(self):
        """Sick keyword should trigger medium urgency."""
        text = "My child is very sick"
        urgency, rule = assess_urgency(text)
        assert urgency == "Medium"
        assert "keyword:" in rule

    def test_medium_urgency_keyword_problem(self):
        """Problem keyword should trigger medium urgency."""
        text = "We have a water problem at the clinic"
        urgency, rule = assess_urgency(text)
        assert urgency == "Medium"

    def test_medium_urgency_keyword_complaint(self):
        """Complaint keyword should trigger medium urgency."""
        text = "I have a complaint about the food distribution"
        urgency, rule = assess_urgency(text)
        assert urgency == "Medium"

    def test_no_keyword_returns_low_urgency(self):
        """Text with no urgency keywords should return low."""
        text = "Things are generally okay"
        urgency, rule = assess_urgency(text)
        assert urgency == "Low"
        assert rule == "default"

    def test_empty_text_returns_low_urgency(self):
        """Empty text should return low urgency."""
        urgency, rule = assess_urgency("")
        assert urgency == "Low"
        assert rule == "default"

    def test_word_boundary_prevents_false_positive_fire(self):
        """'fire' should not match in 'Firefox'."""
        text = "I use Firefox browser"
        urgency, rule = assess_urgency(text)
        # High urgency patterns include 'fire'
        # Word boundary should prevent false positive
        assert urgency == "Low"

    def test_word_boundary_prevents_false_positive_complaint_in_complain(self):
        """'complaint' should not falsely match 'complain' differently."""
        text = "I complain often"
        urgency, rule = assess_urgency(text)
        # This should match because of word boundary on "complain"
        assert urgency == "Medium"

    def test_case_insensitive_matching(self):
        """Matching should be case-insensitive."""
        text = "EMERGENCY! URGENT HELP NEEDED!"
        urgency, rule = assess_urgency(text)
        assert urgency == "High"

    def test_rule_context_includes_keyword(self):
        """Rule context should identify the matched keyword."""
        text = "emergency supplies needed"
        urgency, rule = assess_urgency(text)
        assert urgency == "High"
        assert "emergency" in rule.lower()

    def test_priority_high_over_medium(self):
        """High-urgency keyword should take priority over medium."""
        text = "emergency but also sick"
        urgency, rule = assess_urgency(text)
        assert urgency == "High"

    def test_multiple_keywords_first_wins(self):
        """First matching rule should be returned."""
        text = "death and violence in the settlement"
        urgency, rule = assess_urgency(text)
        # Should match first high-urgency pattern
        assert urgency == "High"

    def test_unicode_text_handled(self):
        """Unicode characters should not break matching."""
        text = "Urgency: çédilla naïve café"
        urgency, rule = assess_urgency(text)
        assert urgency == "High"  # 'Urgency' is a keyword

    def test_multiline_text_handled(self):
        """Multiline text should be processed."""
        text = """The situation is very bad
        We have an emergency
        Please send help"""
        urgency, rule = assess_urgency(text)
        assert urgency == "High"

    def test_rule_3_high_urgency_health_negative(self):
        """Health category + Negative sentiment should trigger high urgency."""
        urgency, rule = assess_urgency(
            "No keywords here",
            category="Health",
            sentiment="Negative",
        )
        assert urgency == "High"
        assert "category+sentiment" in rule
        assert "Health" in rule
        assert "Negative" in rule

    def test_rule_3_high_urgency_violence_negative(self):
        """Violence category + Negative sentiment should trigger high urgency."""
        urgency, rule = assess_urgency(
            "Plain text",
            category="Violence",
            sentiment="Negative",
        )
        assert urgency == "High"
        assert "category+sentiment:Violence+Negative" in rule

    def test_rule_3_high_urgency_exploitation_negative(self):
        """Exploitation category + Negative sentiment should trigger high urgency."""
        urgency, rule = assess_urgency(
            "Neutral message",
            category="Exploitation",
            sentiment="Negative",
        )
        assert urgency == "High"
        assert "category+sentiment" in rule

    def test_rule_3_no_urgency_health_positive(self):
        """Health category + Positive sentiment should not trigger high urgency."""
        urgency, rule = assess_urgency(
            "No keywords",
            category="Health",
            sentiment="Positive",
        )
        assert urgency == "Low"
        assert rule == "default"

    def test_rule_3_no_urgency_health_neutral(self):
        """Health category + Neutral sentiment should not trigger high urgency."""
        urgency, rule = assess_urgency(
            "Normal message",
            category="Health",
            sentiment="Neutral",
        )
        assert urgency == "Low"
        assert rule == "default"

    def test_rule_3_no_urgency_non_urgent_category_negative(self):
        """Non-urgent category + Negative sentiment should not trigger high urgency."""
        urgency, rule = assess_urgency(
            "Just some text",
            category="General",
            sentiment="Negative",
        )
        assert urgency == "Low"
        assert rule == "default"
