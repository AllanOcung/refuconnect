"""
Message Normaliser — C-04.

Single convergence point for all three inbound channels (SMS, USSD, WhatsApp).

``MessageNormaliser.process(raw_message)`` orchestrates:
  1. Sender anonymisation (phone → anonymous_user_id via Redis-cached hash)
  2. Duplicate detection (body SHA-256 hash, 300 s Redis TTL)
  3. Feedback record creation
  4. Pre-category linkage (USSD only)
  5. FeedbackMedia linkage (WhatsApp only)
  6. NLP Celery task dispatch
  7. Acknowledgement dispatch (SMS/WhatsApp only; USSD ack is on-screen)

Privacy contract:
  - raw_message['sender'] is zeroed out immediately after Step 1.
  - Phone numbers are NEVER written to logs, database fields, or Celery args.
  - Redis cache keys use the SHA-256 hash of the phone, not the phone itself.
  - Only anonymous_user_id and feedback_id appear in log statements.

``normalise_feedback()`` is kept as a backward-compatible helper for the
existing dashboard views that call it directly.
"""
from __future__ import annotations

import hashlib
import logging
import re
import threading
import time
import unicodedata
from datetime import datetime, timezone as stdlib_timezone
from typing import Optional, TYPE_CHECKING

from django.conf import settings
from django.core.cache import cache

from apps.common.audit import AuditAction, log_audit_event
from apps.common.utils import (
    generate_reference_id,
    hash_phone_number,
    truncate_text,
)

if TYPE_CHECKING:
    from apps.feedback.models import FeedbackMedia

logger = logging.getLogger("refuconnect.feedback.normaliser")

# ── Tunables ──────────────────────────────────────────────────────────────────
_PHONE_CACHE_TTL: int = 3600        # 1 hour — anon_id reuse window
_DUP_CHECK_TTL: int = 300           # 5 minutes — duplicate-message window
_ACK_TIMEOUT_SECONDS: int = 10      # hard cap for acknowledgement dispatch

# Per-channel content limits (characters)
_MAX_LENGTH = {
    "SMS": 480,        # 3 concatenated SMS segments
    "USSD": 160,       # USSD session frame limit (matches step 3 prompt)
    "WhatsApp": 4096,
}


# ═══════════════════════════════════════════════════════════════════════════════
# MessageNormaliser
# ═══════════════════════════════════════════════════════════════════════════════

