import os
from pathlib import Path
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent.parent.parent / '.env')
except ImportError:
    pass

"""Development settings — DEBUG on, relaxed security, console email."""
import os

from .base import *  # noqa: F401, F403

DEBUG = True
SECRET_KEY = os.environ.get(
    "SECRET_KEY",
    "dev-insecure-secret-key-do-not-use-in-production-ever",
)
ALLOWED_HOSTS = ["*"]

# ─── CORS ────────────────────────────────────────────────────────────────────
CORS_ALLOW_ALL_ORIGINS = True

# ─── Email ───────────────────────────────────────────────────────────────────
# EMAIL_* config is read from env via base.py.
# Set EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend in .env to use real SMTP
# in development; otherwise the base default (console) keeps messages out of inboxes.

# ─── Debug toolbar ───────────────────────────────────────────────────────────
try:
    import debug_toolbar  # noqa: F401

    INSTALLED_APPS += ["debug_toolbar"]  # noqa: F405
    MIDDLEWARE.insert(0, "debug_toolbar.middleware.DebugToolbarMiddleware")  # noqa: F405
    INTERNAL_IPS = ["127.0.0.1"]
except ImportError:
    pass

# ─── Django extensions ───────────────────────────────────────────────────────
try:
    import django_extensions  # noqa: F401

    INSTALLED_APPS += ["django_extensions"]  # noqa: F405
except ImportError:
    pass

# ─── Throttling relaxed for dev ──────────────────────────────────────────────
REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"] = {  # noqa: F405
    "anon": "10000/minute",
    "user": "10000/minute",
    "login": "10000/minute",
    "password_reset": "10000/minute",
    "accept_invite": "10000/minute",
}

# ─── Show full errors ────────────────────────────────────────────────────────
LOGGING["root"]["level"] = "DEBUG"  # noqa: F405

