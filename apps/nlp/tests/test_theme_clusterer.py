"""
Unit tests for theme clustering and FeedbackCluster junction population.

Tests cover:
  - Elbow method for optimal cluster detection
  - Handling of insufficient data (< 3 documents)
"""
from __future__ import annotations

from datetime import date

import pytest

from apps.nlp.pipeline.theme_clusterer import (
    _find_optimal_clusters,
    cluster_weekly_themes,
)


@pytest.mark.django_db
class TestThemeClusterer:
    """Test suite for theme clustering logic."""

    def test_insufficient_data_returns_empty_clusters(self):
        """Clustering should return [] if fewer than 3 documents."""
        week_start = date(2024, 1, 1)
        clusters = cluster_weekly_themes(week_start)
        assert clusters == []

    def test_find_optimal_clusters_with_small_dataset(self):
        """Elbow method should select reasonable cluster count for small datasets."""
        import numpy as np

        # Create mock TF-IDF matrix (4 documents, 10 features)
        X = np.random.rand(4, 10)

        # Should return count between 2 and 4 (clamped by n_docs)
        optimal = _find_optimal_clusters(X, 4)
        assert 2 <= optimal <= 4

    def test_find_optimal_clusters_respects_max_limit(self):
        """Elbow method should cap at 10 clusters."""
        import numpy as np

        # Create large TF-IDF matrix
        X = np.random.rand(50, 100)

        optimal = _find_optimal_clusters(X, 50)
        assert optimal <= 10

    def test_find_optimal_clusters_respects_min_limit(self):
        """Elbow method should not go below 2 clusters."""
        import numpy as np

        # Small dataset
        X = np.random.rand(3, 5)
        optimal = _find_optimal_clusters(X, 3)
        assert optimal >= 2

