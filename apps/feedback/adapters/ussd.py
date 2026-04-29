"""
Africa's Talking USSD Session Manager — C-02.

Implements a 4-step stateful USSD flow:
  Step 0 — Language selection   (text == '')
  Step 1 — Category selection   (text has 1 part)
  Step 2 — Free-text entry      (text has 2 parts)
  Step 3 — Confirm & save       (text has 3+ parts)

Africa's Talking encodes the full session path in the ``text`` field as a
``*``-separated string.  Each POST from AT represents one round-trip.

USSD response rules (required by AT protocol):
  ``CON …``  — session continues; user sees the prompt and types a reply.
  ``END …``  — session terminates; handset shows the message and closes.

No HMAC signature is required for USSD callbacks.
Phone numbers are NEVER logged — only session_id or feedback_id.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone as stdlib_timezone

from django.core.cache import cache
from django.http import HttpResponse
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.views import APIView

logger = logging.getLogger("refuconnect.feedback.ussd")

# ── Session / flow constants ──────────────────────────────────────────────────
_SESSION_TIMEOUT_SECONDS: int = 90
_MAX_MESSAGE_LENGTH: int = 160

_LANGUAGE_MAP: dict[str, str] = {
    "1": "en",
    "2": "sw",
}

_CATEGORY_MAP: dict[str, str] = {
    "1": "Health",
    "2": "Protection/Safety",
    "3": "Education",
    "4": "WASH",
    "5": "Food Security",
    "6": "Other",
}

# ── Menu text ─────────────────────────────────────────────────────────────────
_STEP_0_MENU = (
    "RefuConnect\n"
    "Select language:\n"
    "1. English\n"
    "2. Swahili"
)

_STEP_1_MENU = (
    "Select topic:\n"
    "1. Health\n"
    "2. Protection/Safety\n"
    "3. Education\n"
    "4. Water/WASH\n"
    "5. Food Security\n"
    "6. Other"
)

_STEP_2_PROMPT = "Type your message\n(160 chars max):"

_TIMEOUT_END = (
    "END Session ended.\n"
    "No message sent.\n"
    "Dial *123# to try again."
)

_ERROR_END = (
    "END A system error occurred.\n"
    "Please try again by dialling the short code."
)


# ── USSDSessionView ───────────────────────────────────────────────────────────

class USSDSessionView(APIView):
    """
    Handle stateful USSD sessions from Africa's Talking.

    Endpoint: POST /api/v1/webhooks/ussd/

    Response ``Content-Type`` is ``text/plain`` (required by the AT protocol).
    State is implicit in the ``text`` accumulation field — no server-side
    session storage is needed for the menu steps; only the session start
    timestamp is persisted to Redis for timeout enforcement.
    """

    permission_classes = [AllowAny]
    throttle_classes = []

    def post(self, request: Request) -> HttpResponse:
        """
        Process one AT USSD round-trip.

        AT sends: sessionId, serviceCode, phoneNumber, text.
        Responses must be plain-text strings prefixed with CON or END.
        """
        session_id: str = request.data.get("sessionId", "")
        phone: str = request.data.get("phoneNumber", "")
        text: str = request.data.get("text", "")
        service_code: str = request.data.get("serviceCode", "")

        if not session_id or not phone:
            return HttpResponse("END Invalid session.", content_type="text/plain")

        # Timeout guard — Redis-backed, 90 s window
        if self._is_timed_out(session_id):
            logger.debug("USSDSessionView: session_id=%s timed out", session_id)
            return HttpResponse(_TIMEOUT_END, content_type="text/plain")

        # Parse the accumulated input path
        parts = text.split("*") if text else []
        step = len(parts)

        try:
            response_text = self._route_step(step, parts, phone, session_id)
        except Exception:
            logger.exception(
                "USSDSessionView: Unexpected error in session_id=%s step=%d",
                session_id, step,
            )
            response_text = _ERROR_END

        return HttpResponse(response_text, content_type="text/plain")

    # ── Step routing ──────────────────────────────────────────────────────────

    def _route_step(
        self,
        step: int,
        parts: list[str],
        phone: str,
        session_id: str,
    ) -> str:
        """
        Dispatch to the handler for the current step.

        Parameters
        ----------
        step:       Number of ``*``-delimited segments in ``text`` (0 = first contact).
        parts:      List of user-entered values accumulated so far.
        phone:      Caller's phone (anonymised inside step 3 — not logged here).
        session_id: AT session ID (logged for tracing; contains no PII).
        """
        # Step 0: first contact — language selection
        if step == 0:
            return "CON " + _STEP_0_MENU

        # Validate language choice
        lang_choice = parts[0].strip()
        if lang_choice not in _LANGUAGE_MAP:
            return "END Invalid language choice.\nDial *123# to try again."

        # Step 1: category selection
        if step == 1:
            return "CON " + _STEP_1_MENU

        # Validate category choice
        cat_choice = parts[1].strip()
        if cat_choice not in _CATEGORY_MAP:
            # Re-prompt the category menu instead of ending the session
            return "CON Invalid choice.\n" + _STEP_1_MENU

        # Step 2: message-entry prompt
        if step == 2:
            return "CON " + _STEP_2_PROMPT

        # Step 3+: message entered — confirm and save
        raw_message_text = "*".join(parts[2:]).strip()
        return self._step_3_confirm(
            raw_message_text=raw_message_text,
            phone=phone,
            language=_LANGUAGE_MAP[lang_choice],
            pre_category=_CATEGORY_MAP[cat_choice],
            session_id=session_id,
        )

    # ── Step 3: confirmation + Feedback creation ──────────────────────────────

    @staticmethod
    def _step_3_confirm(
        raw_message_text: str,
        phone: str,
        language: str,
        pre_category: str,
        session_id: str,
    ) -> str:
        """
        Validate the message, call ``MessageNormaliser``, and return the
        reference ID to display on-screen (the on-screen display IS the ack).

        Parameters
        ----------
        raw_message_text: User's free-text feedback (160-char limit enforced).
        phone:            Caller's phone number — anonymised inside the normaliser.
        language:         ISO 639-1 code from step 0 (en / sw / lg).
        pre_category:     Category name from step 1.
        session_id:       AT session ID for logging only.
        """
        message_text = raw_message_text[:_MAX_MESSAGE_LENGTH]
        if len(message_text.strip()) < 3:
            return (
                "END Message too short.\n"
                "No message saved.\n"
                "Dial *123# to try again."
            )

        try:
            from apps.feedback.services.normaliser import MessageNormaliser
            from apps.common.utils import generate_reference_id

            raw_message = {
                "channel": "USSD",
                "sender": phone,
                "body": message_text,
                "received_at": datetime.now(stdlib_timezone.utc),
                "language_hint": language,
                "pre_category": pre_category,
            }
            feedback_id = MessageNormaliser().process(raw_message)
            reference_id = generate_reference_id(feedback_id)

            # SECURITY: log session_id and feedback_id only — never the phone
            logger.info(
                "USSDSessionView: Created feedback_id=%s session_id=%s",
                feedback_id,
                session_id,
            )
            return (
                f"END Thank you! Message received.\n"
                f"Ref: {reference_id}\n"
                "Dial *123# to send another."
            )
        except Exception:
            logger.exception(
                "USSDSessionView: Error creating feedback for session_id=%s", session_id
            )
            return (
                "END Sorry, your message could not be saved.\n"
                "Please try again later."
            )

    # ── Session timeout ───────────────────────────────────────────────────────

    @staticmethod
    def _is_timed_out(session_id: str) -> bool:
        """
        Return True if the session has exceeded ``_SESSION_TIMEOUT_SECONDS``.

        Stores the session start epoch in Redis on first call.
        The Redis key expires automatically after ``_SESSION_TIMEOUT_SECONDS + 10``
        seconds so stale keys don't accumulate.

        Parameters
        ----------
        session_id: Africa's Talking session identifier (no PII).
        """
        cache_key = f"ussd:session:{session_id}:start"
        start_ts = cache.get(cache_key)
        now_ts = time.time()

        if start_ts is None:
            cache.set(cache_key, now_ts, _SESSION_TIMEOUT_SECONDS + 10)
            return False

        return (now_ts - start_ts) > _SESSION_TIMEOUT_SECONDS


# ── Backward-compatible USSDAdapter shim ─────────────────────────────────────

class USSDAdapter:
    """
    Legacy adapter shim retained for backward compatibility with existing tests
    and the old webhook view in ``apps/feedback/views.py``.

    New code should use ``USSDSessionView`` directly.
    """

    @staticmethod
    def parse_incoming(data: dict) -> dict:
        """Parse an Africa's Talking USSD callback payload into a consistent dict."""
        return {
            "session_id": data.get("sessionId", ""),
            "phone": data.get("phoneNumber", ""),
            "text": data.get("text", ""),
            "service_code": data.get("serviceCode", ""),
        }

    def handle_session(
        self,
        session_id: str,
        phone: str,
        text: str,
        service_code: str,
    ) -> str:
        """
        Compatibility shim that delegates to ``USSDSessionView`` instance logic.

        Returns a ``CON …`` or ``END …`` string.
        """
        parts = text.split("*") if text else []
        step = len(parts)
        view = USSDSessionView()
        return view._route_step(step, parts, phone, session_id)