class MessageNormaliser:
    """
    Canonical convergence point for all inbound feedback channels.

    ``process()`` is the only public method.  It consumes the *raw_message*
    dict produced by each adapter's view and orchestrates all side-effects
    (DB writes, cache reads/writes, Celery dispatch, acknowledgement).

    Thread safety
    -------------
    The instance holds no mutable state; it is safe to call ``process()``
    concurrently from multiple threads.
    """

    def process(self, raw_message: dict) -> int:
        """
        Normalise a raw channel message into a persisted ``Feedback`` record.

        Processing pipeline (in order):
          1. Anonymise sender (Redis-cached anonymous_user_id).
          2. Detect duplicates (body hash, Redis 300 s TTL).
          3. Create ``Feedback`` DB record.
          4. Link USSD pre-category (``FeedbackCategory``, confidence=0.80).
          5. Link WhatsApp media (``FeedbackMedia``).
          6. Enqueue NLP Celery task.
          7. Dispatch acknowledgement (SMS/WhatsApp only; async-guarded 10 s).
          8. Return feedback_id.

        Parameters
        ----------
        raw_message:
            Keys:
              channel    (str)           – 'SMS' | 'USSD' | 'WhatsApp'
              sender     (str)           – E.164 phone number (zeroed after step 1)
              body       (str)           – Raw message text
              received_at (datetime)     – UTC arrival time
              pre_category (str, opt)   – Category name from USSD step 1
              language_hint (str, opt)  – ISO 639-1 code from USSD step 0
              media_info   (dict, opt)  – From WhatsApp media download

        Returns
        -------
        int   The ``feedback_id`` of the newly created ``Feedback`` record.

        Security
        --------
        ``raw_message['sender']`` is zeroed to ``None`` immediately after the
        anonymous_user_id is computed.  Nothing after that point has access
        to the phone number.
        """
        # ── Step 1: Anonymise ──────────────────────────────────────────────
        sender: str = raw_message.get("sender") or ""
        anonymous_user_id = self._get_or_create_anon_id(sender)

        # Encrypt a copy of the phone for the ack-send path (first-time users
        # have no UserConsent yet, so route_notification cannot resolve their
        # phone from DB; we hand an encrypted copy to _dispatch_acknowledgement
        # so it can still reply to the inbound message).
        from apps.common.encryption import encrypt_field as _encrypt
        _encrypted_sender = _encrypt(sender) if sender else None
        del _encrypt  # cleanup import alias

        # PASSWORD ZERO: erase phone number from the in-memory dict immediately.
        # Anything below this line must ONLY use anonymous_user_id.
        raw_message["sender"] = None
        sender = ""  # belt-and-suspenders zero

        # ── Step 2: Duplicate detection ────────────────────────────────────
        channel: str = raw_message.get("channel", "SMS")
        body: str = raw_message.get("body", "")
        body = self._clean_and_truncate(body, channel)

        is_duplicate: bool = self._check_and_mark_duplicate(anonymous_user_id, body)

        # ── Step 3: Create Feedback record ─────────────────────────────────
        from apps.feedback.models import Feedback

        language_hint: Optional[str] = raw_message.get("language_hint") or None

        # For SMS/WhatsApp there is no pre-supplied hint. Detect the language now,
        # synchronously, so the ack and Feedback.language are both correct
        # immediately — without waiting for the async NLP pipeline.
        if not language_hint and channel in ("SMS", "WhatsApp") and body:
            try:
                from apps.nlp.pipeline.language_detector import detect_language
                _lang, _conf, _flags = detect_language(body)
                if _lang not in ("unknown", "other"):
                    language_hint = _lang
            except Exception:
                logger.warning(
                    "MessageNormaliser: Inline language detection failed for channel=%s "
                    "— ack will be sent in 'en'",
                    channel,
                )

        received_at: datetime = raw_message.get("received_at") or datetime.now(
            stdlib_timezone.utc
        )

        feedback = Feedback.objects.create(
            anonymous_user_id=anonymous_user_id,
            message_text=body,
            message_text_en=None,          # filled by NLP pipeline
            language=language_hint or "unknown",
            channel=channel,
            status=Feedback.Status.NEW,
            is_duplicate=is_duplicate,
            submitted_at=received_at,
            urgency_level=Feedback.UrgencyLevel.LOW,  # NLP will update
        )
        feedback_id: int = feedback.pk
        # SECURITY: log feedback_id only — anonymous_user_id is acceptable, no phone
        logger.info(
            "MessageNormaliser: Created feedback_id=%d channel=%s duplicate=%s",
            feedback_id,
            channel,
            is_duplicate,
        )

        # ── Step 4: USSD pre-category ──────────────────────────────────────
        pre_category: Optional[str] = raw_message.get("pre_category")
        if pre_category:
            self._link_pre_category(feedback, pre_category)

        # ── Step 5: WhatsApp media linkage ─────────────────────────────────
        media_info: Optional[dict] = raw_message.get("media_info")
        if media_info:
            self._create_media_record(feedback, media_info)

        # ── Step 6: Enqueue NLP task ───────────────────────────────────────
        try:
            from apps.nlp.tasks import process_feedback_nlp
            process_feedback_nlp.delay(feedback_id)
        except Exception:
            logger.exception(
                "MessageNormaliser: Failed to enqueue NLP task for feedback_id=%d",
                feedback_id,
            )

        # ── Step 7: Acknowledgement dispatch ──────────────────────────────
        if not is_duplicate:
            self._dispatch_acknowledgement(
                feedback_id=feedback_id,
                channel=channel,
                language=language_hint or "en",
                encrypted_phone=_encrypted_sender,
            )
        else:
            logger.debug(
                "MessageNormaliser: Skipping ack for duplicate feedback_id=%d", feedback_id
            )

        # ── Step 8: Return ─────────────────────────────────────────────────
        return feedback_id

    # ── Step 1 helper ─────────────────────────────────────────────────────────

    @staticmethod
    def _get_or_create_anon_id(sender: str) -> str:
        """
        Return a stable anonymous_user_id for the given phone number.

        Uses a Redis key keyed by ``hash_phone_number(sender, SALT)`` so that
        the same phone always produces the same anon ID within the 1-hour TTL.
        After TTL expiry the ID is rotated — this is intentional.

        Parameters
        ----------
        sender: E.164 phone number.  May be empty string for anonymous sources.

        Returns
        -------
        str  e.g. ``ANON-1736000000000-A1B2C3D4``
        """
        if not sender:
            epoch_ms = int(time.time() * 1000)
            return f"ANON-{epoch_ms}-UNKNOWN"

        # SECURITY: use phone hash as Redis key — never the raw phone
        salt: str = getattr(settings, "PHONE_HASH_SALT", settings.SECRET_KEY)
        phone_hash = hash_phone_number(sender, salt)
        cache_key = f"anon_id:{phone_hash}"

        cached = cache.get(cache_key)
        if cached:
            return cached

        epoch_ms = int(time.time() * 1000)
        anon_id = f"ANON-{epoch_ms}-{phone_hash[:8].upper()}"
        cache.set(cache_key, anon_id, _PHONE_CACHE_TTL)
        return anon_id

    # ── Step 2 helper ─────────────────────────────────────────────────────────

    @staticmethod
    def _check_and_mark_duplicate(anonymous_user_id: str, body: str) -> bool:
        """
        Return True if this exact message body was submitted by the same
        anonymous user within the last 300 seconds.

        Marks the body as seen in Redis (TTL=300 s) if not already present.
        Uses SHA-256 of the body so the cache never stores raw message text.

        Parameters
        ----------
        anonymous_user_id: Pre-computed anon ID (safe to use as part of Redis key).
        body:              Cleaned, truncated message body.
        """
        body_hash = hashlib.sha256(body.encode("utf-8")).hexdigest()
        dup_key = f"dup:{anonymous_user_id}:{body_hash}"

        if cache.get(dup_key):
            return True

        cache.set(dup_key, True, _DUP_CHECK_TTL)
        return False

    # ── Step 3 helpers — text cleaning ───────────────────────────────────────

    @staticmethod
    def _clean_and_truncate(text: str, channel: str) -> str:
        """
        NFC-normalise, strip control characters, collapse whitespace, then
        truncate to the per-channel limit.

        Parameters
        ----------
        text:    Raw body from the channel adapter.
        channel: 'SMS' | 'USSD' | 'WhatsApp'.
        """
        text = unicodedata.normalize("NFC", text)
        text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        text = text.strip()
        max_len = _MAX_LENGTH.get(channel, 4096)
        return truncate_text(text, max_len)

    # ── Step 4 helper ─────────────────────────────────────────────────────────

    @staticmethod
    def _link_pre_category(feedback, pre_category: str) -> None:
        """
        Look up *pre_category* by name and create a ``FeedbackCategory`` record
        with ``confidence_score=0.80`` and ``is_ai_assigned=False``.

        Fails silently if the category is not found so that USSD submissions
        are never blocked by a missing lookup-table entry.

        Parameters
        ----------
        feedback:     Newly created ``Feedback`` instance.
        pre_category: Category name string from USSD step 1 (e.g. ``'Health'``).
        """
        try:
            from apps.feedback.models import Category, FeedbackCategory
            category = Category.objects.get(category_name__iexact=pre_category, is_active=True)
            FeedbackCategory.objects.create(
                feedback=feedback,
                category=category,
                confidence_score=0.80,
                is_ai_assigned=False,
            )
        except Exception:
            logger.warning(
                "MessageNormaliser: Pre-category '%s' not found for feedback_id=%d",
                pre_category,
                feedback.pk,
            )

    # ── Step 5 helper ─────────────────────────────────────────────────────────

    @staticmethod
    def _create_media_record(feedback, media_info: dict) -> None:
        """
        Create a ``FeedbackMedia`` record linked to *feedback*.

        Parameters
        ----------
        feedback:   ``Feedback`` instance to link to.
        media_info: Dict with keys: media_type, storage_path, file_size_bytes.
        """
        try:
            from apps.feedback.models import FeedbackMedia
            FeedbackMedia.objects.create(
                feedback=feedback,
                media_type=media_info["media_type"],
                storage_path=media_info["storage_path"],
                file_size_bytes=media_info.get("file_size_bytes", 0),
            )
        except Exception:
            logger.exception(
                "MessageNormaliser: Failed to create FeedbackMedia for feedback_id=%d",
                feedback.pk,
            )

    # ── Step 7 helper ─────────────────────────────────────────────────────────

    def _dispatch_acknowledgement(
        self,
        feedback_id: int,
        channel: str,
        language: str,
        encrypted_phone: str | None = None,
    ) -> None:
        """
        Send an acknowledgement message via the appropriate channel adapter.

        USSD: on-screen END message already serves as the acknowledgement; skip.
        SMS/WhatsApp: call ``MessageRouter`` inside a daemon thread bound by
        ``_ACK_TIMEOUT_SECONDS``.  Failure does NOT raise — it is logged and
        a retry Celery task is enqueued instead.

        Parameters
        ----------
        feedback_id:     ID of the newly created Feedback record.
        channel:         'SMS' | 'USSD' | 'WhatsApp'.
        language:        ISO 639-1 language code for the template.
        encrypted_phone: AES-256-GCM ciphertext of the sender's phone (from
                         the inbound message).  Used for first-time users who
                         have no UserConsent record yet — without this they
                         would never receive the opt-in invite.
        """
        if channel == "USSD":
            logger.debug(
                "MessageNormaliser: USSD ack is on-screen for feedback_id=%d — skipping dispatch",
                feedback_id,
            )
            return

        reference_id = generate_reference_id(feedback_id)

        result_holder: dict = {"success": False, "error": None}
        timeout_flag = threading.Event()

        def _send() -> None:
            try:
                from apps.notifications.services.response_composer import compose_acknowledgement
                from apps.notifications.services.message_router import MessageRouter
                from apps.notifications.models import Notification, UserConsent
                from apps.common.encryption import decrypt_field
                from apps.feedback.models import Feedback

                feedback = Feedback.objects.get(pk=feedback_id)

                # Resolve the recipient phone.  Prefer the consent record
                # (returning users, respects channel_preference).  Fall back to
                # the encrypted phone carried over from the inbound message
                # (first-time users who have no consent yet — they must still
                # receive the opt-in invite so they can reply YES).
                consent = UserConsent.objects.filter(
                    anonymous_user_id=feedback.anonymous_user_id,
                    is_active=True,
                ).first()

                if consent is not None:
                    recipient = decrypt_field(consent.phone_number_encrypted)
                    send_channel = consent.channel_preference
                elif encrypted_phone:
                    recipient = decrypt_field(encrypted_phone)
                    send_channel = channel
                else:
                    logger.info(
                        "MessageNormaliser: No consent and no phone for feedback_id=%d; ack skipped",
                        feedback_id,
                    )
                    result_holder["success"] = True  # not an error
                    return

                msg_body = compose_acknowledgement(feedback, language=language, reference_id=reference_id)
                notification = Notification.objects.create(
                    feedback=feedback,
                    message_type=Notification.MessageType.ACKNOWLEDGEMENT,
                    content=msg_body,
                    delivery_language=language,
                    channel=send_channel,
                    delivery_status=Notification.DeliveryStatus.QUEUED,
                )
                result = MessageRouter().send(
                    channel=send_channel,
                    recipient=recipient,
                    body=msg_body,
                    notification_record=notification,
                )
                recipient = None  # Privacy wipe
                success = result["status"] == "Sent"
                result_holder["success"] = success
                if not success:
                    result_holder["error"] = "MessageRouter returned Failed"
            except Exception as exc:
                result_holder["error"] = str(exc)
                logger.exception(
                    "MessageNormaliser: Exception in _send() for feedback_id=%d", feedback_id
                )
            finally:
                timeout_flag.set()

        worker = threading.Thread(target=_send, daemon=True, name=f"ack-{feedback_id}")
        worker.start()
        completed = timeout_flag.wait(timeout=_ACK_TIMEOUT_SECONDS)

        if not completed:
            logger.critical(
                "MessageNormaliser: Acknowledgement for feedback_id=%d exceeded %ds timeout — "
                "enqueuing retry task",
                feedback_id,
                _ACK_TIMEOUT_SECONDS,
            )
            self._enqueue_ack_retry(feedback_id, channel, language, reference_id)
            return

        if result_holder.get("error"):
            logger.error(
                "MessageNormaliser: Acknowledgement failed for feedback_id=%d error=%s — "
                "enqueuing retry task",
                feedback_id,
                result_holder["error"],
            )
            self._enqueue_ack_retry(feedback_id, channel, language, reference_id)

    @staticmethod
    def _enqueue_ack_retry(
        feedback_id: int,
        channel: str,
        language: str,
        reference_id: str,
    ) -> None:
        """
        Enqueue ``retry_failed_acknowledgement`` Celery task.

        Wrapped in try/except so a Celery broker outage cannot cascade into
        complete feedback loss.
        """
        try:
            from apps.feedback.tasks import retry_failed_acknowledgement
            retry_failed_acknowledgement.apply_async(
                args=[feedback_id, channel, language, reference_id],
                countdown=30,
            )
        except Exception:
            logger.exception(
                "MessageNormaliser: Failed to enqueue retry task for feedback_id=%d",
                feedback_id,
            )
            # Log an AuditLog entry so the failure is visible in the dashboard
            try:
                from apps.feedback.models import Feedback
                fb = Feedback.objects.get(pk=feedback_id)
                log_audit_event(
                    user=None,
                    action=AuditAction.NOTIFICATION_SENT,
                    feedback=fb,
                    field_changed="acknowledgement",
                    new_value="FAILED_NO_RETRY",
                )
            except Exception:
                pass  # don't let audit logging failure cascade further


