from __future__ import annotations

import logging
from datetime import date, timedelta

import numpy as np
from django.conf import settings
from sklearn.cluster import KMeans
from sklearn.feature_extraction.text import TfidfVectorizer

try:
    from apps.feedback.models import Feedback
    from apps.nlp.models import FeedbackCluster, ThemeCluster
except Exception:
    Feedback = None
    FeedbackCluster = None
    ThemeCluster = None

logger = logging.getLogger(__name__)

_MIN_RECORDS: int = getattr(settings, "THEME_CLUSTERER_MIN_RECORDS", 5)
_MAX_FEATURES: int = getattr(settings, "THEME_CLUSTERER_MAX_FEATURES", 1000)
_MAX_CLUSTERS: int = getattr(settings, "THEME_CLUSTERER_MAX_CLUSTERS", 20)
_MAX_KEYWORDS: int = getattr(settings, "THEME_CLUSTERER_MAX_KEYWORDS", 10)
_ELBOW_THRESHOLD: float = getattr(settings, "THEME_CLUSTERER_ELBOW_THRESHOLD", 0.10)


def _get_week_start() -> date:
    today = date.today()
    return today - timedelta(days=today.weekday())


def _elbow_k(inertias: list[float]) -> int:
    if len(inertias) < 2:
        return 2
    total_drop = inertias[0] - inertias[-1]
    if total_drop == 0:
        return 2
    for i in range(len(inertias) - 1):
        if (inertias[i] - inertias[i + 1]) / total_drop < _ELBOW_THRESHOLD:
            return i + 2  # k is offset by 2 because the range starts at 2
    return len(inertias) + 1


class ThemeClusterer:

    def run(self) -> None:
        # Use module-level names (patchable in tests) rather than local re-imports.
        import apps.nlp.pipeline.theme_clusterer as _self_mod
        _Feedback = _self_mod.Feedback
        _FeedbackCluster = _self_mod.FeedbackCluster
        _ThemeCluster = _self_mod.ThemeCluster

        week_start = _get_week_start()
        week_end = week_start + timedelta(days=7)
        logger.info("ThemeClusterer: running for week %s – %s.", week_start, week_end)

        records = list(
            _Feedback.objects.filter(
                status="Processed",
                processed_at__date__gte=week_start,
                processed_at__date__lt=week_end,
            ).select_related("sentiment")
        )

        if len(records) < _MIN_RECORDS:
            logger.warning(
                "ThemeClusterer: only %d records found (minimum %d); skipping.",
                len(records),
                _MIN_RECORDS,
            )
            return

        texts = [r.message_text_en or r.message_text or "" for r in records]
        n = len(records)

        vectoriser = TfidfVectorizer(
            max_features=_MAX_FEATURES,
            stop_words="english",
            min_df=1,
            ngram_range=(1, 2),
        )
        try:
            X = vectoriser.fit_transform(texts)
        except ValueError as exc:
            logger.error("ThemeClusterer: TF-IDF vectorisation failed: %s", exc)
            return

        feature_names: np.ndarray = np.array(vectoriser.get_feature_names_out())
        max_k = min(_MAX_CLUSTERS, n // 5)

        if max_k < 2:
            logger.warning(
                "ThemeClusterer: insufficient records for meaningful clustering (%d).", n
            )
            return

        max_k = min(max_k, n)

        inertias: list[float] = []
        for k in range(2, max_k + 1):
            km = KMeans(n_clusters=k, random_state=42, n_init="auto")
            km.fit(X)
            inertias.append(float(km.inertia_))

        optimal_k = min(_elbow_k(inertias), n)
        logger.info("ThemeClusterer: optimal k=%d for %d records.", optimal_k, n)

        try:
            final_km = KMeans(n_clusters=optimal_k, random_state=42, n_init="auto")
            labels: np.ndarray = final_km.fit_predict(X)
        except Exception as exc:
            logger.error("ThemeClusterer: final clustering failed: %s", exc, exc_info=True)
            return

        # Idempotent: delete stale clusters and junctions before writing.
        _ThemeCluster.objects.filter(week_start_date=week_start).delete()
        _FeedbackCluster.objects.filter(week_start_date=week_start).delete()

        cluster_objs: dict[int, object] = {}

        for cluster_idx in range(optimal_k):
            member_mask: np.ndarray = labels == cluster_idx
            member_records = [records[i] for i, m in enumerate(member_mask) if m]

            if not member_records:
                continue

            centroid = final_km.cluster_centers_[cluster_idx]
            top_indices = centroid.argsort()[-_MAX_KEYWORDS:][::-1]
            top_keywords: list[str] = feature_names[top_indices].tolist()
            cluster_label = " / ".join(top_keywords[:3])

            sentiments = [
                r.sentiment.sentiment_label
                for r in member_records
                if r.sentiment_id is not None
            ]
            dominant_sentiment = (
                max(set(sentiments), key=sentiments.count) if sentiments else ""
            )

            cluster_objs[cluster_idx] = _ThemeCluster.objects.create(
                week_start_date=week_start,
                cluster_index=cluster_idx,
                label=cluster_label,
                top_keywords=top_keywords,
                record_count=len(member_records),
                dominant_sentiment=dominant_sentiment,
            )

        junction_records = [
            _FeedbackCluster(
                feedback=records[i],
                cluster=cluster_objs[labels[i]],
                week_start_date=week_start,
            )
            for i in range(n)
            if labels[i] in cluster_objs
        ]
        _FeedbackCluster.objects.bulk_create(junction_records, batch_size=500)

        logger.info(
            "ThemeClusterer: created %d clusters and %d junction records for week %s.",
            len(cluster_objs),
            len(junction_records),
            week_start,
        )