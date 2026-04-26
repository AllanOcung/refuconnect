"""
Weekly theme clustering using TF-IDF + K-Means with elbow method.

Generates ``ThemeCluster`` records for a given calendar week.
Called from the Celery Beat periodic task every Monday at 02:00 UTC.
"""
from __future__ import annotations

import logging
from collections import Counter
from datetime import date, timedelta
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)

_N_CLUSTERS_MIN = 2
_N_CLUSTERS_MAX = 10
_N_CLUSTERS_DEFAULT = 5
_MIN_DOCS_FOR_CLUSTERING = 3
_MAX_KEYWORDS = 5
_ELBOW_THRESHOLD = 0.85  # Accept cluster count if explained variance ratio ≥ 85%


def _find_optimal_clusters(
    X: np.ndarray,  # TF-IDF matrix
    n_docs: int,
) -> int:
    """
    Use elbow method to find optimal number of clusters.

    Tests 2-10 clusters and returns count where explained variance ratio ≥ 85%,
    or where the elbow (diminishing returns) appears.

    Parameters
    ----------
    X: TF-IDF feature matrix
    n_docs: Total number of documents

    Returns
    -------
    Optimal cluster count (2-10, default 5)
    """
    from sklearn.cluster import KMeans  # type: ignore[import]

    inertias = []
    max_clusters = min(_N_CLUSTERS_MAX, n_docs)

    for n_clusters in range(_N_CLUSTERS_MIN, max_clusters + 1):
        try:
            km = KMeans(
                n_clusters=n_clusters,
                random_state=42,
                n_init=10,
            )
            km.fit(X)
            inertias.append(km.inertia_)
        except Exception as e:
            logger.warning("KMeans failed for %d clusters: %s", n_clusters, e)
            continue

    if not inertias:
        return _N_CLUSTERS_DEFAULT

    # Calculate explained variance ratio (simplified)
    max_inertia = inertias[0]
    min_inertia = inertias[-1]
    range_inertia = max(1, max_inertia - min_inertia)

    for idx, inertia in enumerate(inertias):
        explained = 1 - (inertia - min_inertia) / range_inertia
        n_clusters = idx + _N_CLUSTERS_MIN
        if explained >= _ELBOW_THRESHOLD:
            logger.info(
                "Elbow method: selected %d clusters (explained variance: %.2f%%)",
                n_clusters,
                explained * 100,
            )
            return n_clusters

    # Fallback: return cluster count with best explained variance
    best_idx = len(inertias) // 2
    return best_idx + _N_CLUSTERS_MIN


def _get_feedback_with_sentiment(
    week_start: date,
) -> list[tuple[str, str, int]]:  # (text, sentiment, feedback_id)
    """
    Retrieve processed English feedback with sentiment for the given week.

    Returns list of tuples: (message_text_en, sentiment_label, feedback_id)
    """
    from apps.feedback.models import Feedback

    week_end = week_start + timedelta(days=7)
    results = []

    feedbacks = Feedback.objects.filter(
        status="Processed",
        submitted_at__date__gte=week_start,
        submitted_at__date__lt=week_end,
        message_text_en__isnull=False,
    ).exclude(message_text_en="").select_related("sentiment")

    for fb in feedbacks:
        sentiment_label = (
            fb.sentiment.sentiment_label if fb.sentiment else "Unknown"
        )
        results.append((fb.message_text_en, sentiment_label, fb.feedback_id))

    return results


def _get_dominant_sentiment(
    feedback_ids: list[int],
) -> Optional[str]:
    """
    Get the dominant sentiment from a list of feedback IDs.

    Returns the most common sentiment label (or None if no feedback).
    """
    from apps.feedback.models import Feedback

    if not feedback_ids:
        return None

    sentiments = list(
        Feedback.objects.filter(
            feedback_id__in=feedback_ids,
        )
        .values_list("sentiment__sentiment_label", flat=True)
        .select_related("sentiment")
    )

    if not sentiments:
        return None

    # Find most common sentiment
    sentiment_counts = Counter(sentiments)
    dominant = sentiment_counts.most_common(1)[0][0]
    return dominant


