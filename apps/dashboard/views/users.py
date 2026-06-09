from __future__ import annotations

import secrets

from django.conf import settings
from django.core.cache import cache
from django.db.models import Q
from rest_framework import generics, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.audit import AuditAction, log_audit_event
from apps.dashboard.models import User
from apps.dashboard.pagination import StandardResultsPagination
from apps.dashboard.permissions import IsAdministrator
from apps.dashboard.serializers import UserInviteSerializer, UserSerializer
from apps.dashboard.services.emails import send_invitation_email
from apps.dashboard.views.mixins import AuditLogMixin

INVITE_TOKEN_TTL_SECONDS = 7 * 24 * 60 * 60  # 7 days


class UserListView(AuditLogMixin, generics.ListAPIView):
    permission_classes = [IsAuthenticated, IsAdministrator]
    serializer_class = UserSerializer
    pagination_class = StandardResultsPagination

    def get_queryset(self):
        qs = User.objects.order_by("-created_at")
        role = self.request.query_params.get("role")
        status_value = self.request.query_params.get("status")
        search = self.request.query_params.get("search")
        if role:
            qs = qs.filter(role=role)
        if status_value:
            qs = qs.filter(status=status_value)
        if search:
            qs = qs.filter(Q(full_name__icontains=search) | Q(email__icontains=search))
        return qs


class UserInviteView(AuditLogMixin, APIView):
    permission_classes = [IsAuthenticated, IsAdministrator]

    def post(self, request: Request) -> Response:
        serializer = UserInviteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        # Create the user with an unguessable random password they will never use.
        # The accept-invite flow will replace it once they choose their own.
        user = User.objects.create_user(
            password=secrets.token_urlsafe(32),
            status=User.Status.PENDING_VERIFICATION,
            invited_by=request.user if request.user.is_authenticated else None,
            **serializer.validated_data,
        )

        token = secrets.token_urlsafe(32)
        cache.set(f"invite:{token}", user.user_id, timeout=INVITE_TOKEN_TTL_SECONDS)
        # Reverse index so resend/revoke can find the active token by user id.
        cache.set(f"pending_invite:{user.user_id}", token, timeout=INVITE_TOKEN_TTL_SECONDS)

        invite_url = f"{settings.DASHBOARD_URL.rstrip('/')}/accept-invite?token={token}"

        send_invitation_email(user=user, inviter=request.user, token=token)

        log_audit_event(
            request.user,
            AuditAction.USER_CREATED,
            target_user=user,
            request=request,
        )
        data = UserSerializer(user).data
        data["invite_url"] = invite_url
        return Response(data, status=status.HTTP_201_CREATED)


class UserDetailView(AuditLogMixin, generics.RetrieveUpdateDestroyAPIView):
    permission_classes = [IsAuthenticated, IsAdministrator]
    serializer_class = UserSerializer
    queryset = User.objects.all()
    lookup_field = "user_id"
    lookup_url_kwarg = "user_id"
    http_method_names = ["get", "patch", "delete", "head", "options"]

    editable_fields = {"full_name", "role", "status", "receive_alerts", "alert_phone"}

    def patch(self, request: Request, *args, **kwargs) -> Response:
        user = self.get_object()
        changes = {
            field: request.data[field]
            for field in self.editable_fields
            if field in request.data
        }
        for field, new_value in changes.items():
            old_value = getattr(user, field)
            if old_value != new_value:
                setattr(user, field, new_value)
                log_audit_event(
                    request.user,
                    AuditAction.USER_MODIFIED,
                    field_changed=field,
                    old_value=str(old_value),
                    new_value=str(new_value),
                    request=request,
                )
        if changes:
            user.save(update_fields=list(changes.keys()))
        return Response(UserSerializer(user).data, status=status.HTTP_200_OK)

    def delete(self, request: Request, *args, **kwargs) -> Response:
        """
        Permanently remove a user.

        The user must already be Suspended (a two-step suspend-then-delete
        workflow) to avoid accidentally destroying an active account. All
        related rows that point at this user are SET NULL by their FK
        on_delete rules, preserving audit history.
        """
        user = self.get_object()
        if user.pk == request.user.pk:
            return Response(
                {"detail": "You cannot delete your own account."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if user.status != User.Status.SUSPENDED:
            return Response(
                {
                    "detail": (
                        "Suspend the user first, then permanently remove from "
                        "the Suspended state."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        if user.role == User.Role.ADMINISTRATOR and (
            User.objects.filter(
                role=User.Role.ADMINISTRATOR,
                status=User.Status.ACTIVE,
            )
            .exclude(pk=user.pk)
            .count()
            == 0
        ):
            return Response(
                {"detail": "You cannot delete the last active Administrator."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        # Capture identifying details *before* the row vanishes — the
        # AuditLog.target_user FK is SET_NULL on cascade, so we keep the
        # email in old_value for forensic traceability.
        deleted_email = user.email
        deleted_full_name = user.full_name
        log_audit_event(
            request.user,
            AuditAction.USER_DELETED,
            field_changed="email",
            old_value=deleted_email,
            new_value=f"deleted ({deleted_full_name})",
            target_user=user,
            request=request,
        )
        user.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class UserUnlockView(AuditLogMixin, APIView):
    permission_classes = [IsAuthenticated, IsAdministrator]

    def post(self, request: Request, user_id: int) -> Response:
        try:
            user = User.objects.get(user_id=user_id)
        except User.DoesNotExist:
            return Response({"detail": "User not found."}, status=status.HTTP_404_NOT_FOUND)
        old_status = user.status
        user.failed_login_count = 0
        user.status = User.Status.ACTIVE
        user.save(update_fields=["failed_login_count", "status"])
        log_audit_event(
            request.user,
            AuditAction.USER_MODIFIED,
            field_changed="status",
            old_value=old_status,
            new_value=str(user.status),
            request=request,
        )
        return Response({"detail": "User unlocked.", "status": user.status})
