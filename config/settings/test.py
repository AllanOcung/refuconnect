"""
Test settings — fast, dependency-free, no external services required.

Overrides:
  - SQLite in-memory database  (no PostgreSQL needed)
  - LocMemCache                (no Redis needed)
  - Celery tasks run eagerly   (no broker needed)
  - Dummy africastalking creds (SDK initialises without real keys)
  - Dummy WhatsApp / phone-hash secrets for HMAC tests
  - PASSWORD_HASHERS: MD5 only (fast hashing in tests)
  - Email: in-memory backend
  - Logging: silent (no noise during test runs)
"""
from .base import *  # noqa: F401, F403

# ─── Database ─────────────────────────────────────────────────────────────────
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    }
}

# ─── Cache (in-process, no Redis) ─────────────────────────────────────────────
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "refuconnect-test",
    }
}

# ─── Celery — run tasks synchronously inside the test process ─────────────────
CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True

# ─── Password hashing — MD5 is fast enough for tests ─────────────────────────
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

# ─── Email ───────────────────────────────────────────────────────────────────
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"

# ─── Secrets / external service credentials (safe dummy values) ───────────────
SECRET_KEY = "test-secret-key-not-for-production"  # noqa: S105

AFRICAS_TALKING_API_KEY = "test-at-api-key"
AFRICAS_TALKING_USERNAME = "sandbox"
AT_API_KEY = "test-at-api-key"
SMS_SHORT_CODE = "20121"

WHATSAPP_APP_SECRET = "test-whatsapp-app-secret"
WHATSAPP_VERIFY_TOKEN = "test-verify-token"
WHATSAPP_ACCESS_TOKEN = "test-access-token"
WHATSAPP_PHONE_NUMBER_ID = "TEST_PHONE_ID"

PHONE_HASH_SALT = "test-phone-hash-salt"

ENCRYPTION_KEY = "dGVzdC1lbmNyeXB0aW9uLWtleS0zMi1ieXRlcy1sb25n"  # base64, 32 bytes

# ─── Media / static files ─────────────────────────────────────────────────────
import tempfile  # noqa: E402
MEDIA_ROOT = tempfile.mkdtemp()

# ─── Silence logging during tests ────────────────────────────────────────────
LOGGING = {
    "version": 1,
    "disable_existing_loggers": True,
    "handlers": {
        "null": {"class": "logging.NullHandler"},
    },
    "root": {
        "handlers": ["null"],
        "level": "CRITICAL",
    },
}

# ─── Throttling — disable for tests ──────────────────────────────────────────
REST_FRAMEWORK["DEFAULT_THROTTLE_CLASSES"] = []   # noqa: F405
REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"] = {}     # noqa: F405
