"""
JWT authentication views with audit logging and account-lock enforcement.
"""
from __future__ import annotations

import logging

from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.exceptions import TokenError

from apps.common.audit import AuditAction, log_audit_event
from apps.common.exceptions import AccountLockedError
from apps.dashboard.models import User

logger = logging.getLogger(__name__)

_MAX_FAILED_ATTEMPTS = 5


class LoginView(APIView):
    """Authenticate with email + password; return JWT access and refresh tokens."""

    permission_classes = [AllowAny]

    def post(self, request: Request) -> Response:
        email = request.data.get("email", "").strip().lower()
        password = request.data.get("password", "")

        if not email or not password:
            return Response(
                {"detail": "email and password are required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            user = User.objects.get(email=email)
        except User.DoesNotExist:
            log_audit_event(None, AuditAction.LOGIN_FAILED, request=request)
            return Response(
                {"detail": "Invalid credentials."},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        if user.status == User.Status.LOCKED:
            raise AccountLockedError()

        if user.status not in (User.Status.ACTIVE,):
            return Response(
                {"detail": f"Account is {user.status.lower()}. Contact an administrator."},
                status=status.HTTP_403_FORBIDDEN,
            )

        if not user.check_password(password):
            user.increment_failed_login(lock_threshold=_MAX_FAILED_ATTEMPTS)
            log_audit_event(user, AuditAction.LOGIN_FAILED, request=request)
            if user.status == User.Status.LOCKED:
                log_audit_event(user, AuditAction.ACCOUNT_LOCKED, request=request)
                raise AccountLockedError()
            return Response(
                {"detail": "Invalid credentials."},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        # Successful authentication
        user.reset_failed_login()
        user.last_login_at = timezone.now()
        user.save(update_fields=["last_login_at", "failed_login_count"])

        refresh = RefreshToken.for_user(user)
        log_audit_event(user, AuditAction.LOGIN, request=request)

        return Response(
            {
                "access": str(refresh.access_token),
                "refresh": str(refresh),
                "user_id": user.user_id,
                "email": user.email,
                "full_name": user.full_name,
                "role": user.role,
            },
            status=status.HTTP_200_OK,
        )


class LogoutView(APIView):
    """Blacklist the refresh token on logout."""

    permission_classes = [IsAuthenticated]

    def post(self, request: Request) -> Response:
        refresh_token = request.data.get("refresh")
        if not refresh_token:
            return Response(
                {"detail": "refresh token is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            token = RefreshToken(refresh_token)
            token.blacklist()
        except TokenError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        log_audit_event(request.user, AuditAction.LOGOUT, request=request)
        return Response({"detail": "Logged out successfully."}, status=status.HTTP_200_OK)


class PasswordChangeView(APIView):
    """Change the authenticated user's password."""

    permission_classes = [IsAuthenticated]

    def post(self, request: Request) -> Response:
        old_password = request.data.get("old_password", "")
        new_password = request.data.get("new_password", "")

        if not old_password or not new_password:
            return Response(
                {"detail": "old_password and new_password are required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if len(new_password) < 12:
            return Response(
                {"detail": "New password must be at least 12 characters."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        user: User = request.user  # type: ignore[assignment]
        if not user.check_password(old_password):
            return Response(
                {"detail": "Old password is incorrect."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        user.set_password(new_password)
        user.save(update_fields=["password"])
        log_audit_event(user, AuditAction.PASSWORD_RESET, request=request)
        return Response({"detail": "Password changed successfully."}, status=status.HTTP_200_OK)
