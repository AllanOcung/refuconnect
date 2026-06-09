"""
Self-service endpoints — any authenticated user can read/update their own
profile, change their own password, or revoke all their refresh tokens.

These intentionally never expose another user's data and don't require the
Administrator role.
"""
from __future__ import annotations

from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.token_blacklist.models import OutstandingToken

from apps.common.audit import AuditAction, log_audit_event
from apps.dashboard.serializers import ChangePasswordSerializer, UserSerializer
from apps.dashboard.views.mixins import AuditLogMixin


PROFILE_EDITABLE_FIELDS = {
    "full_name",
    "job_title",
    "avatar_url",
    "preferred_language",
    "alert_phone",
    "receive_alerts",
}


class MeView(AuditLogMixin, APIView):
    """``GET`` and ``PATCH`` the authenticated user's own profile."""

    permission_classes = [IsAuthenticated]

    def get(self, request: Request) -> Response:
        return Response(UserSerializer(request.user).data, status=status.HTTP_200_OK)

    def patch(self, request: Request) -> Response:
        user = request.user
        changes = {
            field: request.data[field]
            for field in PROFILE_EDITABLE_FIELDS
            if field in request.data
        }
        updated_fields: list[str] = []
        for field, new_value in changes.items():
            old_value = getattr(user, field)
            if old_value != new_value:
                setattr(user, field, new_value)
                updated_fields.append(field)
                log_audit_event(
                    user,
                    AuditAction.PROFILE_UPDATED,
                    field_changed=field,
                    old_value=str(old_value) if old_value is not None else None,
                    new_value=str(new_value) if new_value is not None else None,
                    target_user=user,
                    request=request,
                )
        if updated_fields:
            user.save(update_fields=updated_fields)
        return Response(UserSerializer(user).data, status=status.HTTP_200_OK)


class ChangePasswordView(AuditLogMixin, APIView):
    """Authenticated password change. Requires current password."""

    permission_classes = [IsAuthenticated]

    def post(self, request: Request) -> Response:
        serializer = ChangePasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        current_password = serializer.validated_data["current_password"]
        new_password = serializer.validated_data["new_password"]

        user = request.user
        if not user.check_password(current_password):
            return Response(
                {"detail": "Current password is incorrect."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if current_password == new_password:
            return Response(
                {"detail": "New password must differ from the current password."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        user.set_password(new_password)
        user.password_changed_at = timezone.now()
        user.save(update_fields=["password", "password_changed_at"])

        log_audit_event(
            user,
            AuditAction.PASSWORD_CHANGED,
            target_user=user,
            request=request,
        )
        return Response({"detail": "Password updated."}, status=status.HTTP_200_OK)


class LogoutAllSessionsView(AuditLogMixin, APIView):
    """Blacklist every outstanding refresh token for the calling user."""

    permission_classes = [IsAuthenticated]

    def post(self, request: Request) -> Response:
        tokens = OutstandingToken.objects.filter(user_id=request.user.pk)
        revoked = 0
        for outstanding in tokens.iterator():
            try:
                outstanding.blacklistedtoken
            except Exception:
                # No BlacklistedToken row yet — create one.
                try:
                    from rest_framework_simplejwt.token_blacklist.models import (
                        BlacklistedToken,
                    )

                    BlacklistedToken.objects.create(token=outstanding)
                    revoked += 1
                except Exception:
                    # Already blacklisted in a race — ignore.
                    pass

        log_audit_event(
            request.user,
            AuditAction.SESSIONS_REVOKED,
            new_value=str(revoked),
            target_user=request.user,
            request=request,
        )
        return Response({"revoked_count": revoked}, status=status.HTTP_200_OK)
