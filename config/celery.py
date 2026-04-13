"""Celery application configuration for RefuConnect."""
import os
from celery import Celery
from celery.schedules import crontab

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.development")

app = Celery("refuconnect")

# Read config from Django settings, namespace CELERY_
app.config_from_object("django.conf:settings", namespace="CELERY")

# Auto-discover tasks in all installed apps
app.autodiscover_tasks()

# ─── Periodic task schedule ───────────────────────────────────────────────────
app.conf.beat_schedule = {
    # Run weekly theme clustering every Monday at 02:00 UTC
    "weekly-theme-clustering": {
        "task": "apps.nlp.tasks.run_weekly_theme_clustering",
        "schedule": crontab(hour=2, minute=0, day_of_week=1),
    },
    # Retry failed notifications every 15 minutes
    "retry-failed-notifications": {
        "task": "apps.notifications.tasks.retry_failed_notifications",
        "schedule": crontab(minute="*/15"),
    },
    # Archive old processed feedback daily at 03:00 UTC
    "archive-old-feedback": {
        "task": "apps.feedback.tasks.archive_old_feedback",
        "schedule": crontab(hour=3, minute=0),
    },
}


@app.task(bind=True, ignore_result=True)
def debug_task(self):
    print(f"Request: {self.request!r}")
