"""Custom DRF exception classes and a global exception handler."""
from __future__ import annotations

import logging

from rest_framework import status
from rest_framework.exceptions import APIException
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler

logger = logging.getLogger(__name__)


# ─── Domain exception classes ────────────────────────────────────────────────

class DuplicateFeedbackError(APIException):
    """Raised when a duplicate submission is detected within the debounce window."""

    status_code = status.HTTP_409_CONFLICT
    default_detail = "Duplicate feedback submission detected. Please wait before submitting again."
    default_code = "duplicate_feedback"


class ConsentNotFoundError(APIException):
    """Raised when no active consent record exists for a given anonymous user."""

    status_code = status.HTTP_404_NOT_FOUND
    default_detail = "No active consent record found for this user."
    default_code = "consent_not_found"


class GatewayError(APIException):
    """Raised when communication with an external gateway (SMS, WhatsApp) fails."""

    status_code = status.HTTP_502_BAD_GATEWAY
    default_detail = "An external gateway communication error occurred. Please try again shortly."
    default_code = "gateway_error"


class TemplateNotFoundError(APIException):
    """Raised when a requested message template does not exist in the library."""

    status_code = status.HTTP_404_NOT_FOUND
    default_detail = "The requested message template was not found."
    default_code = "template_not_found"


class AccountLockedError(APIException):
    """Raised when a user account is locked due to too many failed login attempts."""

    status_code = status.HTTP_403_FORBIDDEN
    default_detail = "Your account has been locked. Please contact an administrator."
    default_code = "account_locked"


class MFARequiredError(APIException):
    """Raised when MFA verification is required to complete authentication."""

    status_code = status.HTTP_401_UNAUTHORIZED
    default_detail = "Multi-factor authentication is required."
    default_code = "mfa_required"


# ─── Global exception handler ────────────────────────────────────────────────

def custom_exception_handler(exc: Exception, context: dict) -> Response | None:
    """
    Wraps DRF's default handler to produce a consistent error envelope:

        {
            "error": {
                "code": "...",
                "detail": "...",
                "status": 400
            }
        }
    """
    response = drf_exception_handler(exc, context)

    if response is not None:
        code = getattr(exc, "default_code", "error")
        response.data = {
            "error": {
                "code": code,
                "detail": response.data,
                "status": response.status_code,
            }
        }
    else:
        # Unhandled server error — log it and return a generic 500
        logger.exception("Unhandled exception in view: %s", exc)
        response = Response(
            {
                "error": {
                    "code": "internal_error",
                    "detail": "An unexpected error occurred.",
                    "status": status.HTTP_500_INTERNAL_SERVER_ERROR,
                }
            },
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    return response