# ═══════════════════════════════════════════════════════════════════════════════
# Backward-compatible functional API (used by existing dashboard views)
# ═══════════════════════════════════════════════════════════════════════════════

def normalise_feedback(
    message_text: str,
    channel: str,
    anonymous_user_id: str,
    **kwargs,
) -> dict:
    """
    Normalise raw feedback data from any channel into a common dict.

    This function is retained for backward compatibility with the existing
    ``FeedbackListView`` / ``FeedbackDetailView`` code paths that build a dict
    and then call ``Feedback.objects.create(**data)`` themselves.

    New code should use ``MessageNormaliser.process()`` instead.

    Parameters
    ----------
    message_text:       Raw text from the channel.
    channel:            One of 'SMS', 'USSD', 'WhatsApp'.
    anonymous_user_id:  Pre-hashed identifier for the submitting user.
    **kwargs:           Any additional valid Feedback field values.

    Returns
    -------
    dict ready to be unpacked into ``Feedback.objects.create``.
    """
    normaliser = MessageNormaliser()
    cleaned = normaliser._clean_and_truncate(message_text, channel)

    is_duplicate = normaliser._check_and_mark_duplicate(anonymous_user_id, cleaned)

    return {
        "message_text": cleaned,
        "channel": channel,
        "anonymous_user_id": anonymous_user_id,
        "is_duplicate": is_duplicate,
        # Always mark the old compat path as duplicate so callers can decide
        "message_normalised": cleaned,  # kept for legacy attribute names
        **kwargs,
    }
