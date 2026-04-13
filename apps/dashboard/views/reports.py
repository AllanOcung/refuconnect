"""
PDF and Excel report export views.
"""
from __future__ import annotations

import logging
from datetime import date, timedelta

from django.http import HttpResponse
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework import status
from rest_framework.views import APIView

from apps.common.audit import AuditAction, log_audit_event
from apps.common.utils import format_utc_timestamp
from apps.dashboard.services.report_generator import generate_excel_report, generate_pdf_report
from apps.feedback.models import Feedback

logger = logging.getLogger(__name__)


def _parse_date_range(request: Request):
    """Return (date_from, date_to) tuple parsed from query params."""
    date_from_str = request.query_params.get("date_from")
    date_to_str = request.query_params.get("date_to")
    date_from = date.fromisoformat(date_from_str) if date_from_str else date.today() - timedelta(days=30)
    date_to = date.fromisoformat(date_to_str) if date_to_str else date.today()
    return date_from, date_to


def _build_queryset(date_from, date_to):
    return Feedback.objects.filter(
        submitted_at__date__gte=date_from,
        submitted_at__date__lte=date_to,
    ).select_related("sentiment", "reviewed_by").prefetch_related("categories")


class PDFReportView(APIView):
    """
    GET /api/v1/dashboard/reports/pdf/
    Returns a PDF report for the given date range.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request: Request) -> HttpResponse:
        try:
            date_from, date_to = _parse_date_range(request)
        except ValueError:
            return Response(
                {"detail": "Invalid date format. Use YYYY-MM-DD."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        queryset = _build_queryset(date_from, date_to)
        title = f"RefuConnect Feedback Report ({date_from} to {date_to})"
        pdf_bytes = generate_pdf_report(queryset, title)

        log_audit_event(request.user, AuditAction.REPORT_EXPORTED, request=request)

        response = HttpResponse(pdf_bytes, content_type="application/pdf")
        filename = f"refuconnect_report_{date_from}_{date_to}.pdf"
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        return response


class ExcelReportView(APIView):
    """
    GET /api/v1/dashboard/reports/excel/
    Returns an Excel (.xlsx) report for the given date range.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request: Request) -> HttpResponse:
        try:
            date_from, date_to = _parse_date_range(request)
        except ValueError:
            return Response(
                {"detail": "Invalid date format. Use YYYY-MM-DD."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        queryset = _build_queryset(date_from, date_to)
        excel_bytes = generate_excel_report(queryset)

        log_audit_event(request.user, AuditAction.REPORT_EXPORTED, request=request)

        response = HttpResponse(
            excel_bytes,
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        filename = f"refuconnect_report_{date_from}_{date_to}.xlsx"
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        return response
