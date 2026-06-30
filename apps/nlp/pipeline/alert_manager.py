"""
AlertManager — creates Alert records and logs for high-urgency feedback.

Called by PipelineConsumer after the full pipeline runs when urgency_level='High'.
Kept in a dedicated class so the consumer doesn't need to know about the Alert
model directly, and so alert behaviour can be extended (e.g. push notifications)
without touching the pipeline.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


class AlertManager:
    """Creates and dispatches alerts for high-urgency feedback."""

    @staticmethod
    def dispatch(feedback, urgency_rule: str | None = None) -> None:
        """
        Create an Alert record for *feedback* if one does not already exist.

        Parameters
        ----------
        feedback:
            A saved ``Feedback`` model instance with urgency_level='High'.
        urgency_rule:
            Optional rule string from ``UrgencyAssessor`` (e.g. ``keyword:emergency``).
        """
        from apps.feedback.models import Alert

        try:
            # Avoid creating a duplicate alert if the record was reprocessed
            if Alert.objects.filter(feedback=feedback).exists():
                logger.info(
                    "Alert already exists for feedback_id=%d — skipping.",
                    feedback.feedback_id,
                )
                return

            Alert.objects.create(
                feedback=feedback,
                priority_level="High",
                description=(
                    f"Auto-generated: high urgency detected in "
                    f"Feedback #{feedback.feedback_id}. "
                    f"Sentiment: {feedback.sentiment or 'N/A'}. "
                    f"Rule: {urgency_rule or 'unknown'}."
                ),
            )
            logger.info(
                "Alert created for high-urgency feedback_id=%d.",
                feedback.feedback_id,
            )

            # Email alert-subscribed staff — only for genuinely high-urgency
            # feedback. dispatch() is also used for processing-failure alerts
            # (passed a non-High feedback), which must not trigger this email.
            if getattr(feedback, "urgency_level", None) == "High":
                try:
                    from apps.dashboard.tasks import send_urgent_feedback_alert

                    send_urgent_feedback_alert.delay(feedback.feedback_id)
                except Exception:
                    logger.exception(
                        "AlertManager.dispatch: failed to enqueue urgent alert "
                        "email for feedback_id=%d.",
                        feedback.feedback_id,
                    )
        except Exception:
            # Alert creation is best-effort — never fail the pipeline over it.
            logger.exception(
                "AlertManager.dispatch failed for feedback_id=%d.",
                feedback.feedback_id,
            )
