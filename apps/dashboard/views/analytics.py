from __future__ import annotations

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.dashboard.permissions import IsNGOStaff
from apps.dashboard.services.analytics_engine import AnalyticsEngine


def _filters_from_request(request: Request) -> dict:
    excluded = {"days", "page", "page_size", "ordering"}
    return {
        key: request.query_params.getlist(key)
        if len(request.query_params.getlist(key)) > 1
        else request.query_params.get(key)
        for key in request.query_params
        if key not in excluded
    }


def _org_id(request: Request):
    return getattr(request.user, "organisation", "") or 1


class AnalyticsSummaryView(APIView):
    permission_classes = [IsAuthenticated, IsNGOStaff]

    def get(self, request: Request) -> Response:
        data = AnalyticsEngine().get_summary(_filters_from_request(request), _org_id(request))
        return Response(data, status=status.HTTP_200_OK)


class SentimentTrendView(APIView):
    permission_classes = [IsAuthenticated, IsNGOStaff]

    def get(self, request: Request) -> Response:
        try:
            days = int(request.query_params.get("days", 30))
        except ValueError:
            return Response(
                {"detail": "days must be an integer."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if days < 1 or days > 90:
            return Response(
                {"detail": "days must be between 1 and 90."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        data = AnalyticsEngine().get_sentiment_timeseries(
            days, _filters_from_request(request)
        )
        return Response(data, status=status.HTTP_200_OK)


class ThemeSummaryView(APIView):
    permission_classes = [IsAuthenticated, IsNGOStaff]

    def get(self, request: Request) -> Response:
        return Response(AnalyticsEngine().get_theme_summary(), status=status.HTTP_200_OK)
