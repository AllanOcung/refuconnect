from __future__ import annotations

from rest_framework import serializers

from apps.dashboard.models import ReportExport


class ReportGenerateSerializer(serializers.Serializer):
    format = serializers.ChoiceField(choices=["pdf", "xlsx"])
    template_id = serializers.ChoiceField(
        choices=["executive_summary", "detailed_analysis"]
    )
    filters = serializers.DictField(required=False, default=dict)


class ReportExportSerializer(serializers.ModelSerializer):
    class Meta:
        model = ReportExport
        fields = [
            "export_id",
            "template_id",
            "format",
            "filters_snapshot",
            "row_count",
            "file_size_bytes",
            "status",
            "task_id",
            "file_name",
            "content_type",
            "error_message",
            "generated_at",
            "completed_at",
        ]
