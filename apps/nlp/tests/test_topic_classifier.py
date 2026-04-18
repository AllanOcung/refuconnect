"""
apps/nlp/tests/test_topic_classifier.py
"""
from unittest.mock import MagicMock, patch

from django.test import TestCase

MODULE = "apps.nlp.pipeline.topic_classifier"
HF_PIPELINE = f"{MODULE}.hf_pipeline"
ACTIVE_LABELS = f"{MODULE}.TopicClassifier._active_labels"
MOD_FEEDBACK_CATEGORY = f"{MODULE}.FeedbackCategory"
MOD_CATEGORY = f"{MODULE}.Category"


def _make_record(message_text_en="The water at the clinic is contaminated"):
    r = MagicMock()
    r.pk = 1
    r.id = 1
    r.message_text_en = message_text_en
    r.message_text = message_text_en
    r.feedbackcategory_set = MagicMock()
    r.feedbackcategory_set.filter.return_value = []
    return r


@patch(HF_PIPELINE)
class TopicClassifierTests(TestCase):

    def _get_classifier(self, mock_hf):
        from apps.nlp.pipeline.topic_classifier import TopicClassifier
        TopicClassifier._classifier = None
        mock_clf = MagicMock()
        mock_hf.return_value = mock_clf
        clf = TopicClassifier()
        return clf, mock_clf

    def _zs_result(self, scores: dict):
        return {
            "labels": list(scores.keys()),
            "scores": list(scores.values()),
        }

    @patch(ACTIVE_LABELS, return_value=["Health", "WASH", "Education"])
    @patch(f"{MODULE}.TopicClassifier._get_category_by_name")
    @patch(MOD_FEEDBACK_CATEGORY)
    def test_categories_above_threshold_assigned(
        self, MockFC, mock_cat, mock_labels, mock_hf
    ):
        clf, mock_clf = self._get_classifier(mock_hf)
        mock_clf.return_value = self._zs_result(
            {"Health": 0.85, "WASH": 0.80, "Education": 0.40}
        )
        mock_cat.return_value = MagicMock(pk=1)
        MockFC.objects.get_or_create.return_value = (MagicMock(), True)

        record = _make_record()
        clf.process(record, {})
        # Only Health and WASH above 0.70
        self.assertEqual(MockFC.objects.get_or_create.call_count, 2)

    @patch(ACTIVE_LABELS, return_value=["Health", "Education"])
    @patch(f"{MODULE}.TopicClassifier._get_category_by_name")
    @patch(MOD_FEEDBACK_CATEGORY)
    def test_nothing_above_threshold_uses_highest_with_review_flag(
        self, MockFC, mock_cat, mock_labels, mock_hf
    ):
        clf, mock_clf = self._get_classifier(mock_hf)
        mock_clf.return_value = self._zs_result({"Health": 0.45, "Education": 0.30})
        mock_cat.return_value = MagicMock(pk=1)
        MockFC.objects.get_or_create.return_value = (MagicMock(), True)
        context = {}

        clf.process(_make_record(), context)
        self.assertTrue(context.get("needs_category_review"))

    @patch(ACTIVE_LABELS, return_value=["Health"])
    @patch(f"{MODULE}.TopicClassifier._get_category_by_name")
    @patch(MOD_FEEDBACK_CATEGORY)
    def test_ussd_pre_category_not_overwritten(
        self, MockFC, mock_cat, mock_labels, mock_hf
    ):
        clf, mock_clf = self._get_classifier(mock_hf)
        mock_clf.return_value = self._zs_result({"Health": 0.90})
        mock_cat.return_value = MagicMock(pk=1)

        record = _make_record()
        existing = MagicMock()
        existing.is_ai_assigned = False
        existing.category.name = "Health"
        record.feedbackcategory_set.filter.return_value = [existing]
        MockFC.objects.get_or_create.return_value = (existing, False)

        clf.process(record, {})
        fc_obj, created = MockFC.objects.get_or_create.return_value
        self.assertFalse(fc_obj.is_ai_assigned)

    @patch(ACTIVE_LABELS, return_value=["WASH", "Health"])
    @patch(f"{MODULE}.TopicClassifier._get_category_by_name")
    @patch(MOD_FEEDBACK_CATEGORY)
    def test_multi_label_two_above_threshold_both_created(
        self, MockFC, mock_cat, mock_labels, mock_hf
    ):
        clf, mock_clf = self._get_classifier(mock_hf)
        mock_clf.return_value = self._zs_result({"WASH": 0.82, "Health": 0.78})
        mock_cat.return_value = MagicMock(pk=1)
        MockFC.objects.get_or_create.return_value = (MagicMock(), True)

        clf.process(_make_record(), {})
        self.assertEqual(MockFC.objects.get_or_create.call_count, 2)

    @patch(ACTIVE_LABELS, return_value=["Health"])
    @patch(f"{MODULE}.TopicClassifier._get_category_by_name")
    @patch(MOD_FEEDBACK_CATEGORY)
    def test_feedback_category_saved_with_confidence(
        self, MockFC, mock_cat, mock_labels, mock_hf
    ):
        clf, mock_clf = self._get_classifier(mock_hf)
        mock_clf.return_value = self._zs_result({"Health": 0.88})
        mock_cat.return_value = MagicMock(pk=1)
        new_fc = MagicMock()
        MockFC.objects.get_or_create.return_value = (new_fc, True)

        clf.process(_make_record(), {})
        kwargs = MockFC.objects.get_or_create.call_args[1]["defaults"]
        self.assertAlmostEqual(kwargs["confidence_score"], 0.88, places=2)
        self.assertTrue(kwargs["is_ai_assigned"])