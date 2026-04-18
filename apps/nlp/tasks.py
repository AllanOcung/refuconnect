
from __future__ import annotations

import logging
from datetime import date, timedelta

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=0)
def process_feedback_nlp(self, feedback_id: int) -> None:
    
    from apps.nlp.pipeline.consumer import PipelineConsumer

    logger.info("feedback_id=%s: NLP pipeline task started.", feedback_id)
    try:
        PipelineConsumer().run(feedback_id)
    except Exception as exc:
        
        logger.critical(
            "feedback_id=%s: NLP pipeline exhausted all retries: %s",
            feedback_id,
            exc,
            exc_info=True,
        )


@shared_task(bind=True, max_retries=0)
def run_theme_clustering(self) -> dict:
    
    from apps.nlp.pipeline.theme_clusterer import ThemeClusterer

    today = date.today()
    week_start = today - timedelta(days=today.weekday() + 7)  

    logger.info("ThemeClusterer task started for week %s.", week_start)
    try:
        ThemeClusterer().run()
        logger.info("ThemeClusterer task completed for week %s.", week_start)
        return {"week": str(week_start), "status": "ok"}
    except Exception as exc:
        logger.error("run_theme_clustering task failed: %s", exc, exc_info=True)
        return {"week": str(week_start), "status": "error"}


@shared_task(bind=True, max_retries=0)
def run_model_retraining(self) -> None:
    
    from apps.nlp.pipeline.model_retrainer import ModelRetrainer

    logger.info("ModelRetrainer task started.")
    try:
        ModelRetrainer().run()
        logger.info("ModelRetrainer task completed.")
    except Exception as exc:
        logger.error("run_model_retraining task failed: %s", exc, exc_info=True)