def cluster_weekly_themes(
    week_start: date,
    n_clusters: Optional[int] = None,
) -> list[dict]:
    """
    Retrieve processed English feedback for *week_start*'s ISO week and
    cluster it into thematic groups.

    Parameters
    ----------
    week_start: The Monday that starts the ISO week window.
    n_clusters: Target number of clusters. If None, use elbow method to auto-detect.

    Returns
    -------
    List of dicts ready to be unpacked into ``ThemeCluster.objects.create``.
    Each dict includes: week_start_date, cluster_label, feedback_count,
    avg_sentiment, top_keywords, feedback_ids.
    """
    feedback_data = _get_feedback_with_sentiment(week_start)

    if len(feedback_data) < _MIN_DOCS_FOR_CLUSTERING:
        logger.info(
            "Not enough feedback for clustering (week %s): %d documents.",
            week_start,
            len(feedback_data),
        )
        return []

    texts = [text for text, _, _ in feedback_data]
    feedback_ids_list = [fid for _, _, fid in feedback_data]

    try:
        from sklearn.feature_extraction.text import TfidfVectorizer  # type: ignore[import]
        from sklearn.cluster import KMeans  # type: ignore[import]

        vectorizer = TfidfVectorizer(
            max_features=500,
            stop_words="english",
            min_df=1,
            ngram_range=(1, 2),
        )
        X = vectorizer.fit_transform(texts)
        feature_names: list[str] = vectorizer.get_feature_names_out().tolist()

        # Auto-detect optimal cluster count if not provided
        if n_clusters is None:
            n_clusters = _find_optimal_clusters(X, len(texts))
        else:
            n_clusters = min(n_clusters, len(texts))

        kmeans = KMeans(
            n_clusters=n_clusters,
            random_state=42,
            n_init=10,
        )
        labels = kmeans.fit_predict(X)

    except Exception:
        logger.exception("Clustering failed for week %s.", week_start)
        return []

    clusters: list[dict] = []
    for cid in range(n_clusters):
        mask = labels == cid
        count = int(mask.sum())
        if count == 0:
            continue

        # Extract top keywords from this cluster's centroid
        centroid = kmeans.cluster_centers_[cid]
        top_idx = centroid.argsort()[-_MAX_KEYWORDS:][::-1]
        keywords = [feature_names[i] for i in top_idx]

        # Get feedback IDs in this cluster
        cluster_feedback_ids = [
            feedback_ids_list[i] for i in range(len(labels)) if labels[i] == cid
        ]

        # Get dominant sentiment for this cluster
        dominant_sentiment = _get_dominant_sentiment(cluster_feedback_ids)

        clusters.append(
            {
                "week_start_date": week_start,
                "cluster_label": f"Theme: {', '.join(keywords[:2])}",
                "feedback_count": count,
                "avg_sentiment": dominant_sentiment,
                "top_keywords": keywords,
                "feedback_ids": cluster_feedback_ids,
            }
        )

    return clusters


def save_weekly_clusters(week_start: date) -> int:
    """
    Run clustering and persist results to the database.

    Creates both ThemeCluster records and FeedbackCluster junction entries.
    Deletes any existing clusters for the same week before inserting fresh ones
    so the task is safely idempotent.

    Returns the number of clusters created.
    """
    from apps.nlp.models import FeedbackCluster, ThemeCluster

    cluster_dicts = cluster_weekly_themes(week_start)

    # Idempotent: remove stale clusters for this week before re-inserting
    ThemeCluster.objects.filter(week_start_date=week_start).delete()

    created = 0
    for data in cluster_dicts:
        feedback_ids = data.pop("feedback_ids", [])

        # Create ThemeCluster record
        cluster = ThemeCluster.objects.create(**data)

        # Create FeedbackCluster junction entries
        feedback_clusters = [
            FeedbackCluster(
                feedback_id=fid,
                cluster=cluster,
                week_start_date=week_start,
            )
            for fid in feedback_ids
        ]
        FeedbackCluster.objects.bulk_create(feedback_clusters, ignore_conflicts=True)

        created += 1

    logger.info("Created %d theme clusters for week %s.", created, week_start)
    return created
