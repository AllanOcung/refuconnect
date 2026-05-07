from __future__ import annotations

from django.core.cache import cache
from django.db.models import Count
from django.utils import timezone
from rest_framework import generics, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.audit import AuditAction, log_audit_event
from apps.dashboard.pagination import AlertPagination
from apps.dashboard.permissions import IsNGOStaff
from apps.dashboard.serializers import AlertSerializer
from apps.dashboard.services.analytics_engine import AnalyticsEngine
from apps.feedback.models import Alert


class AlertListView(generics.ListAPIView):
    permission_classes = [IsAuthenticated, IsNGOStaff]
    serializer_class = AlertSerializer
    pagination_class = AlertPagination

    def get_queryset(self):
        qs = Alert.objects.select_related("feedback", "acknowledged_by").prefetch_related(
            "feedback__feedback_categories__category"
        )
        status_value = self.request.query_params.get("status")
        if status_value:
            qs = qs.filter(status=status_value)
        return qs.order_by("-created_at")

    def paginate_queryset(self, queryset):
        page = super().paginate_queryset(queryset)
        if self.paginator is not None:
            self.paginator.open_count = Alert.objects.filter(
                status=Alert.AlertStatus.OPEN
            ).count()
        return page


class AlertAcknowledgeView(APIView):
    permission_classes = [IsAuthenticated, IsNGOStaff]

    def post(self, request: Request, alert_id: int) -> Response:
        try:
            alert = (
                Alert.objects.select_related("feedback")
                .prefetch_related("feedback__feedback_categories__category")
                .get(pk=alert_id)
            )
        except Alert.DoesNotExist:
            return Response({"detail": "Alert not found."}, status=status.HTTP_404_NOT_FOUND)

        alert.status = Alert.AlertStatus.ACKNOWLEDGED
        alert.acknowledged_by = request.user
        alert.acknowledged_at = timezone.now()
        alert.save(update_fields=["status", "acknowledged_by", "acknowledged_at"])
        log_audit_event(
            request.user,
            AuditAction.ALERT_ACKNOWLEDGED,
            feedback=alert.feedback,
            request=request,
        )
        AnalyticsEngine().invalidate_cache(getattr(request.user, "organisation", "") or 1)
        cache.delete("dashboard:alert_stats")
        return Response(AlertSerializer(alert).data, status=status.HTTP_200_OK)


class AlertResolveView(APIView):
    permission_classes = [IsAuthenticated, IsNGOStaff]

    def post(self, request: Request, alert_id: int) -> Response:
        try:
            alert = (
                Alert.objects.select_related("feedback")
                .prefetch_related("feedback__feedback_categories__category")
                .get(pk=alert_id)
            )
        except Alert.DoesNotExist:
            return Response({"detail": "Alert not found."}, status=status.HTTP_404_NOT_FOUND)

        alert.status = Alert.AlertStatus.RESOLVED
        alert.save(update_fields=["status"])
        log_audit_event(
            request.user,
            AuditAction.ALERT_RESOLVED,
            feedback=alert.feedback,
            request=request,
        )
        AnalyticsEngine().invalidate_cache(getattr(request.user, "organisation", "") or 1)
        cache.delete("dashboard:alert_stats")
        return Response(AlertSerializer(alert).data, status=status.HTTP_200_OK)


class AlertStatsView(APIView):
    permission_classes = [IsAuthenticated, IsNGOStaff]

    def get(self, request: Request) -> Response:
        cached = cache.get("dashboard:alert_stats")
        if cached:
            return Response(cached)
        counts = {status_value: 0 for status_value, _label in Alert.AlertStatus.choices}
        for row in Alert.objects.values("status").annotate(count=Count("alert_id")):
            counts[row["status"]] = row["count"]
        cache.set("dashboard:alert_stats", counts, timeout=30)
        return Response(counts)
