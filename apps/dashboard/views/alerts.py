"""
Alert list and acknowledge views.
"""
from __future__ import annotations

import logging

from rest_framework import status
from rest_framework.generics import ListAPIView, RetrieveAPIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.audit import AuditAction, log_audit_event
from apps.dashboard.serializers import AlertSerializer
from apps.feedback.models import Alert

logger = logging.getLogger(__name__)


class AlertListView(ListAPIView):
    """
    GET /api/v1/dashboard/alerts/
    Query params: status (Open/Acknowledged), priority (Critical/High/Medium)
    """

    serializer_class = AlertSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        qs = Alert.objects.select_related("feedback", "acknowledged_by").order_by(
            "-feedback__submitted_at"
        )
        alert_status = self.request.query_params.get("status")
        priority = self.request.query_params.get("priority")
        if alert_status:
            qs = qs.filter(alert_status=alert_status)
        if priority:
            qs = qs.filter(priority=priority)
        return qs


class AlertDetailView(RetrieveAPIView):
    """
    GET /api/v1/dashboard/alerts/<pk>/
    """

    serializer_class = AlertSerializer
    permission_classes = [IsAuthenticated]
    queryset = Alert.objects.select_related("feedback", "acknowledged_by")


class AlertAcknowledgeView(APIView):
    """
    PATCH /api/v1/dashboard/alerts/<pk>/acknowledge/
    """

    permission_classes = [IsAuthenticated]

    def patch(self, request: Request, pk: int) -> Response:
        try:
            alert = Alert.objects.select_related("feedback").get(pk=pk)
        except Alert.DoesNotExist:
            return Response({"detail": "Alert not found."}, status=status.HTTP_404_NOT_FOUND)

        if alert.alert_status == Alert.AlertStatus.ACKNOWLEDGED:
            return Response(
                {"detail": "Alert is already acknowledged."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        alert.alert_status = Alert.AlertStatus.ACKNOWLEDGED
        alert.acknowledged_by = request.user
        alert.save(update_fields=["alert_status", "acknowledged_by"])

        log_audit_event(
            request.user,
            AuditAction.ALERT_ACKNOWLEDGED,
            feedback=alert.feedback,
            request=request,
        )

        serializer = AlertSerializer(alert)
        return Response(serializer.data, status=status.HTTP_200_OK)
