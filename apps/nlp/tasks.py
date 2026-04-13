"""NLP app Celery tasks."""
from __future__ import annotations

import logging
from datetime import date, timedelta

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3, default_retry_delay=120)
def process_feedback_async(self, feedback_id: int) -> None:
    """Process a single feedback record through the NLP pipeline."""
    try:
        from apps.nlp.pipeline.consumer import process_feedback

        process_feedback(feedback_id)
    except Exception as exc:
        logger.exception(
            "NLP task failed for feedback %d (attempt %d/%d).",
            feedback_id,
            self.request.retries + 1,
            self.max_retries + 1,
        )
        raise self.retry(exc=exc)


@shared_task
def run_weekly_theme_clustering() -> dict:
    """
    Celery Beat task: generate ThemeCluster records for the previous ISO week.

    Runs every Monday at 02:00 UTC so the previous week is fully closed.
    """
    from apps.nlp.pipeline.theme_clusterer import save_weekly_clusters

    # Previous Monday
    today = date.today()
    last_monday = today - timedelta(days=today.weekday() + 7)

    try:
        count = save_weekly_clusters(last_monday)
        logger.info("Weekly clustering complete: %d clusters for %s.", count, last_monday)
        return {"week": str(last_monday), "clusters_created": count}
    except Exception:
        logger.exception("Weekly theme clustering failed.")
        return {"week": str(last_monday), "clusters_created": 0, "error": True}
