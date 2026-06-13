"""NLP app Celery tasks."""
from __future__ import annotations

import logging
from datetime import date, timedelta

from celery import shared_task

logger = logging.getLogger(__name__)

# Exponential back-off countdowns (seconds) applied between retries: the first
# retry waits 30 s, the second 120 s, the third 300 s.
_RETRY_COUNTDOWNS = [30, 120, 300]


@shared_task(bind=True, max_retries=3, default_retry_delay=30)
def process_feedback_nlp(self, feedback_id: int) -> None:
    """
    Real-time task: process a single feedback record through the NLP pipeline.

    The pipeline runs once per execution (see ``consumer.process_feedback``).
    On failure the task reschedules itself with exponential back-off via
    ``self.retry`` — a *non-blocking* retry: Celery re-queues the task for later
    delivery, leaving the worker free to process other feedback in the meantime
    instead of sleeping. After the retries are exhausted the record is marked
    'ProcessingFailed' and ops are alerted.
    """
    from apps.nlp.pipeline.consumer import process_feedback

    try:
        process_feedback(feedback_id)
    except Exception as exc:
        attempt = self.request.retries  # 0 on the first execution
        if attempt < self.max_retries:
            countdown = _RETRY_COUNTDOWNS[min(attempt, len(_RETRY_COUNTDOWNS) - 1)]
            logger.warning(
                "process_feedback_nlp: feedback_id=%d failed (attempt %d/%d) — "
                "retrying in %ds.",
                feedback_id,
                attempt + 1,
                self.max_retries + 1,
                countdown,
            )
            raise self.retry(exc=exc, countdown=countdown)

        # Retries exhausted — mark terminal failure and alert ops.
        logger.critical(
            "process_feedback_nlp: feedback_id=%d failed after %d attempts — "
            "marking ProcessingFailed.",
            feedback_id,
            self.max_retries + 1,
        )
        _mark_processing_failed(feedback_id)


def _mark_processing_failed(feedback_id: int) -> None:
    """Set a feedback record to 'ProcessingFailed' and alert ops for follow-up."""
    from apps.feedback.models import Feedback
    from apps.nlp.pipeline.alert_manager import AlertManager

    try:
        feedback = Feedback.objects.get(feedback_id=feedback_id)
    except Feedback.DoesNotExist:
        logger.error(
            "_mark_processing_failed: feedback_id=%d not found.", feedback_id
        )
        return

    feedback.status = "ProcessingFailed"
    feedback.save(update_fields=["status"])
    AlertManager.dispatch(feedback, None)


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
