from __future__ import annotations

from django.db import transaction
from django.db.models import Exists, OuterRef
from django.utils import timezone
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import generics, status
from rest_framework.filters import OrderingFilter
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from apps.common.audit import AuditAction, log_audit_event
from apps.dashboard.filters import AuditLogFilterSet, FeedbackFilterSet
from apps.dashboard.models import AuditLog
from apps.dashboard.pagination import AuditLogPagination, FeedbackPagination
from apps.dashboard.permissions import IsAdministrator, IsNGOStaff
from apps.dashboard.serializers import (
    AuditLogSerializer,
    FeedbackDetailSerializer,
    FeedbackListSerializer,
    FeedbackUpdateSerializer,
)
from apps.dashboard.services.analytics_engine import AnalyticsEngine
from apps.dashboard.views.mixins import AuditLogMixin
from apps.feedback.models import Feedback, FeedbackCategory, FeedbackMedia


class FeedbackListView(AuditLogMixin, generics.ListAPIView):
    permission_classes = [IsAuthenticated, IsNGOStaff]
    serializer_class = FeedbackListSerializer
    pagination_class = FeedbackPagination
    filter_backends = [DjangoFilterBackend, OrderingFilter]
    filterset_class = FeedbackFilterSet
    ordering_fields = ["submitted_at", "urgency_level", "sentiment"]
    ordering = ["-submitted_at"]

    def get_queryset(self):
        media_qs = FeedbackMedia.objects.filter(feedback=OuterRef("pk"))
        return (
            Feedback.objects.select_related("sentiment")
            .prefetch_related("feedback_categories__category")
            .annotate(has_media=Exists(media_qs))
            .order_by("-submitted_at")
        )


class FeedbackDetailView(AuditLogMixin, generics.GenericAPIView):
    permission_classes = [IsAuthenticated, IsNGOStaff]
    serializer_class = FeedbackDetailSerializer
    lookup_field = "feedback_id"
    lookup_url_kwarg = "feedback_id"

    def get_queryset(self):
        media_qs = FeedbackMedia.objects.filter(feedback=OuterRef("pk"))
        return (
            Feedback.objects.select_related("sentiment", "reviewed_by", "alert")
            .prefetch_related(
                "feedback_categories__category",
                "media_files",
                "notifications",
                "audit_logs__user",
            )
            .annotate(has_media=Exists(media_qs))
        )

    def get(self, request: Request, *args, **kwargs) -> Response:
        feedback = self.get_object()
        feedback.reviewed_by = request.user
        feedback.reviewed_at = timezone.now()
        feedback.save(update_fields=["reviewed_by", "reviewed_at"])
        log_audit_event(
            request.user,
            AuditAction.FEEDBACK_VIEWED,
            feedback=feedback,
            request=request,
        )
        return Response(self.get_serializer(feedback).data)

    @transaction.atomic
    def patch(self, request: Request, *args, **kwargs) -> Response:
        feedback = self.get_object()
        serializer = FeedbackUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        changes = serializer.validated_data

        for field in ("urgency_level", "is_flagged", "flag_reason"):
            if field not in changes:
                continue
            old_value = getattr(feedback, field)
            new_value = changes[field]
            if old_value != new_value:
                setattr(feedback, field, new_value)
                log_audit_event(
                    request.user,
                    AuditAction.FEEDBACK_EDITED,
                    feedback=feedback,
                    field_changed=field,
                    old_value=str(old_value),
                    new_value=str(new_value),
                    request=request,
                )

        feedback.reviewed_by = request.user
        feedback.reviewed_at = timezone.now()
        feedback.save(
            update_fields=[
                "urgency_level",
                "is_flagged",
                "flag_reason",
                "reviewed_by",
                "reviewed_at",
            ]
        )

        if "categories" in changes:
            old_categories = list(
                feedback.feedback_categories.select_related("category").values_list(
                    "category__category_name", flat=True
                )
            )
            FeedbackCategory.objects.filter(
                feedback=feedback, is_ai_assigned=True
            ).delete()
            for category in changes["categories"]:
                FeedbackCategory.objects.update_or_create(
                    feedback=feedback,
                    category=category,
                    defaults={
                        "confidence_score": 1.0,
                        "is_ai_assigned": False,
                    },
                )
            new_categories = [category.category_name for category in changes["categories"]]
            log_audit_event(
                request.user,
                AuditAction.FEEDBACK_EDITED,
                feedback=feedback,
                field_changed="categories",
                old_value=", ".join(old_categories),
                new_value=", ".join(new_categories),
                request=request,
            )

        AnalyticsEngine().invalidate_cache(getattr(request.user, "organisation", "") or 1)
        feedback = self.get_queryset().get(pk=feedback.pk)
        return Response(self.get_serializer(feedback).data, status=status.HTTP_200_OK)


class AuditLogView(AuditLogMixin, generics.ListAPIView):
    permission_classes = [IsAuthenticated, IsAdministrator]
    serializer_class = AuditLogSerializer
    pagination_class = AuditLogPagination
    filter_backends = [DjangoFilterBackend]
    filterset_class = AuditLogFilterSet
    http_method_names = ["get", "head", "options"]

    def get_queryset(self):
        return AuditLog.objects.select_related("user", "feedback").order_by("-created_at")
