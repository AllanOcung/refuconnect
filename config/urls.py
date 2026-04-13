"""Root URL configuration for RefuConnect."""
from django.contrib import admin
from django.urls import path, include
from django.http import JsonResponse


def health_check(request):
    return JsonResponse({"status": "ok"})


urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/health/", health_check, name="health-check"),
    path("api/v1/", include("apps.dashboard.urls")),
    path("api/v1/feedback/", include("apps.feedback.urls")),
    path("api/v1/notifications/", include("apps.notifications.urls")),
]
