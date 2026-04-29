"""
Feedback app views.

Webhook endpoints (public) live in the channel adapters:
  apps.feedback.adapters.sms     → SMSWebhookView
  apps.feedback.adapters.ussd    → USSDSessionView
  apps.feedback.adapters.whatsapp → WhatsAppWebhookView

This module contains only the authenticated dashboard API views:
  GET  /api/v1/feedback/          — List feedback (authenticated)
  GET  /api/v1/feedback/<id>/     — Retrieve single feedback (authenticated)
  PATCH /api/v1/feedback/<id>/flag/ — Flag a feedback record
"""
from __future__ import annotations

import logging

from django.utils import timezone
from rest_framework import generics, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.audit import AuditAction, log_audit_event

from .models import Feedback
from .serializers import (
    FeedbackDetailSerializer,
    FeedbackListSerializer,
    LanguageReviewSerializer,
)

logger = logging.getLogger("refuconnect.feedback.views")


# ── Dashboard views (authenticated) ──────────────────────────────────────────


class FeedbackListView(generics.ListAPIView):
    """Paginated list of all feedback records for authenticated NGO staff."""

    permission_classes = [IsAuthenticated]
    serializer_class = FeedbackListSerializer
    filterset_fields = ["channel", "status", "urgency_level", "language", "is_flagged"]
    search_fields = ["message_text", "location", "anonymous_user_id"]
    ordering_fields = ["submitted_at", "urgency_level", "status"]
    ordering = ["-submitted_at"]

    def get_queryset(self):
        return (
            Feedback.objects.select_related("sentiment")
            .only(
                "feedback_id", "channel", "language", "urgency_level",
                "status", "is_flagged", "is_duplicate", "location",
                "submitted_at", "sentiment__sentiment_label",
            )
            .order_by("-submitted_at")
        )


class FeedbackDetailView(generics.RetrieveUpdateAPIView):
    """Full feedback record for review and manual edits."""

    permission_classes = [IsAuthenticated]
    serializer_class = FeedbackDetailSerializer
    queryset = Feedback.objects.select_related("sentiment", "reviewed_by").prefetch_related(
        "feedback_categories__category", "media_files"
    )

    def get_object(self):
        obj = super().get_object()
        log_audit_event(
            user=self.request.user,
            action=AuditAction.FEEDBACK_VIEWED,
            feedback=obj,
            request=self.request,
        )
        return obj

    def perform_update(self, serializer):
        old_status = serializer.instance.status
        updated = serializer.save(
            reviewed_by=self.request.user,
            reviewed_at=timezone.now(),
        )
        if old_status != updated.status:
            log_audit_event(
                user=self.request.user,
                action=AuditAction.FEEDBACK_EDITED,
                feedback=updated,
                field_changed="status",
                old_value=old_status,
                new_value=updated.status,
                request=self.request,
            )


class FeedbackFlagView(APIView):
    """Flag or un-flag a feedback record."""

    permission_classes = [IsAuthenticated]

    def patch(self, request: Request, pk: int) -> Response:
        try:
            feedback = Feedback.objects.get(pk=pk)
        except Feedback.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)

        is_flagged = request.data.get("is_flagged", True)
        flag_reason = request.data.get("flag_reason", "")

        feedback.is_flagged = bool(is_flagged)
        feedback.flag_reason = flag_reason[:60] if flag_reason else None
        feedback.save(update_fields=["is_flagged", "flag_reason"])

        log_audit_event(
            user=request.user,
            action=AuditAction.FEEDBACK_EDITED,
            feedback=feedback,
            field_changed="is_flagged",
            old_value=str(not is_flagged),
            new_value=str(is_flagged),
            request=request,
        )

        return Response(
            {"feedback_id": pk, "is_flagged": feedback.is_flagged},
            status=status.HTTP_200_OK,
        )


class LanguageDetectionReviewView(generics.ListAPIView):
    """
    List feedback records that need language detection review.
    
    Includes:
      - Feedbacks with language = 'unknown'
      - Feedbacks with language_confidence < 0.85
    
    This helps operators identify messages where automatic language detection
    was uncertain and may need manual verification or re-classification.
    """

    permission_classes = [IsAuthenticated]
    serializer_class = LanguageReviewSerializer
    search_fields = ["message_text", "location", "anonymous_user_id"]
    ordering_fields = ["submitted_at", "language_confidence"]
    ordering = ["language_confidence", "-submitted_at"]

    def get_queryset(self):
        from django.conf import settings
        from django.db.models import Q
        
        threshold = getattr(settings, "LANGUAGE_CONFIDENCE_THRESHOLD_TRANSLATION", 0.85)
        return (
            Feedback.objects.select_related("sentiment")
            .filter(
                Q(language="unknown") | 
                Q(language_confidence__lt=threshold)
            )
            .only(
                "feedback_id", "channel", "language", "language_confidence",
                "urgency_level", "status", "is_flagged", "location",
                "submitted_at", "message_text", "sentiment__sentiment_label",
            )
            .order_by("language_confidence", "-submitted_at")
        )
