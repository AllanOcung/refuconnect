from __future__ import annotations

from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response


class StandardResultsPagination(PageNumberPagination):
    """Default dashboard paginator."""

    page_size = 50
    page_size_query_param = "page_size"
    max_page_size = 100


class FeedbackPagination(StandardResultsPagination):
    page_size = 50


class AuditLogPagination(StandardResultsPagination):
    page_size = 100
    max_page_size = 100


class AlertPagination(StandardResultsPagination):
    """Alert paginator that includes the open badge count."""

    page_size = 50

    def get_paginated_response(self, data):
        open_count = getattr(self, "open_count", 0)
        return Response(
            {
                "count": self.page.paginator.count,
                "next": self.get_next_link(),
                "previous": self.get_previous_link(),
                "open_count": open_count,
                "results": data,
            }
        )


class LargeResultsPagination(PageNumberPagination):
    page_size = 100
    page_size_query_param = "page_size"
    max_page_size = 500