# ── Menu definitions ──────────────────────────────────────────────────────────

_MAIN_MENU = (
    "Welcome to RefuConnect.\n"
    "Your voice matters.\n"
    "1. Submit Feedback\n"
    "2. Check submission status\n"
    "0. Exit"
)

_FEEDBACK_PROMPT = (
    "Please type your feedback message and press Send.\n"
    "Your identity is kept anonymous."
)

_STATUS_PROMPT = "Enter your reference number (e.g. RFC-00000001):"


class USSDAdapter:
    """
    Stateless USSD session handler.

    Africa's Talking encodes the full user input path in ``text`` as a
    ``*``-separated string.  Each call to ``handle_session`` inspects the
    depth and routes accordingly.
    """

    # ── Session handler ───────────────────────────────────────────────────────

    def handle_session(
        self,
        session_id: str,
        phone: str,
        text: str,
        service_code: str,
    ) -> str:
        """
        Process one USSD round-trip and return the provider response string.

        Parameters
        ----------
        session_id: Unique session identifier from the provider.
        phone:      Caller's phone number.
        text:       Full ``*``-delimited input history for this session.
        service_code: The USSD short code dialled.

        Returns
        -------
        str starting with ``CON `` (session continues) or ``END `` (terminates).
        """
        parts = [p.strip() for p in text.split("*")] if text else []
        depth = len(parts)

        # ── Level 0: first contact ─────────────────────────────────────────
        if depth == 0 or text == "":
            return f"CON {_MAIN_MENU}"

        first = parts[0]

        if first == "0":
            return "END Thank you for using RefuConnect. Goodbye!"

        # ── Level 1: main menu selection ──────────────────────────────────
        if depth == 1:
            if first == "1":
                return f"CON {_FEEDBACK_PROMPT}"
            if first == "2":
                return f"CON {_STATUS_PROMPT}"
            return "END Invalid option. Please dial again and choose 1 or 2."

        # ── Level 2 ───────────────────────────────────────────────────────
        if first == "1" and depth == 2:
            return self._handle_feedback_submission(parts[1], phone, session_id)

        if first == "2" and depth == 2:
            return self._handle_status_check(parts[1])

        return "END An unexpected error occurred. Please try again."

    # ── Private helpers ───────────────────────────────────────────────────────

    def _handle_feedback_submission(
        self, message_text: str, phone: str, session_id: str
    ) -> str:
        """Validate and queue the feedback for async processing."""
        if len(message_text.strip()) < 5:
            return (
                "END Your message is too short. "
                "Please dial again and provide more detail."
            )

        try:
            from apps.feedback.services.normaliser import normalise_feedback
            from apps.feedback.models import Feedback
            from apps.common.utils import hash_phone_number
            from django.conf import settings
            from django.utils import timezone

            anon_id = hash_phone_number(phone, settings.SECRET_KEY)
            data = normalise_feedback(
                message_text=message_text,
                channel="USSD",
                anonymous_user_id=anon_id,
            )
            data["submitted_at"] = timezone.now()
            feedback = Feedback.objects.create(**data)

            # Trigger async NLP processing
            from apps.nlp.tasks import process_feedback_async
            process_feedback_async.delay(feedback.feedback_id)

            ref = f"RFC-{feedback.feedback_id:08d}"
            return (
                f"END Thank you! Your feedback has been received.\n"
                f"Reference: {ref}\n"
                "We will review it shortly."
            )
        except Exception:
            logger.exception("Error saving USSD feedback from session %s", session_id)
            return "END Sorry, we could not save your feedback. Please try again later."

    @staticmethod
    def _handle_status_check(reference: str) -> str:
        """Look up a feedback status by reference code."""
        reference = reference.strip().upper()
        try:
            # Extract numeric ID from reference (RFC-00000042-XXXXXX or RFC-00000042)
            parts = reference.split("-")
            feedback_id = int(parts[1]) if len(parts) >= 2 else None
        except (IndexError, ValueError):
            return "END Invalid reference format. Expected RFC-XXXXXXXX."

        if feedback_id is None:
            return "END Could not parse the reference number."

        try:
            from apps.feedback.models import Feedback
            fb = Feedback.objects.only("status", "feedback_id").get(
                feedback_id=feedback_id
            )
            return (
                f"END Status for {reference}:\n"
                f"Your feedback is currently: {fb.status}.\n"
                "Thank you for following up."
            )
        except Feedback.DoesNotExist:
            return f"END Reference {reference} was not found in our system."

    # ── Inbound payload parser ────────────────────────────────────────────────

    @staticmethod
    def parse_incoming(data: dict) -> dict:
        """Normalise an Africa's Talking USSD webhook payload."""
        return {
            "session_id": data.get("sessionId", ""),
            "phone": data.get("phoneNumber", ""),
            "text": data.get("text", ""),
            "service_code": data.get("serviceCode", ""),
            "network_code": data.get("networkCode", ""),
        }
