import pytest
from django.urls import reverse

from apps.common.audit import AuditAction
from apps.dashboard.models import AuditLog, ReportExport


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
