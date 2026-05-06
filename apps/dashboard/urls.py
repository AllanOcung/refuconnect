from __future__ import annotations

from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView

from apps.dashboard.views.alerts import (
    AlertAcknowledgeView,
    AlertListView,
    AlertResolveView,
    AlertStatsView,
)
from apps.dashboard.views.analytics import (
    AnalyticsSummaryView,
    SentimentTrendView,
    ThemeSummaryView,
)
from apps.dashboard.views.auth import (
    LoginView,
    LogoutView,
    MFAConfirmView,
    MFASetupView,
    PasswordResetConfirmView,
    PasswordResetRequestView,
)
from apps.dashboard.views.feedback import AuditLogView, FeedbackDetailView, FeedbackListView
from apps.dashboard.views.reports import (
    ReportGenerateView,
    ReportHistoryView,
    ReportTaskDownloadView,
    ReportTaskStatusView,
)
from apps.dashboard.views.users import (
    UserDetailView,
    UserInviteView,
    UserListView,
    UserUnlockView,
)

app_name = "dashboard"

urlpatterns = [
    path("auth/login/", LoginView.as_view(), name="login"),
    path("auth/logout/", LogoutView.as_view(), name="logout"),
    path("auth/token/refresh/", TokenRefreshView.as_view(), name="token-refresh"),
    path(
        "auth/password-reset/request/",
        PasswordResetRequestView.as_view(),
        name="password-reset-request",
    ),
    path(
        "auth/password-reset/confirm/",
        PasswordResetConfirmView.as_view(),
        name="password-reset-confirm",
    ),
    path("auth/mfa/setup/", MFASetupView.as_view(), name="mfa-setup"),
    path("auth/mfa/confirm/", MFAConfirmView.as_view(), name="mfa-confirm"),
    path("feedback/", FeedbackListView.as_view(), name="feedback-list"),
    path("feedback/<int:feedback_id>/", FeedbackDetailView.as_view(), name="feedback-detail"),
    path("audit-log/", AuditLogView.as_view(), name="audit-log"),
    path("analytics/summary/", AnalyticsSummaryView.as_view(), name="analytics-summary"),
    path(
        "analytics/sentiment-trend/",
        SentimentTrendView.as_view(),
        name="analytics-sentiment-trend",
    ),
    path("analytics/themes/", ThemeSummaryView.as_view(), name="analytics-themes"),
    path("reports/generate/", ReportGenerateView.as_view(), name="reports-generate"),
    path("reports/history/", ReportHistoryView.as_view(), name="reports-history"),
    path(
        "reports/tasks/<str:task_id>/",
        ReportTaskStatusView.as_view(),
        name="reports-task-status",
    ),
    path(
        "reports/tasks/<str:task_id>/download/",
        ReportTaskDownloadView.as_view(),
        name="reports-task-download",
    ),
    path("alerts/", AlertListView.as_view(), name="alert-list"),
    path("alerts/stats/", AlertStatsView.as_view(), name="alert-stats"),
    path(
        "alerts/<int:alert_id>/acknowledge/",
        AlertAcknowledgeView.as_view(),
        name="alert-acknowledge",
    ),
    path(
        "alerts/<int:alert_id>/resolve/",
        AlertResolveView.as_view(),
        name="alert-resolve",
    ),
    path("users/", UserListView.as_view(), name="user-list"),
    path("users/invite/", UserInviteView.as_view(), name="user-invite"),
    path("users/<int:user_id>/", UserDetailView.as_view(), name="user-detail"),
    path("users/<int:user_id>/unlock/", UserUnlockView.as_view(), name="user-unlock"),
]
