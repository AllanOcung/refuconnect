"""
Notifications app configuration.

Includes a Django system check that verifies the ACKNOWLEDGEMENT English
template exists on startup. The system cannot acknowledge any feedback if
this template is missing.
"""
from __future__ import annotations

from django.apps import AppConfig
from django.core.checks import Warning, register


class NotificationsConfig(AppConfig):
    name = "apps.notifications"
    verbose_name = "Notifications"

    def ready(self) -> None:
        register(check_acknowledgement_template)


def check_acknowledgement_template(app_configs, **kwargs):
    """
    Verify the ACKNOWLEDGEMENT template in English exists and is active.
    Raises a system warning (not an error) so the server still starts but
    operators are alerted immediately.
    """
    errors = []
    try:
        from apps.notifications.models import MessageTemplate

        exists = MessageTemplate.objects.filter(
            template_key="ACKNOWLEDGEMENT",
            language="en",
            is_active=True,
        ).exists()

        if not exists:
            errors.append(
                Warning(
                    "The ACKNOWLEDGEMENT message template (language='en') is missing or inactive. "
                    "The system cannot send acknowledgements to any feedback channel. "
                    "Run the seed migration or create it via the admin.",
                    hint=(
                        "Run: python manage.py migrate apps.notifications "
                        "or create a MessageTemplate with template_key='ACKNOWLEDGEMENT', language='en'."
                    ),
                    obj=None,
                    id="notifications.W001",
                )
            )
    except Exception:
        # DB may not be ready yet (e.g. first migrate run) — skip check
        pass

    return errors