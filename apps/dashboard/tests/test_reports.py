import pytest
from datetime import timedelta

from django.utils import timezone
from django.urls import reverse

from apps.common.audit import AuditAction
from apps.dashboard.models import AuditLog, ReportExport
from apps.feedback.models import Feedback, Sentiment


@pytest.mark.django_db
def test_pdf_report_returns_pdf_content_type(auth_client, sample_feedback, monkeypatch):
    monkeypatch.setattr(
        "apps.dashboard.services.report_generator.ReportGenerator._generate_pdf",
        lambda self, queryset, filters, template_id, user: b"%PDF-1.4 test",
    )
    response = auth_client.post(
        reverse("dashboard:reports-generate"),
        {"format": "pdf", "template_id": "executive_summary", "filters": {}},
        format="json",
    )
    assert response.status_code == 200
    assert response["Content-Type"].startswith("application/pdf")


@pytest.mark.django_db
def test_excel_report_returns_xlsx_content_type(auth_client, sample_feedback):
    response = auth_client.post(
        reverse("dashboard:reports-generate"),
        {"format": "xlsx", "template_id": "executive_summary", "filters": {}},
        format="json",
    )
    assert response.status_code == 200
    assert response["Content-Type"].startswith(
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )


@pytest.mark.django_db
def test_report_generation_logs_audit_event(auth_client, sample_feedback):
    auth_client.post(
        reverse("dashboard:reports-generate"),
        {"format": "xlsx", "template_id": "executive_summary", "filters": {}},
        format="json",
    )
    assert AuditLog.objects.filter(action=AuditAction.REPORT_EXPORTED).exists()


@pytest.mark.django_db
def test_report_respects_date_filters(auth_client, monkeypatch):
    sentiment, _created = Sentiment.objects.get_or_create(
        sentiment_label="Neutral",
        defaults={"display_colour": "#aaaaaa"},
    )
    Feedback.objects.create(
        anonymous_user_id="anon-old",
        message_text="Older feedback",
        message_text_en="Older feedback",
        channel=Feedback.Channel.SMS,
        status=Feedback.Status.NEW,
        urgency_level=Feedback.UrgencyLevel.LOW,
        language="en",
        sentiment=sentiment,
        submitted_at=timezone.now() - timedelta(days=12),
    )
    Feedback.objects.create(
        anonymous_user_id="anon-new",
        message_text="Recent feedback",
        message_text_en="Recent feedback",
        channel=Feedback.Channel.SMS,
        status=Feedback.Status.NEW,
        urgency_level=Feedback.UrgencyLevel.LOW,
        language="en",
        sentiment=sentiment,
        submitted_at=timezone.now(),
    )

    monkeypatch.setattr(
        "apps.dashboard.services.report_generator.ReportGenerator._generate_excel",
        lambda self, queryset, filters: b"xlsx-content",
    )

    response = auth_client.post(
        reverse("dashboard:reports-generate"),
        {
            "format": "xlsx",
            "template_id": "executive_summary",
            "filters": {
                "date_to": (timezone.now() - timedelta(days=7)).isoformat(),
            },
        },
        format="json",
    )

    assert response.status_code == 200
    export_id = int(response["X-Report-Export-ID"])
    export = ReportExport.objects.get(export_id=export_id)
    assert export.row_count == 1


@pytest.mark.django_db
def test_report_history_shows_past_exports(auth_client, ngo_staff_user):
    ReportExport.objects.create(
        user=ngo_staff_user,
        template_id="executive_summary",
        format="xlsx",
        filters_snapshot={},
        row_count=0,
    )
    response = auth_client.get(reverse("dashboard:reports-history"))
    assert response.status_code == 200
    assert response.data["count"] == 1


@pytest.mark.django_db
def test_large_report_returns_task_id(auth_client, monkeypatch):
    class FakeTask:
        id = "task-123"

    monkeypatch.setattr(
        "apps.dashboard.views.reports.ReportGenerator.row_count",
        lambda self, filters: 1001,
    )
    monkeypatch.setattr(
        "apps.dashboard.views.reports.generate_report_export_task.delay",
        lambda export_id: FakeTask(),
    )

    response = auth_client.post(
        reverse("dashboard:reports-generate"),
        {"format": "xlsx", "template_id": "executive_summary", "filters": {}},
        format="json",
    )

    assert response.status_code == 202
    assert response.data["task_id"] == "task-123"
    export = ReportExport.objects.get(export_id=response.data["export_id"])
    assert export.task_id == "task-123"
    assert export.status == ReportExport.Status.QUEUED


@pytest.mark.django_db
def test_report_task_status_returns_export(auth_client, ngo_staff_user):
    export = ReportExport.objects.create(
        user=ngo_staff_user,
        template_id="executive_summary",
        format="xlsx",
        filters_snapshot={},
        row_count=1001,
        status=ReportExport.Status.COMPLETED,
        task_id="task-456",
    )

    response = auth_client.get(reverse("dashboard:reports-task-status", args=["task-456"]))

    assert response.status_code == 200
    assert response.data["export_id"] == export.export_id
    assert response.data["status"] == ReportExport.Status.COMPLETED


@pytest.mark.django_db
def test_report_task_download_returns_file(auth_client, ngo_staff_user):
    ReportExport.objects.create(
        user=ngo_staff_user,
        template_id="executive_summary",
        format="xlsx",
        filters_snapshot={},
        row_count=1001,
        status=ReportExport.Status.COMPLETED,
        task_id="task-789",
        file_name="report.xlsx",
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        file_data=b"report-bytes",
    )

    response = auth_client.get(
        reverse("dashboard:reports-task-download", args=["task-789"])
    )

    assert response.status_code == 200
    assert response.content == b"report-bytes"
