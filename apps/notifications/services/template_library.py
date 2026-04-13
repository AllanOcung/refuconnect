"""
Multilingual message templates for automated notifications.

Templates support three languages: English (en), Swahili (sw), Luganda (lg).
"""
from __future__ import annotations

_TEMPLATES: dict[str, dict[str, str]] = {
    "acknowledgement": {
        "en": (
            "Hello! We have received your message (Ref: {reference_id}). "
            "Thank you for reaching out. Our team is reviewing your feedback."
        ),
        "sw": (
            "Habari! Tumepokea ujumbe wako (Kumb: {reference_id}). "
            "Asante kwa kuwasiliana nasi. Timu yetu inakagua maoni yako."
        ),
        "lg": (
            "Osiibwa! Tufunye obubaka bwo (Ref: {reference_id}). "
            "Webale okutuukirira. Akabinja kaffe kagenda okulaba ebyo bye wagamba."
        ),
    },
    "targeted_response": {
        "en": "Dear community member (Ref: {reference_id}): {custom_message}",
        "sw": "Ndugu mwanajamii (Kumb: {reference_id}): {custom_message}",
        "lg": "Munno (Ref: {reference_id}): {custom_message}",
    },
    "broadcast_general": {
        "en": "RefuConnect Community Update: {message}",
        "sw": "Taarifa ya Jamii ya RefuConnect: {message}",
        "lg": "Amakuru g'Ekibiina kya RefuConnect: {message}",
    },
    "broadcast_yswd": {
        "en": "Your Safety & Well-being: {message}",
        "sw": "Usalama na Ustawi Wako: {message}",
        "lg": "Obukuumi bwo n'Obulamu bwo: {message}",
    },
}

_FALLBACK_LANGUAGE = "en"


def get_template(name: str, language: str) -> str:
    """
    Return the template string for the given name and language.
    Falls back to English if the requested language is unavailable.

    Raises KeyError if the template name does not exist.
    """
    templates_for_name = _TEMPLATES[name]
    return templates_for_name.get(language) or templates_for_name[_FALLBACK_LANGUAGE]
