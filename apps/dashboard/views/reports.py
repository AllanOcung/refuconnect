from __future__ import annotations

from django.http import HttpResponse
from django.utils import timezone
from rest_framework import generics, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.audit import AuditAction, log_audit_event
from apps.dashboard.models import ReportExport
from apps.dashboard.pagination import StandardResultsPagination
from apps.dashboard.permissions import IsNGOStaff
from apps.dashboard.serializers import ReportExportSerializer, ReportGenerateSerializer
from apps.dashboard.services.report_generator import ReportGenerator
from apps.dashboard.tasks import generate_report_export_task


class ReportGenerateView(APIView):
    permission_classes = [IsAuthenticated, IsNGOStaff]

    def post(self, request: Request) -> HttpResponse | Response:
        serializer = ReportGenerateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        format_value = serializer.validated_data["format"]
        template_id = serializer.validated_data["template_id"]
        filters = serializer.validated_data.get("filters", {})

        generator = ReportGenerator()
        row_count = generator.row_count(filters)
        if row_count > 1000:
            export = ReportExport.objects.create(
                user=request.user,
                template_id=template_id,
                format=format_value,
                filters_snapshot=filters,
                row_count=row_count,
                status=ReportExport.Status.QUEUED,
            )
            task = generate_report_export_task.delay(export.export_id)
            ReportExport.objects.filter(pk=export.pk).update(task_id=task.id)
            return Response(
                {
                    "detail": "Report queued for background generation.",
                    "task_id": task.id,
                    "export_id": export.export_id,
                    "status": ReportExport.Status.QUEUED,
                },
                status=status.HTTP_202_ACCEPTED,
            )

        file_bytes, filename = generator.generate(
            format_value, filters, template_id, request.user
        )
        export = ReportExport.objects.create(
            user=request.user,
            template_id=template_id,
            format=format_value,
            filters_snapshot=filters,
            row_count=row_count,
            file_size_bytes=len(file_bytes),
            status=ReportExport.Status.COMPLETED,
            file_name=filename,
            content_type=generator.content_type(format_value),
            file_data=file_bytes,
            completed_at=timezone.now(),
        )
        log_audit_event(
            request.user,
            AuditAction.REPORT_EXPORTED,
            field_changed="report",
            old_value=None,
            new_value=f"{format_value}:{template_id}:{row_count}",
            request=request,
        )

        response = HttpResponse(file_bytes, content_type=generator.content_type(format_value))
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        response["X-Report-Export-ID"] = str(export.export_id)
        return response


class ReportHistoryView(generics.ListAPIView):
    permission_classes = [IsAuthenticated, IsNGOStaff]
    serializer_class = ReportExportSerializer
    pagination_class = StandardResultsPagination

    def get_queryset(self):
        return ReportExport.objects.filter(user=self.request.user).order_by("-generated_at")


class ReportTaskStatusView(generics.RetrieveAPIView):
    permission_classes = [IsAuthenticated, IsNGOStaff]
    serializer_class = ReportExportSerializer
    lookup_field = "task_id"
    lookup_url_kwarg = "task_id"

    def get_queryset(self):
        return ReportExport.objects.filter(user=self.request.user)


class ReportTaskDownloadView(APIView):
    permission_classes = [IsAuthenticated, IsNGOStaff]

    def get(self, request: Request, task_id: str) -> HttpResponse | Response:
        try:
            export = ReportExport.objects.get(user=request.user, task_id=task_id)
        except ReportExport.DoesNotExist:
            return Response(
                {"detail": "Report task not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        if export.status != ReportExport.Status.COMPLETED:
            return Response(
                {"detail": "Report is not ready.", "status": export.status},
                status=status.HTTP_409_CONFLICT,
            )
        if not export.file_data:
            return Response(
                {"detail": "Report file is no longer available."},
                status=status.HTTP_404_NOT_FOUND,
            )

        filename = export.file_name or f"refuconnect_report_{export.export_id}.{export.format}"
        content_type = export.content_type or ReportGenerator.content_type(export.format)
        response = HttpResponse(bytes(export.file_data), content_type=content_type)
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        return response
