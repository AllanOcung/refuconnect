"""
Shared utility functions used across all RefuConnect apps.
"""
from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone
from typing import Optional


def generate_reference_id(feedback_id: int) -> str:
    """
    Return a human-readable, unique reference ID for a feedback record.

    Format: ``RFC-00000042-A3F9B1``

    The suffix is derived from a UUID4 so that even feedback with the same
    numeric ID (e.g. across test environments) produces distinct references.
    """
    suffix = uuid.uuid4().hex[:6].upper()
    return f"RFC-{feedback_id:08d}-{suffix}"


def hash_phone_number(phone: str, salt: str) -> str:
    """
    Produce a one-way SHA-256 hash of a phone number combined with a salt.

    This is used for deduplication / lookup without storing the raw number.

    Parameters
    ----------
    phone:
        E.164-formatted phone number, e.g. ``"+256700123456"``.
    salt:
        A stable, secret salt value (use ``settings.SECRET_KEY`` or a
        dedicated ``PHONE_HASH_SALT`` env variable).
    """
    return hashlib.sha256(f"{salt}:{phone}".encode("utf-8")).hexdigest()


def format_utc_timestamp(dt: Optional[datetime] = None) -> str:
    """
    Return *dt* formatted as an ISO 8601 UTC string (``YYYY-MM-DDTHH:MM:SSZ``).

    If *dt* is ``None``, the current UTC time is used.
    """
    if dt is None:
        dt = datetime.now(timezone.utc)
    # Ensure we always emit a UTC-normalised string regardless of input tz
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def truncate_text(text: str, max_chars: int = 160) -> str:
    """
    Truncate *text* to at most *max_chars* characters.

    If truncation is needed an ellipsis (``…``) replaces the last three
    characters so the total length never exceeds *max_chars*.
    """
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1] + "\u2026"


def normalize_phone_e164(phone: str) -> str:
    """
    Coerce a Ugandan phone number into E.164 format (``+256XXXXXXXXX``).

    Handles common formats:
    - 0700123456   → +256700123456
    - 256700123456 → +256700123456
    - +256700123456 → +256700123456 (unchanged)
    """
    phone = phone.strip().replace(" ", "").replace("-", "")
    if phone.startswith("+"):
        return phone
    if phone.startswith("256"):
        return f"+{phone}"
    if phone.startswith("0") and len(phone) == 10:
        return f"+256{phone[1:]}"
    return phone  # return as-is if we cannot determine the format
