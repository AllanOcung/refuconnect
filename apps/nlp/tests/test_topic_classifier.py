"""
Unit tests for the topic classifier component.

Tests cover:
  - Threshold fix (0.70 cutoff)
  - Multi-label support (multiple categories >= 0.70)
  - Low confidence fallback (needs_category_review flag)
  - USSD pre-category preservation
  - Token truncation verification
  - FeedbackCategory record creation
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from apps.nlp.pipeline.topic_classifier import (
    _MAX_INPUT_TOKENS,
    _truncate_to_tokens,
    classify_topics,
)


class TestTopicClassifier:
    """Test suite for topic classification logic."""

    def test_threshold_is_0_70(self):
        """Confidence threshold should be 0.70 (not 0.40)."""
        from apps.nlp.pipeline.topic_classifier import _CONFIDENCE_THRESHOLD

        assert _CONFIDENCE_THRESHOLD == 0.70

    def test_multi_label_support_multiple_categories(self):
        """Multiple categories >= 0.70 should all be returned."""
        text = "Health emergency with violence issues"

        with patch("apps.nlp.pipeline.topic_classifier._get_classifier") as mock_clf:
            mock_classifier = MagicMock()
            mock_classifier.return_value = {
                "labels": ["Health", "Violence", "Exploitation", "General"],
                "scores": [0.85, 0.78, 0.65, 0.42],
            }
            mock_clf.return_value = mock_classifier

            with patch("apps.feedback.models.Category.objects.filter") as mock_categories:
                mock_categories.return_value.values_list.return_value = [
                    "Health",
                    "Violence",
                    "Exploitation",
                    "General",
                ]

                results, flags = classify_topics(text)

                # Should include Health (0.85) and Violence (0.78), not Exploitation (0.65) or General (0.42)
                assert len(results) == 2
                assert ("Health", 0.85) in results
                assert ("Violence", 0.78) in results

    def test_single_category_above_threshold(self):
        """Single category above threshold should be returned."""
        text = "Health related message"

        with patch("apps.nlp.pipeline.topic_classifier._get_classifier") as mock_clf:
            mock_classifier = MagicMock()
            mock_classifier.return_value = {
                "labels": ["Health", "General", "Other"],
                "scores": [0.72, 0.18, 0.10],
            }
            mock_clf.return_value = mock_classifier

            with patch("apps.feedback.models.Category.objects.filter") as mock_categories:
                mock_categories.return_value.values_list.return_value = [
                    "Health",
                    "General",
                    "Other",
                ]

                results, flags = classify_topics(text)

                assert len(results) == 1
                assert results[0] == ("Health", 0.72)

    def test_no_categories_above_threshold_flags_review(self):
        """No categories above threshold should set needs_category_review."""
        text = "Generic message"

        with patch("apps.nlp.pipeline.topic_classifier._get_classifier") as mock_clf:
            mock_classifier = MagicMock()
            mock_classifier.return_value = {
                "labels": ["Health", "Violence", "General"],
                "scores": [0.65, 0.55, 0.45],
            }
            mock_clf.return_value = mock_classifier

            with patch("apps.feedback.models.Category.objects.filter") as mock_categories:
                mock_categories.return_value.values_list.return_value = [
                    "Health",
                    "Violence",
                    "General",
                ]

                results, flags = classify_topics(text)

                assert results == []
                assert flags["needs_category_review"] is True

    def test_ussd_pre_category_added(self):
        """USSD pre-category should be included with confidence 1.0."""
        text = "Some message"

        with patch("apps.nlp.pipeline.topic_classifier._get_classifier") as mock_clf:
            mock_classifier = MagicMock()
            mock_classifier.return_value = {
                "labels": ["Health", "General"],
                "scores": [0.75, 0.25],
            }
            mock_clf.return_value = mock_classifier

            with patch("apps.feedback.models.Category.objects.filter") as mock_categories:
                mock_categories.return_value.values_list.return_value = ["Health", "General"]

                results, flags = classify_topics(text, ussd_pre_category="Violence")

                # Violence should be first (inserted at position 0)
                assert results[0] == ("Violence", 1.0)
                assert ("Health", 0.75) in results

    def test_ussd_pre_category_not_duplicated(self):
        """USSD pre-category already in results should not be duplicated."""
        text = "Violence incident reported"

        with patch("apps.nlp.pipeline.topic_classifier._get_classifier") as mock_clf:
            mock_classifier = MagicMock()
            mock_classifier.return_value = {
                "labels": ["Violence", "General"],
                "scores": [0.80, 0.20],
            }
            mock_clf.return_value = mock_classifier

            with patch("apps.feedback.models.Category.objects.filter") as mock_categories:
                mock_categories.return_value.values_list.return_value = ["Violence", "General"]

                results, flags = classify_topics(text, ussd_pre_category="Violence")

                # Should only have one Violence entry (the model's one at 0.80)
                violence_count = sum(1 for cat, _ in results if cat == "Violence")
                assert violence_count == 1

    def test_classifier_unavailable_returns_empty(self):
        """Unavailable classifier should return empty list."""
        text = "Some message"

        with patch("apps.nlp.pipeline.topic_classifier._get_classifier") as mock_clf:
            mock_clf.return_value = None

            with patch("apps.feedback.models.Category.objects.filter") as mock_categories:
                mock_categories.return_value.values_list.return_value = ["Health"]

                results, flags = classify_topics(text)

                assert results == []

    def test_no_active_categories_returns_empty(self):
        """No active categories should return empty list."""
        text = "Some message"

        with patch("apps.feedback.models.Category.objects.filter") as mock_categories:
            mock_categories.return_value.values_list.return_value = []

            results, flags = classify_topics(text)

            assert results == []

    def test_classifier_exception_handled(self):
        """Classifier exception should be caught and empty list returned."""
        text = "Some message"

        with patch("apps.nlp.pipeline.topic_classifier._get_classifier") as mock_clf:
            mock_classifier = MagicMock()
            mock_classifier.side_effect = Exception("Classification error")
            mock_clf.return_value = mock_classifier

            with patch("apps.feedback.models.Category.objects.filter") as mock_categories:
                mock_categories.return_value.values_list.return_value = ["Health"]

                results, flags = classify_topics(text)

                assert results == []

    def test_token_truncation_512_tokens(self):
        """Text should be truncated to 512 tokens before classification."""
        # Create a very long text
        long_text = "word " * 2000  # ~2000 words, well over 512 tokens

        with patch("apps.nlp.pipeline.topic_classifier._truncate_to_tokens") as mock_truncate:
            mock_truncate.return_value = "truncated text"

            with patch("apps.nlp.pipeline.topic_classifier._get_classifier") as mock_clf:
                mock_classifier = MagicMock()
                mock_classifier.return_value = {
                    "labels": ["Health"],
                    "scores": [0.75],
                }
                mock_clf.return_value = mock_classifier

                with patch("apps.feedback.models.Category.objects.filter") as mock_categories:
                    mock_categories.return_value.values_list.return_value = ["Health"]

                    results, flags = classify_topics(long_text)

                    # _truncate_to_tokens should have been called
                    mock_truncate.assert_called_once()
                    # It should be called with _MAX_INPUT_TOKENS
                    assert mock_truncate.call_args[0][1] == _MAX_INPUT_TOKENS

    @pytest.mark.django_db
    def test_feedback_category_records_created(self):
        """FeedbackCategory records should be created for each result."""
        text = "Health and violence issue"

        with patch("apps.nlp.pipeline.topic_classifier._get_classifier") as mock_clf:
            mock_classifier = MagicMock()
            mock_classifier.return_value = {
                "labels": ["Health", "Violence"],
                "scores": [0.80, 0.75],
            }
            mock_clf.return_value = mock_classifier

            with patch("apps.feedback.models.Category.objects.filter") as mock_categories:
                mock_categories.return_value.values_list.return_value = ["Health", "Violence"]

            with patch("apps.feedback.models.Feedback.objects.get") as mock_feedback_get:
                mock_feedback = MagicMock()
                mock_feedback_get.return_value = mock_feedback

                with patch("apps.feedback.models.Category.objects.get") as mock_category_get:
                    mock_health = MagicMock()
                    mock_violence = MagicMock()

                    def category_get_side_effect(category_name):
                        if category_name == "Health":
                            return mock_health
                        elif category_name == "Violence":
                            return mock_violence
                        raise Exception("Not found")

                    mock_category_get.side_effect = category_get_side_effect

                    with patch("apps.feedback.models.FeedbackCategory.objects.get_or_create") as mock_get_or_create:
                        mock_get_or_create.return_value = (MagicMock(), True)

                        results, flags = classify_topics(text, feedback_id=123)

                        # Should create 2 FeedbackCategory records
                        assert mock_get_or_create.call_count == 2

    @pytest.mark.django_db
    def test_feedback_category_skip_if_feedback_not_found(self):
        """FeedbackCategory creation should skip if feedback not found."""
        text = "Test message"

        with patch("apps.nlp.pipeline.topic_classifier._get_classifier") as mock_clf:
            mock_classifier = MagicMock()
            mock_classifier.return_value = {
                "labels": ["Health"],
                "scores": [0.80],
            }
            mock_clf.return_value = mock_classifier

            with patch("apps.feedback.models.Category.objects.filter") as mock_categories:
                mock_categories.return_value.values_list.return_value = ["Health"]

            with patch("apps.feedback.models.Feedback.objects.get") as mock_feedback_get:
                from apps.feedback.models import Feedback

                mock_feedback_get.side_effect = Feedback.DoesNotExist()

                results, flags = classify_topics(text, feedback_id=999)

                # Should still return results
                assert results == [("Health", 0.80)]

    def test_return_tuple_structure(self):
        """Return should be (results_list, review_flags_dict)."""
        text = "Test"

        with patch("apps.feedback.models.Category.objects.filter") as mock_categories:
            mock_categories.return_value.values_list.return_value = []

            results = classify_topics(text)

            assert isinstance(results, tuple)
            assert len(results) == 2
            results_list, flags_dict = results
            assert isinstance(results_list, list)
            assert isinstance(flags_dict, dict)
            assert "needs_category_review" in flags_dict

    def test_confidence_scores_rounded_to_3_decimals(self):
        """Confidence scores should be rounded to 3 decimals."""
        text = "Test message"

        with patch("apps.nlp.pipeline.topic_classifier._get_classifier") as mock_clf:
            mock_classifier = MagicMock()
            mock_classifier.return_value = {
                "labels": ["Health", "General"],
                "scores": [0.85432, 0.14568],
            }
            mock_clf.return_value = mock_classifier

            with patch("apps.feedback.models.Category.objects.filter") as mock_categories:
                mock_categories.return_value.values_list.return_value = ["Health", "General"]

                results, flags = classify_topics(text)

                # First result should have rounded score
                assert results[0][1] == 0.854

    @pytest.mark.django_db
    def test_results_ordered_by_confidence_descending(self):
        """Results should be ordered by confidence descending."""
        text = "Complex multi-category message"

        with patch("apps.nlp.pipeline.topic_classifier._get_classifier") as mock_clf:
            mock_classifier = MagicMock()
            mock_classifier.return_value = {
                "labels": ["Health", "Violence", "Exploitation"],
                "scores": [0.75, 0.85, 0.72],  # Intentionally out of order
            }
            mock_clf.return_value = mock_classifier

            with patch("apps.feedback.models.Category.objects.filter") as mock_categories:
                mock_categories.return_value.values_list.return_value = [
                    "Health",
                    "Violence",
                    "Exploitation",
                ]

                results, flags = classify_topics(text)

                # Violence should be first (0.85), then Health (0.75)
                assert results[0][0] == "Violence"
                assert results[1][0] == "Health"

    def test_categories_below_threshold_excluded(self):
        """Categories with score < 0.70 should be excluded."""
        text = "Message"

        with patch("apps.nlp.pipeline.topic_classifier._get_classifier") as mock_clf:
            mock_classifier = MagicMock()
            mock_classifier.return_value = {
                "labels": ["Health", "Borderline", "Low"],
                "scores": [0.80, 0.70, 0.69],  # 0.70 exactly vs 0.69
            }
            mock_clf.return_value = mock_classifier

            with patch("apps.feedback.models.Category.objects.filter") as mock_categories:
                mock_categories.return_value.values_list.return_value = [
                    "Health",
                    "Borderline",
                    "Low",
                ]

                results, flags = classify_topics(text)

                # Should include Health (0.80) and Borderline (exactly 0.70)
                # but not Low (0.69)
                category_names = [cat for cat, _ in results]
                assert "Health" in category_names
                assert "Borderline" in category_names
                assert "Low" not in category_names
