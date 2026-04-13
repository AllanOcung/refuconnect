"""
Pagination classes for the dashboard app.
"""
from __future__ import annotations

from rest_framework.pagination import PageNumberPagination


class StandardResultsPagination(PageNumberPagination):
    """Default: 25 items per page, max 100."""

    page_size = 25
    page_size_query_param = "page_size"
    max_page_size = 100


class LargeResultsPagination(PageNumberPagination):
    """Large export: 100 items per page, max 500."""

    page_size = 100
    page_size_query_param = "page_size"
    max_page_size = 500
