"""
Analytics views — feed count breakdowns, trend data, sentiment distribution.
"""
from __future__ import annotations

import logging
from datetime import date, timedelta

from django.db.models import Count, Q
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.dashboard.services.analytics_engine import (
    get_channel_breakdown,
    get_feedback_summary,
    get_sentiment_trends,
    get_urgency_breakdown,
)

logger = logging.getLogger(__name__)


class FeedbackSummaryView(APIView):
    """
    GET /api/v1/dashboard/analytics/summary/
    Query params: date_from (YYYY-MM-DD), date_to (YYYY-MM-DD)
    """

    permission_classes = [IsAuthenticated]

    def get(self, request: Request) -> Response:
        date_from_str = request.query_params.get("date_from")
        date_to_str = request.query_params.get("date_to")

        try:
            date_from = date.fromisoformat(date_from_str) if date_from_str else date.today() - timedelta(days=30)
            date_to = date.fromisoformat(date_to_str) if date_to_str else date.today()
        except ValueError:
            return Response(
                {"detail": "Invalid date format. Use YYYY-MM-DD."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        summary = get_feedback_summary(date_from, date_to)
        return Response(summary, status=status.HTTP_200_OK)


class ChannelBreakdownView(APIView):
    """
    GET /api/v1/dashboard/analytics/channels/
    Returns feedback count per channel.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request: Request) -> Response:
        breakdown = get_channel_breakdown()
        return Response(breakdown, status=status.HTTP_200_OK)


class SentimentTrendsView(APIView):
    """
    GET /api/v1/dashboard/analytics/sentiment-trends/
    Query params: days (default 30)
    """

    permission_classes = [IsAuthenticated]

    def get(self, request: Request) -> Response:
        try:
            days = int(request.query_params.get("days", 30))
            if days < 1 or days > 365:
                raise ValueError
        except ValueError:
            return Response(
                {"detail": "days must be an integer between 1 and 365."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        trends = get_sentiment_trends(days=days)
        return Response(trends, status=status.HTTP_200_OK)


class UrgencyBreakdownView(APIView):
    """
    GET /api/v1/dashboard/analytics/urgency/
    """

    permission_classes = [IsAuthenticated]

    def get(self, request: Request) -> Response:
        breakdown = get_urgency_breakdown()
        return Response(breakdown, status=status.HTTP_200_OK)
