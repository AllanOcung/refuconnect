"""
User management views — admin-only CRUD and status transitions.
"""
from __future__ import annotations

import logging

from rest_framework import status
from rest_framework.generics import ListAPIView, RetrieveUpdateAPIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.audit import AuditAction, log_audit_event
from apps.dashboard.models import User
from apps.dashboard.permissions import IsAdministrator
from apps.dashboard.serializers import UserCreateSerializer, UserSerializer

logger = logging.getLogger(__name__)


class UserListCreateView(APIView):
    """
    GET  /api/v1/dashboard/users/       — list all users (admin only)
    POST /api/v1/dashboard/users/       — invite/create a new user (admin only)
    """

    permission_classes = [IsAuthenticated, IsAdministrator]

    def get(self, request: Request) -> Response:
        users = User.objects.order_by("-created_at")
        serializer = UserSerializer(users, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def post(self, request: Request) -> Response:
        serializer = UserCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        log_audit_event(request.user, AuditAction.USER_CREATED, request=request)
        return Response(UserSerializer(user).data, status=status.HTTP_201_CREATED)


class UserDetailView(RetrieveUpdateAPIView):
    """
    GET   /api/v1/dashboard/users/<pk>/  — retrieve user detail
    PATCH /api/v1/dashboard/users/<pk>/  — update user (admin only)
    """

    queryset = User.objects.all()
    serializer_class = UserSerializer
    permission_classes = [IsAuthenticated, IsAdministrator]
    http_method_names = ["get", "patch", "head", "options"]

    def perform_update(self, serializer):
        serializer.save()
        log_audit_event(self.request.user, AuditAction.USER_UPDATED, request=self.request)


class UserStatusView(APIView):
    """
    PATCH /api/v1/dashboard/users/<pk>/status/
    Body: {"status": "Active" | "Suspended" | "Locked"}
    """

    permission_classes = [IsAuthenticated, IsAdministrator]

    _ALLOWED_TRANSITIONS = {
        User.Status.ACTIVE,
        User.Status.SUSPENDED,
        User.Status.LOCKED,
    }

    def patch(self, request: Request, pk: int) -> Response:
        try:
            user = User.objects.get(pk=pk)
        except User.DoesNotExist:
            return Response({"detail": "User not found."}, status=status.HTTP_404_NOT_FOUND)

        new_status = request.data.get("status")
        if new_status not in self._ALLOWED_TRANSITIONS:
            return Response(
                {"detail": f"Invalid status. Allowed: {sorted(self._ALLOWED_TRANSITIONS)}"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        old_status = user.status
        user.status = new_status
        if new_status == User.Status.ACTIVE:
            user.failed_login_count = 0
        user.save(update_fields=["status", "failed_login_count"])

        action_map = {
            User.Status.ACTIVE: AuditAction.USER_ACTIVATED,
            User.Status.SUSPENDED: AuditAction.USER_SUSPENDED,
            User.Status.LOCKED: AuditAction.ACCOUNT_LOCKED,
        }
        log_audit_event(
            request.user,
            action_map[new_status],
            field_changed="status",
            old_value=old_status,
            new_value=new_status,
            request=request,
        )

        return Response(
            {"detail": f"User status updated to {new_status}.", "status": new_status},
            status=status.HTTP_200_OK,
        )
