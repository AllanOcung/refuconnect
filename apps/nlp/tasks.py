"""NLP app Celery tasks."""
from __future__ import annotations

import logging
from datetime import date, timedelta

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=0, default_retry_delay=30)
def process_feedback_nlp(self, feedback_id: int) -> None:
    """
    Real-time task: process a single feedback record through the NLP pipeline.

    Retry logic (exponential backoff) is handled inside PipelineConsumer, not
    here, so max_retries=0 prevents Celery from double-retrying.
    """
    from apps.nlp.pipeline.consumer import process_feedback

    try:
        process_feedback(feedback_id)
    except Exception:
        logger.exception(
            "NLP task failed for feedback_id=%d.",
            feedback_id,
        )
        # Do not re-raise — prevents blocking the queue on a permanently broken record.


# Backward-compatibility alias so existing callers don't break during rollout.
process_feedback_async = process_feedback_nlp


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


@shared_task
def run_model_retraining() -> dict:
    """
    Celery Beat task: log a model retraining run on the 1st of every month at 03:00 UTC.

    Collects NGO corrections from AuditLog for the past 30 days and records a
    training-run entry via AIModelLog.  Full fine-tuning is reserved for a future
    GPU-enabled worker; this task ensures the audit trail is always written.
    """
    from apps.nlp.pipeline.model_retrainer import collect_corrections_and_log

    try:
        result = collect_corrections_and_log()
        logger.info("Monthly model retraining log complete: %s", result)
        return result
    except Exception:
        logger.exception("Monthly model retraining task failed.")
        return {"error": True}
