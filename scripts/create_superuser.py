#!/usr/bin/env python
"""
Non-interactive superuser creation from environment variables.

Required env vars:
    DJANGO_SUPERUSER_EMAIL
    DJANGO_SUPERUSER_PASSWORD
    DJANGO_SUPERUSER_FULL_NAME  (optional, defaults to "Super Admin")

Run: python scripts/create_superuser.py
"""
from __future__ import annotations

import os
import sys
import django

# ---------------------------------------------------------------------------
# Bootstrap Django
# ---------------------------------------------------------------------------
_BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _BASE_DIR)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.production")
django.setup()

from apps.dashboard.models import User  # noqa: E402


def main() -> None:
    email = os.environ.get("DJANGO_SUPERUSER_EMAIL", "").strip()
    password = os.environ.get("DJANGO_SUPERUSER_PASSWORD", "").strip()
    full_name = os.environ.get("DJANGO_SUPERUSER_FULL_NAME", "Super Admin").strip()

    if not email or not password:
        print(
            "ERROR: DJANGO_SUPERUSER_EMAIL and DJANGO_SUPERUSER_PASSWORD must be set.",
            file=sys.stderr,
        )
        sys.exit(1)

    if len(password) < 12:
        print("ERROR: Password must be at least 12 characters.", file=sys.stderr)
        sys.exit(1)

    if User.objects.filter(email=email).exists():
        print(f"Superuser '{email}' already exists. Skipping.")
        return

    user = User.objects.create_superuser(
        email=email,
        password=password,
        full_name=full_name,
    )
    user.role = User.Role.ADMINISTRATOR
    user.status = User.Status.ACTIVE
    user.save(update_fields=["role", "status"])
    print(f"Superuser '{email}' created successfully.")


if __name__ == "__main__":
    main()
