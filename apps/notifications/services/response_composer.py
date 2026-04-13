"""
Response composer — builds notification message text from templates.
"""
from __future__ import annotations

from apps.common.utils import generate_reference_id
from apps.feedback.models import Feedback
from apps.notifications.services.template_library import get_template


def compose_acknowledgement(feedback: Feedback, language: str = "en") -> str:
    """Build an acknowledgement message for the given feedback record."""
    reference_id = generate_reference_id(feedback.feedback_id)
    template = get_template("acknowledgement", language)
    return template.format(reference_id=reference_id)


def compose_targeted_response(
    feedback: Feedback,
    custom_message: str,
    language: str = "en",
) -> str:
    """Build a targeted response for the given feedback record."""
    reference_id = generate_reference_id(feedback.feedback_id)
    template = get_template("targeted_response", language)
    return template.format(reference_id=reference_id, custom_message=custom_message)


def compose_broadcast(
    message: str,
    language: str = "en",
    broadcast_type: str = "broadcast_general",
) -> str:
    """
    Build a broadcast message.
    broadcast_type: "broadcast_general" or "broadcast_yswd"
    """
    if broadcast_type not in ("broadcast_general", "broadcast_yswd"):
        broadcast_type = "broadcast_general"
    template = get_template(broadcast_type, language)
    return template.format(message=message)
