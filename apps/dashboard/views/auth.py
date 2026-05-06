from __future__ import annotations

import re
import secrets

import pyotp
from django.core.cache import cache
from django.core.mail import send_mail
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken

from apps.common.audit import AuditAction, log_audit_event
from apps.common.encryption import decrypt_field, encrypt_field
from apps.dashboard.models import User
from apps.dashboard.permissions import IsAdministrator

_MAX_FAILED_ATTEMPTS = 5


def _mfa_secret_for_use(stored_secret: str) -> str:
    try:
        return decrypt_field(stored_secret)
    except Exception:
        return stored_secret


def _password_is_valid(password: str) -> bool:
    return (
        len(password) >= 8
        and re.search(r"\d", password) is not None
        and re.search(r"[^A-Za-z0-9]", password) is not None
    )


class LoginView(APIView):
    permission_classes = [AllowAny]

    def post(self, request: Request) -> Response:
        email = request.data.get("email", "").strip().lower()
        password = request.data.get("password", "")

        try:
            user = User.objects.get(email=email)
        except User.DoesNotExist:
            log_audit_event(None, AuditAction.LOGIN_FAILED, request=request)
            return Response(
                {"detail": "Invalid credentials"},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        if user.status == User.Status.LOCKED:
            return Response(
                {"detail": "Account locked. Contact your administrator."},
                status=status.HTTP_403_FORBIDDEN,
            )
        if user.status == User.Status.SUSPENDED:
            return Response(
                {"detail": "Account suspended."},
                status=status.HTTP_403_FORBIDDEN,
            )
        if user.status == User.Status.PENDING_VERIFICATION:
            return Response(
                {"detail": "Account not yet verified."},
                status=status.HTTP_403_FORBIDDEN,
            )

        if not user.check_password(password):
            user.increment_failed_login(lock_threshold=_MAX_FAILED_ATTEMPTS)
            log_audit_event(user, AuditAction.LOGIN_FAILED, request=request)
            if user.status == User.Status.LOCKED:
                log_audit_event(user, AuditAction.ACCOUNT_LOCKED, request=request)
                send_mail(
                    "RefuConnect account locked",
                    "Your RefuConnect account has been locked after failed login attempts.",
                    None,
                    [user.email],
                    fail_silently=True,
                )
            return Response(
                {"detail": "Invalid credentials"},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        if user.role == User.Role.ADMINISTRATOR and user.mfa_secret:
            totp_code = request.data.get("totp_code")
            if not totp_code:
                return Response({"mfa_required": True}, status=status.HTTP_200_OK)
            secret = _mfa_secret_for_use(user.mfa_secret)
            if not pyotp.TOTP(secret).verify(str(totp_code)):
                return Response(
                    {"detail": "Invalid MFA code."},
                    status=status.HTTP_401_UNAUTHORIZED,
                )

        user.failed_login_count = 0
        user.last_login_at = timezone.now()
        user.save(update_fields=["failed_login_count", "last_login_at"])

        refresh = RefreshToken.for_user(user)
        log_audit_event(user, AuditAction.LOGIN, request=request)
        return Response(
            {
                "access": str(refresh.access_token),
                "refresh": str(refresh),
                "user": {
                    "user_id": user.user_id,
                    "full_name": user.full_name,
                    "role": user.role,
                    "preferred_language": user.preferred_language,
                },
            },
            status=status.HTTP_200_OK,
        )


class LogoutView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request: Request) -> Response:
        refresh_token = request.data.get("refresh")
        if not refresh_token:
            return Response(
                {"detail": "refresh token is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            RefreshToken(refresh_token).blacklist()
        except TokenError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        log_audit_event(request.user, AuditAction.LOGOUT, request=request)
        return Response({"detail": "Logged out successfully."}, status=status.HTTP_200_OK)


class PasswordResetRequestView(APIView):
    permission_classes = [AllowAny]

    def post(self, request: Request) -> Response:
        email = request.data.get("email", "").strip().lower()
        try:
            user = User.objects.get(email=email)
        except User.DoesNotExist:
            return Response(status=status.HTTP_200_OK)

        token = secrets.token_urlsafe(32)
        cache.set(f"pwd_reset:{token}", user.user_id, timeout=3600)
        send_mail(
            "RefuConnect password reset",
            f"Use this token to reset your password: {token}",
            None,
            [user.email],
            fail_silently=True,
        )
        log_audit_event(user, AuditAction.PASSWORD_RESET, request=request)
        return Response(status=status.HTTP_200_OK)


class PasswordResetConfirmView(APIView):
    permission_classes = [AllowAny]

    def post(self, request: Request) -> Response:
        token = request.data.get("token", "")
        new_password = request.data.get("new_password", "")
        user_id = cache.get(f"pwd_reset:{token}")
        if not user_id:
            return Response(
                {"detail": "Password reset token is invalid or expired."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if not _password_is_valid(new_password):
            return Response(
                {
                    "detail": "Password must be at least 8 characters and include a number and special character."
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        user = User.objects.get(pk=user_id)
        user.set_password(new_password)
        user.failed_login_count = 0
        user.status = User.Status.ACTIVE
        user.save(update_fields=["password", "failed_login_count", "status"])
        cache.delete(f"pwd_reset:{token}")
        log_audit_event(user, AuditAction.PASSWORD_RESET, request=request)
        return Response(status=status.HTTP_200_OK)


class MFASetupView(APIView):
    permission_classes = [IsAuthenticated, IsAdministrator]

    def post(self, request: Request) -> Response:
        secret = pyotp.random_base32()
        provisioning_uri = pyotp.TOTP(secret).provisioning_uri(
            name=request.user.email,
            issuer_name="RefuConnect",
        )
        return Response({"secret": secret, "qr_code_url": provisioning_uri})


class MFAConfirmView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request: Request) -> Response:
        pending_secret = request.data.get("pending_secret", "")
        totp_code = request.data.get("totp_code", "")
        if not pending_secret or not pyotp.TOTP(pending_secret).verify(str(totp_code)):
            return Response(
                {"detail": "Invalid MFA code."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            request.user.mfa_secret = encrypt_field(pending_secret)
        except Exception:
            request.user.mfa_secret = pending_secret
        request.user.save(update_fields=["mfa_secret"])
        return Response(status=status.HTTP_200_OK)
