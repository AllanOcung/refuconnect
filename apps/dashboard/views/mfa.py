"""
Self-service MFA management — disable, regenerate backup codes, view status.

Setup + initial confirm live in ``auth.py`` (used by both the initial enrol
flow on first login and the profile page).  These three live in the user's
own ``/me/mfa/*`` namespace and require a fresh password to perform any
destructive action.
"""
from __future__ import annotations

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.audit import AuditAction, log_audit_event
from apps.dashboard.services.backup_codes import (
    backup_code_stats,
    clear_backup_codes,
    generate_backup_codes,
)
from apps.dashboard.views.mixins import AuditLogMixin


def _require_password(request: Request) -> tuple[bool, Response | None]:
    """Helper: confirm the request includes a correct ``password`` for the user."""
    password = request.data.get("password", "")
    if not password or not request.user.check_password(password):
        return False, Response(
            {"detail": "Password confirmation is required and must match."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    return True, None


class MFADisableView(AuditLogMixin, APIView):
    """Turn off MFA for the calling user. Requires password confirmation."""

    permission_classes = [IsAuthenticated]

    def post(self, request: Request) -> Response:
        ok, denied = _require_password(request)
        if not ok:
            return denied

        user = request.user
        user.mfa_secret = None
        user.mfa_enabled_at = None
        user.save(update_fields=["mfa_secret", "mfa_enabled_at"])
        removed = clear_backup_codes(user)

        log_audit_event(
            user,
            AuditAction.MFA_DISABLED,
            new_value=f"removed_codes={removed}",
            target_user=user,
            request=request,
        )
        return Response(status=status.HTTP_204_NO_CONTENT)


class BackupCodesStatusView(AuditLogMixin, APIView):
    """Return counts only — never plaintext codes."""

    permission_classes = [IsAuthenticated]

    def get(self, request: Request) -> Response:
        return Response(backup_code_stats(request.user), status=status.HTTP_200_OK)


class BackupCodesRegenerateView(AuditLogMixin, APIView):
    """Replace the user's backup codes with a fresh batch. Returns plaintext once."""

    permission_classes = [IsAuthenticated]

    def post(self, request: Request) -> Response:
        ok, denied = _require_password(request)
        if not ok:
            return denied
        if not request.user.mfa_secret:
            return Response(
                {"detail": "Enable MFA before generating backup codes."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        codes = generate_backup_codes(request.user)
        log_audit_event(
            request.user,
            AuditAction.MFA_BACKUP_CODES_GENERATED,
            new_value=str(len(codes)),
            target_user=request.user,
            request=request,
        )
        return Response({"backup_codes": codes}, status=status.HTTP_200_OK)
