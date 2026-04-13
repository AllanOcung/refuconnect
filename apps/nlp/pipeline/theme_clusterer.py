"""
Weekly theme clustering using TF-IDF + K-Means.

Generates ``ThemeCluster`` records for a given calendar week.
Called from the Celery Beat periodic task every Monday at 02:00 UTC.
"""
from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)

_N_CLUSTERS_DEFAULT = 5
_MIN_DOCS_FOR_CLUSTERING = 3
_MAX_KEYWORDS = 5


def cluster_weekly_themes(
    week_start: date,
    n_clusters: int = _N_CLUSTERS_DEFAULT,
) -> list[dict]:
    """
    Retrieve processed English feedback for *week_start*'s ISO week and
    cluster it into *n_clusters* thematic groups.

    Parameters
    ----------
    week_start: The Monday that starts the ISO week window.
    n_clusters: Target number of clusters.  Reduced automatically if there
                are fewer documents than requested.

    Returns
    -------
    List of dicts, each ready to be unpacked into ``ThemeCluster.objects.create``.
    """
    from apps.feedback.models import Feedback

    week_end = week_start + timedelta(days=7)
    texts = list(
        Feedback.objects.filter(
            status="Processed",
            submitted_at__date__gte=week_start,
            submitted_at__date__lt=week_end,
            message_text_en__isnull=False,
        )
        .exclude(message_text_en="")
        .values_list("message_text_en", flat=True)
    )

    if len(texts) < _MIN_DOCS_FOR_CLUSTERING:
        logger.info(
            "Not enough feedback for clustering (week %s): %d documents.",
            week_start,
            len(texts),
        )
        return []

    effective_clusters = min(n_clusters, len(texts))

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

        kmeans = KMeans(
            n_clusters=effective_clusters,
            random_state=42,
            n_init=10,
        )
        labels = kmeans.fit_predict(X)

    except Exception:
        logger.exception("Clustering failed for week %s.", week_start)
        return []

    clusters: list[dict] = []
    for cid in range(effective_clusters):
        mask = labels == cid
        count = int(mask.sum())
        if count == 0:
            continue

        # Extract top keywords from this cluster's centroid
        centroid = kmeans.cluster_centers_[cid]
        top_idx = centroid.argsort()[-_MAX_KEYWORDS:][::-1]
        keywords = [feature_names[i] for i in top_idx]

        clusters.append(
            {
                "week_start_date": week_start,
                "cluster_label": f"Theme: {', '.join(keywords[:2])}",
                "feedback_count": count,
                "top_keywords": keywords,
            }
        )

    return clusters


def save_weekly_clusters(week_start: date) -> int:
    """
    Run clustering and persist results to the database.

    Deletes any existing clusters for the same week before inserting fresh ones
    so the task is safely idempotent.

    Returns the number of clusters created.
    """
    from apps.nlp.models import ThemeCluster

    cluster_dicts = cluster_weekly_themes(week_start)

    # Idempotent: remove stale clusters for this week before re-inserting
    ThemeCluster.objects.filter(week_start_date=week_start).delete()

    created = 0
    for data in cluster_dicts:
        ThemeCluster.objects.create(**data)
        created += 1

    logger.info("Created %d theme clusters for week %s.", created, week_start)
    return created
