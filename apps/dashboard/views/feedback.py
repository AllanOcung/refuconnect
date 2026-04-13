"""
Dashboard-specific feedback views (bulk operations).
"""
from __future__ import annotations

import logging

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.audit import AuditAction, log_audit_event
from apps.feedback.models import Feedback

logger = logging.getLogger(__name__)

_ALLOWED_STATUSES = {choice[0] for choice in Feedback.Status.choices}


class BulkFeedbackStatusView(APIView):
    """
    PATCH /api/v1/dashboard/feedback/bulk-status/
    Body: {"ids": [1, 2, 3], "status": "Reviewed"}
    """

    permission_classes = [IsAuthenticated]

    def patch(self, request: Request) -> Response:
        ids = request.data.get("ids", [])
        new_status = request.data.get("status")

        if not ids or not isinstance(ids, list):
            return Response(
                {"detail": "ids must be a non-empty list."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if new_status not in _ALLOWED_STATUSES:
            return Response(
                {"detail": f"Invalid status. Allowed: {sorted(_ALLOWED_STATUSES)}"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        updated = Feedback.objects.filter(pk__in=ids).update(status=new_status)
        log_audit_event(
            request.user,
            AuditAction.FEEDBACK_EDITED,
            field_changed="status",
            new_value=new_status,
            request=request,
        )
        return Response({"updated": updated}, status=status.HTTP_200_OK)


class BulkFeedbackFlagView(APIView):
    """
    PATCH /api/v1/dashboard/feedback/bulk-flag/
    Body: {"ids": [1, 2, 3], "is_flagged": true, "flag_reason": "Sensitive content"}
    """

    permission_classes = [IsAuthenticated]

    def patch(self, request: Request) -> Response:
        ids = request.data.get("ids", [])
        is_flagged = request.data.get("is_flagged")
        flag_reason = request.data.get("flag_reason", "")

        if not ids or not isinstance(ids, list):
            return Response(
                {"detail": "ids must be a non-empty list."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if is_flagged is None:
            return Response(
                {"detail": "is_flagged (boolean) is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        update_fields = {"is_flagged": bool(is_flagged)}
        if is_flagged:
            update_fields["flag_reason"] = flag_reason

        updated = Feedback.objects.filter(pk__in=ids).update(**update_fields)
        log_audit_event(
            request.user,
            AuditAction.FEEDBACK_EDITED,
            field_changed="is_flagged",
            new_value=str(is_flagged),
            request=request,
        )
        return Response({"updated": updated}, status=status.HTTP_200_OK)
