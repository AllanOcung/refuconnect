"""
apps/nlp/tests/test_urgency_assessor.py
"""
from unittest.mock import MagicMock

from django.test import SimpleTestCase

from apps.nlp.pipeline.urgency_assessor import UrgencyAssessor


def _make_record(message_text_en="", sentiment_id=None):
    r = MagicMock()
    r.id = 1
    r.message_text_en = message_text_en
    r.message_text = message_text_en
    r.sentiment_id = sentiment_id
    r.feedbackcategory_set = MagicMock()
    r.feedbackcategory_set.select_related.return_value = []
    return r


class UrgencyAssessorTests(SimpleTestCase):

    def setUp(self):
        UrgencyAssessor._initialised = False
        self.assessor = UrgencyAssessor()

    def test_high_urgency_keyword_sets_high(self):
        record = _make_record("There has been a violent attack on the camp")
        context = {}
        self.assessor.process(record, context)
        self.assertEqual(record.urgency_level, "High")
        self.assertTrue(context["urgency_rule"].startswith("keyword:"))

    def test_medium_urgency_keyword_sets_medium(self):
        record = _make_record("The medicine supply has been delayed again")
        context = {}
        self.assessor.process(record, context)
        self.assertEqual(record.urgency_level, "Medium")

    def test_no_keyword_sets_low(self):
        record = _make_record("The community meeting was well attended")
        context = {}
        self.assessor.process(record, context)
        self.assertEqual(record.urgency_level, "Low")
        self.assertEqual(context["urgency_rule"], "default")

    def test_word_boundary_prevents_false_positive(self):
        # 'fire' should not match 'Firefox'
        record = _make_record("I opened Firefox to check the schedule")
        context = {}
        self.assessor.process(record, context)
        self.assertEqual(record.urgency_level, "Low")

    def test_word_boundary_prevents_false_positive_fireplace(self):
        record = _make_record("We sat by the fireplace last evening")
        context = {}
        self.assessor.process(record, context)
        self.assertEqual(record.urgency_level, "Low")

    def test_urgency_rule_field_set_for_high(self):
        record = _make_record("A child abuse case was reported today")
        context = {}
        self.assessor.process(record, context)
        self.assertIn("urgency_rule", context)
        self.assertEqual(record.urgency_level, "High")

    def test_urgency_rule_field_set_for_medium(self):
        record = _make_record("Many people are sick in the camp this week")
        context = {}
        self.assessor.process(record, context)
        self.assertIn("urgency_rule", context)
        self.assertEqual(record.urgency_level, "Medium")
