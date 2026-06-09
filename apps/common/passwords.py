"""
Shared password-policy validator.

Rule (mirrored on the frontend):
  - at least 8 characters
  - at least one digit
  - at least one non-alphanumeric symbol
"""
from __future__ import annotations

import re

MIN_LENGTH = 8
PASSWORD_POLICY_DETAIL = (
    "Password must be at least 8 characters and include a number and special character."
)


def is_password_valid(password: str) -> bool:
    """Return True when *password* satisfies the RefuConnect policy."""
    if not isinstance(password, str):
        return False
    return (
        len(password) >= MIN_LENGTH
        and re.search(r"\d", password) is not None
        and re.search(r"[^A-Za-z0-9]", password) is not None
    )
