"""
URL configuration for the dashboard app.
"""
from __future__ import annotations

from django.urls import path

from apps.dashboard.views.alerts import AlertAcknowledgeView, AlertDetailView, AlertListView
from apps.dashboard.views.analytics import (
    ChannelBreakdownView,
    FeedbackSummaryView,
    SentimentTrendsView,
    UrgencyBreakdownView,
)
from apps.dashboard.views.auth import LoginView, LogoutView, PasswordChangeView
from apps.dashboard.views.feedback import BulkFeedbackFlagView, BulkFeedbackStatusView
from apps.dashboard.views.reports import ExcelReportView, PDFReportView
from apps.dashboard.views.users import UserDetailView, UserListCreateView, UserStatusView

app_name = "dashboard"

urlpatterns = [
    # Auth
    path("auth/login/", LoginView.as_view(), name="login"),
    path("auth/logout/", LogoutView.as_view(), name="logout"),
    path("auth/password-change/", PasswordChangeView.as_view(), name="password-change"),
    # Users
    path("users/", UserListCreateView.as_view(), name="user-list-create"),
    path("users/<int:pk>/", UserDetailView.as_view(), name="user-detail"),
    path("users/<int:pk>/status/", UserStatusView.as_view(), name="user-status"),
    # Analytics
    path("analytics/summary/", FeedbackSummaryView.as_view(), name="analytics-summary"),
    path("analytics/channels/", ChannelBreakdownView.as_view(), name="analytics-channels"),
    path("analytics/sentiment-trends/", SentimentTrendsView.as_view(), name="analytics-sentiment-trends"),
    path("analytics/urgency/", UrgencyBreakdownView.as_view(), name="analytics-urgency"),
    # Reports
    path("reports/pdf/", PDFReportView.as_view(), name="reports-pdf"),
    path("reports/excel/", ExcelReportView.as_view(), name="reports-excel"),
    # Alerts
    path("alerts/", AlertListView.as_view(), name="alert-list"),
    path("alerts/<int:pk>/", AlertDetailView.as_view(), name="alert-detail"),
    path("alerts/<int:pk>/acknowledge/", AlertAcknowledgeView.as_view(), name="alert-acknowledge"),
    # Feedback bulk ops
    path("feedback/bulk-status/", BulkFeedbackStatusView.as_view(), name="feedback-bulk-status"),
    path("feedback/bulk-flag/", BulkFeedbackFlagView.as_view(), name="feedback-bulk-flag"),
]
