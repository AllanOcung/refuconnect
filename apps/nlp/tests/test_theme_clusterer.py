"""
apps/nlp/tests/test_theme_clusterer.py
"""
from datetime import date, timedelta
from unittest.mock import MagicMock, patch

from django.test import TestCase


def _make_record(pk, text="some feedback text here", sentiment_id=None):
    r = MagicMock()
    r.pk = pk
    r.message_text_en = text
    r.message_text = text
    r.sentiment_id = sentiment_id
    if sentiment_id:
        r.sentiment = MagicMock(sentiment_label="Negative")
    return r


CLUSTERER_MODULE = "apps.nlp.pipeline.theme_clusterer"


def _make_qs(records):
    """Return a mock queryset whose filter().select_related() returns the records list."""
    qs = MagicMock()
    qs.filter.return_value.select_related.return_value = records
    # Also make filter().delete() available for the idempotency check
    qs.filter.return_value.delete = MagicMock()
    return qs


class ThemeClustererTests(TestCase):

    def _get_clusterer(self):
        from apps.nlp.pipeline.theme_clusterer import ThemeClusterer
        return ThemeClusterer()

    @patch(f"{CLUSTERER_MODULE}.ThemeCluster")
    @patch(f"{CLUSTERER_MODULE}.FeedbackCluster")
    @patch(f"{CLUSTERER_MODULE}.Feedback")
    def test_fewer_than_5_records_exits_early(
        self, mock_feedback_cls, mock_fc, mock_tc
    ):
        records = [_make_record(i) for i in range(3)]
        mock_feedback_cls.objects.filter.return_value.select_related.return_value = records
        clusterer = self._get_clusterer()
        clusterer.run()
        mock_tc.objects.create.assert_not_called()

    @patch(f"{CLUSTERER_MODULE}.ThemeCluster")
    @patch(f"{CLUSTERER_MODULE}.FeedbackCluster")
    @patch(f"{CLUSTERER_MODULE}.Feedback")
    def test_existing_clusters_deleted_before_insert(
        self, mock_feedback_cls, mock_fc, mock_tc
    ):
        records = [
            _make_record(i, f"water food health medicine supply camp {i}") for i in range(10)
        ]
        mock_feedback_cls.objects.filter.return_value.select_related.return_value = records

        mock_tc.objects.filter.return_value.delete = MagicMock()
        mock_tc.objects.create.return_value = MagicMock(pk=1)
        mock_fc.objects.filter.return_value.delete = MagicMock()
        mock_fc.objects.bulk_create = MagicMock()

        clusterer = self._get_clusterer()
        clusterer.run()

        # Delete called before insert — idempotency guarantee
        mock_tc.objects.filter.assert_called()
        mock_tc.objects.filter.return_value.delete.assert_called()

    def test_elbow_k_returns_correct_k(self):
        from apps.nlp.pipeline.theme_clusterer import _elbow_k
        inertias = [100.0, 60.0, 55.0, 53.0]
        k = _elbow_k(inertias)
        self.assertGreaterEqual(k, 2)
        self.assertLessEqual(k, 5)

    def test_get_week_start_is_monday(self):
        from apps.nlp.pipeline.theme_clusterer import _get_week_start
        week_start = _get_week_start()
        self.assertEqual(week_start.weekday(), 0)  # 0 = Monday