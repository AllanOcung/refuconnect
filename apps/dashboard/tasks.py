from __future__ import annotations

from datetime import timedelta

from celery import shared_task
from django.core.mail import EmailMessage
from django.utils import timezone

from apps.dashboard.models import ReportExport, ScheduledReport
from apps.dashboard.services.report_generator import ReportGenerator


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
