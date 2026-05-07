import pytest
from django.urls import reverse

from apps.dashboard.models import User


@pytest.mark.django_db
def test_ngo_staff_cannot_access_user_management(auth_client):
    response = auth_client.get(reverse("dashboard:user-list"))
    assert response.status_code == 403


@pytest.mark.django_db
def test_administrator_can_invite_user(admin_client):
    response = admin_client.post(
        reverse("dashboard:user-invite"),
        {
            "full_name": "Invited User",
            "email": "invited@example.test",
            "role": User.Role.NGO_STAFF,
        },
        format="json",
    )
    assert response.status_code == 201
    assert response.data["status"] == User.Status.PENDING_VERIFICATION


@pytest.mark.django_db
def test_user_responses_exclude_sensitive_fields(admin_client, ngo_staff_user):
    response = admin_client.get(reverse("dashboard:user-detail", args=[ngo_staff_user.user_id]))
    assert response.status_code == 200
    for field in ("password", "mfa_secret", "failed_login_count"):
        assert field not in response.data


@pytest.mark.django_db
def test_cannot_delete_own_account(admin_client, admin_user):
    response = admin_client.delete(reverse("dashboard:user-detail", args=[admin_user.user_id]))
    assert response.status_code == 400


@pytest.mark.django_db
def test_cannot_delete_last_administrator(admin_client, admin_user, ngo_staff_user):
    response = admin_client.delete(
        reverse("dashboard:user-detail", args=[ngo_staff_user.user_id])
    )
    assert response.status_code == 204
    admin_user.refresh_from_db()
    assert admin_user.status == User.Status.ACTIVE


@pytest.mark.django_db
def test_unlock_resets_failed_count_and_status(admin_client, ngo_staff_user):
    ngo_staff_user.status = User.Status.LOCKED
    ngo_staff_user.failed_login_count = 5
    ngo_staff_user.save(update_fields=["status", "failed_login_count"])
    response = admin_client.post(reverse("dashboard:user-unlock", args=[ngo_staff_user.user_id]))
    assert response.status_code == 200
    ngo_staff_user.refresh_from_db()
    assert ngo_staff_user.status == User.Status.ACTIVE
    assert ngo_staff_user.failed_login_count == 0


@pytest.mark.django_db
def test_user_list_supports_role_filter(admin_client, ngo_staff_user):
    response = admin_client.get(reverse("dashboard:user-list"), {"role": User.Role.NGO_STAFF})
    assert response.status_code == 200
    assert response.data["count"] == 1
