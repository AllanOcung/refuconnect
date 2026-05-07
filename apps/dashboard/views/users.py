from __future__ import annotations

import secrets

from django.core.mail import send_mail
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
from apps.dashboard.views.mixins import AuditLogMixin


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
        temporary_password = secrets.token_urlsafe(12) + "1!"
        user = User.objects.create_user(
            password=temporary_password,
            status=User.Status.PENDING_VERIFICATION,
            **serializer.validated_data,
        )
        send_mail(
            "Your RefuConnect invitation",
            f"You have been invited to RefuConnect. Temporary password: {temporary_password}",
            None,
            [user.email],
            fail_silently=True,
        )
        log_audit_event(request.user, AuditAction.USER_CREATED, request=request)
        return Response(UserSerializer(user).data, status=status.HTTP_201_CREATED)


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
        user = self.get_object()
        if user.pk == request.user.pk:
            return Response(
                {"detail": "You cannot delete your own account."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if (
            user.role == User.Role.ADMINISTRATOR
            and User.objects.filter(
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
        old_status = user.status
        user.status = User.Status.SUSPENDED
        user.save(update_fields=["status"])
        log_audit_event(
            request.user,
            AuditAction.USER_DELETED,
            field_changed="status",
            old_value=old_status,
            new_value=str(user.status),
            request=request,
        )
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
