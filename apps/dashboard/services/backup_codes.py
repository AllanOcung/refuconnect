"""
MFA backup-code helpers.

Codes are formatted as ``xxxx-xxxx`` (8 lowercase-hex characters split by a dash,
total 9 chars including the dash, 32 bits of entropy).  Plaintext is returned
to the user *exactly once* by the calling view; only the hash is persisted.

Stored hash uses Django's password hasher (PBKDF2 by default, or whatever's
configured) so timing-safe ``check_password`` comparisons work.
"""
from __future__ import annotations

import secrets
from typing import TYPE_CHECKING

from django.contrib.auth.hashers import check_password, make_password
from django.utils import timezone

if TYPE_CHECKING:
    from apps.dashboard.models import User


BACKUP_CODE_COUNT = 8


def _format_code(raw: str) -> str:
    """Take 8 hex chars and format as ``xxxx-xxxx``."""
    return f"{raw[:4]}-{raw[4:]}"


def generate_backup_codes(user: "User") -> list[str]:
    """
    Replace any existing backup codes for *user* with a fresh batch of 8.

    Returns the plaintext list — caller MUST show them to the user exactly
    once and never persist them in plaintext anywhere.
    """
    from apps.dashboard.models import BackupCode  # avoid circular import

    BackupCode.objects.filter(user=user).delete()

    plaintext: list[str] = []
    to_create: list[BackupCode] = []
    for _ in range(BACKUP_CODE_COUNT):
        raw_hex = secrets.token_hex(4)  # 8 hex chars
        code = _format_code(raw_hex)
        plaintext.append(code)
        to_create.append(BackupCode(user=user, code_hash=make_password(code)))
    BackupCode.objects.bulk_create(to_create)
    return plaintext


def consume_backup_code(user: "User", candidate: str) -> bool:
    """
    If *candidate* matches one of the user's unused codes, mark it used and
    return True.  Otherwise return False.

    Iterates user's unused codes — typically ≤ 8 rows per user so this is fine.
    """
    from apps.dashboard.models import BackupCode  # avoid circular import

    if not candidate:
        return False
    candidate = candidate.strip().lower()

    unused = BackupCode.objects.filter(user=user, used_at__isnull=True)
    for row in unused.iterator():
        if check_password(candidate, row.code_hash):
            row.used_at = timezone.now()
            row.save(update_fields=["used_at"])
            return True
    return False


def backup_code_stats(user: "User") -> dict:
    """Return ``{total, used, remaining, generated_at}`` for the user."""
    from apps.dashboard.models import BackupCode  # avoid circular import

    qs = BackupCode.objects.filter(user=user)
    total = qs.count()
    used = qs.filter(used_at__isnull=False).count()
    latest = qs.order_by("-created_at").first()
    return {
        "total": total,
        "used": used,
        "remaining": total - used,
        "generated_at": latest.created_at if latest else None,
    }


def clear_backup_codes(user: "User") -> int:
    """Delete every backup code for *user*. Returns the number removed."""
    from apps.dashboard.models import BackupCode  # avoid circular import

    deleted_count, _ = BackupCode.objects.filter(user=user).delete()
    return int(deleted_count)
