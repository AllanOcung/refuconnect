import pyotp
import pytest
from django.core.cache import cache
from django.urls import reverse

from apps.common.audit import AuditAction
from apps.dashboard.models import AuditLog, User


@pytest.mark.django_db
def test_login_success_returns_tokens(api_client, ngo_staff_user):
    response = api_client.post(
        reverse("dashboard:login"),
        {"email": ngo_staff_user.email, "password": "StaffPass123!"},
        format="json",
    )
    assert response.status_code == 200
    assert "access" in response.data
    assert response.data["user"]["role"] == User.Role.NGO_STAFF


@pytest.mark.django_db
def test_login_wrong_password_returns_401(api_client, ngo_staff_user):
    response = api_client.post(
        reverse("dashboard:login"),
        {"email": ngo_staff_user.email, "password": "wrong"},
        format="json",
    )
    assert response.status_code == 401


@pytest.mark.django_db
def test_login_increments_failed_count(api_client, ngo_staff_user):
    api_client.post(
        reverse("dashboard:login"),
        {"email": ngo_staff_user.email, "password": "wrong"},
        format="json",
    )
    ngo_staff_user.refresh_from_db()
    assert ngo_staff_user.failed_login_count == 1


@pytest.mark.django_db
def test_login_locks_account_after_5_failures(api_client, ngo_staff_user):
    for _ in range(5):
        api_client.post(
            reverse("dashboard:login"),
            {"email": ngo_staff_user.email, "password": "wrong"},
            format="json",
        )
    ngo_staff_user.refresh_from_db()
    assert ngo_staff_user.status == User.Status.LOCKED
    assert AuditLog.objects.filter(action=AuditAction.ACCOUNT_LOCKED).exists()


@pytest.mark.django_db
def test_login_locked_account_returns_403(api_client, ngo_staff_user):
    ngo_staff_user.status = User.Status.LOCKED
    ngo_staff_user.save(update_fields=["status"])
    response = api_client.post(
        reverse("dashboard:login"),
        {"email": ngo_staff_user.email, "password": "StaffPass123!"},
        format="json",
    )
    assert response.status_code == 403


@pytest.mark.django_db
def test_login_administrator_without_mfa_code_returns_mfa_required(api_client, admin_user):
    admin_user.mfa_secret = pyotp.random_base32()
    admin_user.save(update_fields=["mfa_secret"])
    response = api_client.post(
        reverse("dashboard:login"),
        {"email": admin_user.email, "password": "AdminPass123!"},
        format="json",
    )
    assert response.status_code == 200
    assert response.data == {"mfa_required": True}


@pytest.mark.django_db
def test_login_administrator_with_valid_mfa_code_succeeds(api_client, admin_user):
    secret = pyotp.random_base32()
    admin_user.mfa_secret = secret
    admin_user.save(update_fields=["mfa_secret"])
    response = api_client.post(
        reverse("dashboard:login"),
        {
            "email": admin_user.email,
            "password": "AdminPass123!",
            "totp_code": pyotp.TOTP(secret).now(),
        },
        format="json",
    )
    assert response.status_code == 200
    assert "access" in response.data


@pytest.mark.django_db
def test_login_administrator_with_invalid_mfa_code_returns_401(api_client, admin_user):
    admin_user.mfa_secret = pyotp.random_base32()
    admin_user.save(update_fields=["mfa_secret"])
    response = api_client.post(
        reverse("dashboard:login"),
        {
            "email": admin_user.email,
            "password": "AdminPass123!",
            "totp_code": "000000",
        },
        format="json",
    )
    assert response.status_code == 401


@pytest.mark.django_db
def test_password_reset_request_always_returns_200(api_client):
    response = api_client.post(
        reverse("dashboard:password-reset-request"),
        {"email": "missing@example.test"},
        format="json",
    )
    assert response.status_code == 200


@pytest.mark.django_db
def test_password_reset_confirm_with_valid_token(api_client, ngo_staff_user):
    cache.set("pwd_reset:test-token", ngo_staff_user.user_id, timeout=3600)
    response = api_client.post(
        reverse("dashboard:password-reset-confirm"),
        {"token": "test-token", "new_password": "NewPass123!"},
        format="json",
    )
    assert response.status_code == 200


@pytest.mark.django_db
def test_password_reset_confirm_with_expired_token(api_client):
    response = api_client.post(
        reverse("dashboard:password-reset-confirm"),
        {"token": "missing", "new_password": "NewPass123!"},
        format="json",
    )
    assert response.status_code == 400


@pytest.mark.django_db
def test_logout_blacklists_refresh_token(api_client, ngo_staff_user):
    from rest_framework_simplejwt.tokens import RefreshToken

    refresh = RefreshToken.for_user(ngo_staff_user)
    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")
    response = api_client.post(
        reverse("dashboard:logout"),
        {"refresh": str(refresh)},
        format="json",
    )
    assert response.status_code == 200
