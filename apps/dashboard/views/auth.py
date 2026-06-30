from __future__ import annotations

import secrets

import pyotp
from django.core.cache import cache
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
from apps.common.passwords import PASSWORD_POLICY_DETAIL, is_password_valid
from apps.common.throttles import (
    AcceptInviteRateThrottle,
    LoginRateThrottle,
    PasswordResetRateThrottle,
)
from apps.dashboard.models import User
from apps.dashboard.permissions import IsAdministrator
from apps.dashboard.services.backup_codes import (
    consume_backup_code,
    generate_backup_codes,
)
from apps.dashboard.services.emails import (
    send_account_locked_email,
    send_password_reset_email,
)
from apps.dashboard.views.mixins import AuditLogMixin

_MAX_FAILED_ATTEMPTS = 5


def _mfa_secret_for_use(stored_secret: str) -> str:
    """Decrypt a stored MFA secret. Raises ValueError if decryption fails."""
    return decrypt_field(stored_secret)


# Password policy moved to apps.common.passwords for shared use.


class LoginView(AuditLogMixin, APIView):
    permission_classes = [AllowAny]
    throttle_classes = [LoginRateThrottle]

    def post(self, request: Request) -> Response:
        raw_email = request.data.get("email", "")
        password = request.data.get("password", "")
        if not isinstance(raw_email, str) or not isinstance(password, str):
            return Response({"detail": "Invalid credentials"}, status=status.HTTP_401_UNAUTHORIZED)
        email = raw_email.strip().lower().replace("\x00", "")

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
                log_audit_event(
                    user,
                    AuditAction.ACCOUNT_LOCKED,
                    target_user=user,
                    request=request,
                )
                send_account_locked_email(user)
            return Response(
                {"detail": "Invalid credentials"},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        if user.mfa_secret:
            totp_code = request.data.get("totp_code")
            backup_code = request.data.get("backup_code")
            if not totp_code and not backup_code:
                return Response({"mfa_required": True}, status=status.HTTP_200_OK)
            secret = _mfa_secret_for_use(user.mfa_secret)
            mfa_ok = False
            if totp_code and pyotp.TOTP(secret).verify(str(totp_code)):
                mfa_ok = True
            elif backup_code and consume_backup_code(user, str(backup_code)):
                mfa_ok = True
                log_audit_event(
                    user,
                    AuditAction.BACKUP_CODE_USED,
                    target_user=user,
                    request=request,
                )
            if not mfa_ok:
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


class LogoutView(AuditLogMixin, APIView):
    permission_classes = [IsAuthenticated]
    audit_action = AuditAction.LOGOUT

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

        self.log_action(request)
        return Response({"detail": "Logged out successfully."}, status=status.HTTP_200_OK)


class PasswordResetRequestView(AuditLogMixin, APIView):
    permission_classes = [AllowAny]
    throttle_classes = [PasswordResetRateThrottle]
    audit_action = AuditAction.PASSWORD_RESET

    def post(self, request: Request) -> Response:
        email = request.data.get("email", "").strip().lower()
        try:
            user = User.objects.get(email=email)
        except User.DoesNotExist:
            return Response(status=status.HTTP_200_OK)

        token = secrets.token_urlsafe(32)
        cache.set(f"pwd_reset:{token}", user.user_id, timeout=3600)
        send_password_reset_email(user, token)
        # Keep user-specific logging for this endpoint.
        log_audit_event(
            user,
            self.audit_action,
            target_user=user,
            request=request,
        )
        return Response(status=status.HTTP_200_OK)


class PasswordResetConfirmView(AuditLogMixin, APIView):
    permission_classes = [AllowAny]
    audit_action = AuditAction.PASSWORD_RESET

    def post(self, request: Request) -> Response:
        token = request.data.get("token", "")
        new_password = request.data.get("new_password", "")
        user_id = cache.get(f"pwd_reset:{token}")
        if not user_id:
            return Response(
                {"detail": "Password reset token is invalid or expired."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if not is_password_valid(new_password):
            return Response(
                {"detail": PASSWORD_POLICY_DETAIL},
                status=status.HTTP_400_BAD_REQUEST,
            )
        user = User.objects.get(pk=user_id)
        user.set_password(new_password)
        user.failed_login_count = 0
        user.status = User.Status.ACTIVE
        user.password_changed_at = timezone.now()
        user.save(update_fields=["password", "failed_login_count", "status", "password_changed_at"])
        cache.delete(f"pwd_reset:{token}")
        log_audit_event(
            user,
            self.audit_action,
            target_user=user,
            request=request,
        )
        return Response(status=status.HTTP_200_OK)


class AcceptInviteView(AuditLogMixin, APIView):
    permission_classes = [AllowAny]
    throttle_classes = [AcceptInviteRateThrottle]
    audit_action = AuditAction.USER_MODIFIED

    def get(self, request: Request) -> Response:
        """Validate a token without consuming it, so the frontend can show the email."""
        token = request.query_params.get("token", "")
        user_id = cache.get(f"invite:{token}") if token else None
        if not user_id:
            return Response(
                {"detail": "Invitation link is invalid or has expired."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            user = User.objects.get(pk=user_id)
        except User.DoesNotExist:
            return Response(
                {"detail": "Invitation link is invalid or has expired."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response({"email": user.email, "full_name": user.full_name})

    def post(self, request: Request) -> Response:
        token = request.data.get("token", "")
        new_password = request.data.get("new_password", "")
        user_id = cache.get(f"invite:{token}") if token else None
        if not user_id:
            return Response(
                {"detail": "Invitation link is invalid or has expired."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if not is_password_valid(new_password):
            return Response(
                {"detail": PASSWORD_POLICY_DETAIL},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            user = User.objects.get(pk=user_id)
        except User.DoesNotExist:
            return Response(
                {"detail": "Invitation link is invalid or has expired."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        user.set_password(new_password)
        user.failed_login_count = 0
        user.status = User.Status.ACTIVE
        user.password_changed_at = timezone.now()
        user.save(update_fields=["password", "failed_login_count", "status", "password_changed_at"])
        cache.delete(f"invite:{token}")
        # Also clear the reverse-index pending_invite key.
        cache.delete(f"pending_invite:{user.user_id}")
        log_audit_event(
            user,
            self.audit_action,
            target_user=user,
            request=request,
        )
        return Response({"detail": "Account activated. You can now log in."}, status=status.HTTP_200_OK)


class MFASetupView(AuditLogMixin, APIView):
    # Open to every authenticated user — NGO Staff can self-enrol.
    permission_classes = [IsAuthenticated]

    def post(self, request: Request) -> Response:
        secret = pyotp.random_base32()
        provisioning_uri = pyotp.TOTP(secret).provisioning_uri(
            name=request.user.email,
            issuer_name="RefuConnect",
        )
        return Response({"secret": secret, "qr_code_url": provisioning_uri})


class MFAConfirmView(AuditLogMixin, APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request: Request) -> Response:
        pending_secret = request.data.get("pending_secret", "")
        totp_code = request.data.get("totp_code", "")
        if not pending_secret or not pyotp.TOTP(pending_secret).verify(str(totp_code)):
            return Response(
                {"detail": "Invalid MFA code."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        request.user.mfa_secret = encrypt_field(pending_secret)
        request.user.mfa_enabled_at = timezone.now()
        request.user.save(update_fields=["mfa_secret", "mfa_enabled_at"])

        backup_codes = generate_backup_codes(request.user)
        log_audit_event(
            request.user,
            AuditAction.MFA_ENABLED,
            target_user=request.user,
            request=request,
        )
        log_audit_event(
            request.user,
            AuditAction.MFA_BACKUP_CODES_GENERATED,
            new_value=str(len(backup_codes)),
            target_user=request.user,
            request=request,
        )
        return Response({"backup_codes": backup_codes}, status=status.HTTP_200_OK)
