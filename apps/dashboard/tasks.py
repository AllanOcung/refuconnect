from __future__ import annotations

import logging
from datetime import timedelta

from celery import shared_task
from django.core.mail import EmailMessage
from django.utils import timezone

from apps.dashboard.models import ReportExport, ScheduledReport
from apps.dashboard.services.report_generator import ReportGenerator

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=2, default_retry_delay=120)
def send_urgent_feedback_alert(self, feedback_id: int) -> dict:
    """
    Email every alert-subscribed active staff member about a high-urgency feedback.

    Enqueued by AlertManager when a high-urgency Alert is first created, so the
    NLP pipeline is never blocked by email delivery. Recipients are active users
    with ``receive_alerts=True``.
    """
    from apps.dashboard.models import User
    from apps.dashboard.services.emails import send_urgent_alert_email
    from apps.feedback.models import Feedback

    try:
        feedback = Feedback.objects.select_related("sentiment").get(feedback_id=feedback_id)
    except Feedback.DoesNotExist:
        logger.warning("send_urgent_feedback_alert: feedback_id=%s not found", feedback_id)
        return {"feedback_id": feedback_id, "sent": 0}

    recipients = (
        User.objects.filter(status=User.Status.ACTIVE, receive_alerts=True)
        .exclude(email="")
    )
    sent = 0
    for user in recipients:
        if send_urgent_alert_email(user, feedback):
            sent += 1
    logger.info(
        "send_urgent_feedback_alert: feedback_id=%s emailed %d/%d staff",
        feedback_id,
        sent,
        recipients.count(),
    )
    return {"feedback_id": feedback_id, "sent": sent}


@shared_task(bind=True)
def generate_report_export_task(self, export_id: int) -> int:
    """Generate a queued report export and persist the completed file."""

    export = ReportExport.objects.select_related("user").get(pk=export_id)
    export.status = ReportExport.Status.PROCESSING
    export.error_message = None
    export.save(update_fields=["status", "error_message"])

    try:
        generator = ReportGenerator()
        file_bytes, filename = generator.generate(
            export.format,
            export.filters_snapshot,
            export.template_id,
            export.user,
        )
        export.status = ReportExport.Status.COMPLETED
        export.file_name = filename
        export.content_type = generator.content_type(export.format)
        export.file_data = file_bytes
        export.file_size_bytes = len(file_bytes)
        export.completed_at = timezone.now()
        export.save(
            update_fields=[
                "status",
                "file_name",
                "content_type",
                "file_data",
                "file_size_bytes",
                "completed_at",
            ]
        )
    except Exception as exc:
        export.status = ReportExport.Status.FAILED
        export.error_message = str(exc)
        export.completed_at = timezone.now()
        export.save(update_fields=["status", "error_message", "completed_at"])
        raise

    return export.export_id


@shared_task
def send_scheduled_report() -> int:
    """Generate and email due scheduled reports."""

    now = timezone.now()
    due_reports = ScheduledReport.objects.select_related("user").filter(
        is_active=True,
        next_run_at__lte=now,
    )
    sent_count = 0
    generator = ReportGenerator()
    for scheduled in due_reports:
        file_bytes, filename = generator.generate(
            scheduled.format,
            scheduled.filters,
            scheduled.template_id,
            scheduled.user,
        )
        message = EmailMessage(
            subject="Your scheduled RefuConnect report",
            body="Attached is your scheduled RefuConnect dashboard report.",
            to=[scheduled.user.email],
        )
        content_type = (
            "application/pdf"
            if scheduled.format == ScheduledReport.Format.PDF
            else "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        message.attach(filename, file_bytes, content_type)
        message.send(fail_silently=True)
        scheduled.last_sent_at = now
        scheduled.next_run_at = _next_run_at(now, scheduled.frequency)
        scheduled.save(update_fields=["last_sent_at", "next_run_at"])
        sent_count += 1
    return sent_count


def _next_run_at(now, frequency: str):
    if frequency == ScheduledReport.Frequency.WEEKLY:
        return now + timedelta(days=7)
    if frequency == ScheduledReport.Frequency.MONTHLY:
        return now + timedelta(days=30)
    return now + timedelta(days=1)
