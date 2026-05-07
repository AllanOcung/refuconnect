import pytest
from django.urls import reverse

from apps.common.audit import AuditAction
from apps.dashboard.models import AuditLog
from apps.feedback.models import Alert


@pytest.mark.django_db
def test_alert_list_returns_open_alerts_first(auth_client, sample_feedback):
    Alert.objects.create(
        feedback=sample_feedback,
        priority_level=Alert.Priority.HIGH,
        description="Urgent",
        status=Alert.AlertStatus.OPEN,
    )
    response = auth_client.get(reverse("dashboard:alert-list"))
    assert response.status_code == 200
    assert response.data["open_count"] == 1


@pytest.mark.django_db
def test_acknowledge_sets_status_and_user(auth_client, sample_feedback, ngo_staff_user):
    alert = Alert.objects.create(
        feedback=sample_feedback,
        priority_level=Alert.Priority.HIGH,
        description="Urgent",
        status=Alert.AlertStatus.OPEN,
    )
    response = auth_client.post(reverse("dashboard:alert-acknowledge", args=[alert.alert_id]))
    assert response.status_code == 200
    alert.refresh_from_db()
    assert alert.status == Alert.AlertStatus.ACKNOWLEDGED
    assert alert.acknowledged_by == ngo_staff_user


@pytest.mark.django_db
def test_acknowledge_logs_audit_event(auth_client, sample_feedback):
    alert = Alert.objects.create(
        feedback=sample_feedback,
        priority_level=Alert.Priority.HIGH,
        status=Alert.AlertStatus.OPEN,
    )
    auth_client.post(reverse("dashboard:alert-acknowledge", args=[alert.alert_id]))
    assert AuditLog.objects.filter(action=AuditAction.ALERT_ACKNOWLEDGED).exists()


@pytest.mark.django_db
def test_resolve_sets_status_resolved(auth_client, sample_feedback):
    alert = Alert.objects.create(
        feedback=sample_feedback,
        priority_level=Alert.Priority.HIGH,
        status=Alert.AlertStatus.OPEN,
    )
    response = auth_client.post(reverse("dashboard:alert-resolve", args=[alert.alert_id]))
    assert response.status_code == 200
    alert.refresh_from_db()
    assert alert.status == Alert.AlertStatus.RESOLVED


@pytest.mark.django_db
def test_alert_stats_returns_counts_by_status(auth_client, sample_feedback):
    Alert.objects.create(
        feedback=sample_feedback,
        priority_level=Alert.Priority.HIGH,
        status=Alert.AlertStatus.OPEN,
    )
    response = auth_client.get(reverse("dashboard:alert-stats"))
    assert response.status_code == 200
    assert response.data["Open"] == 1
