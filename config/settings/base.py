"""
Base Django settings for RefuConnect.
All environment-specific settings files import from this module.
"""
import os
from pathlib import Path

import dj_database_url

# ─── Paths ────────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent.parent.parent

# ─── Security ────────────────────────────────────────────────────────────────
SECRET_KEY = os.environ["SECRET_KEY"]
DEBUG = False
ALLOWED_HOSTS: list[str] = []

# ─── Application definition ──────────────────────────────────────────────────
DJANGO_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.postgres",
]

THIRD_PARTY_APPS = [
    "rest_framework",
    "rest_framework_simplejwt",
    "rest_framework_simplejwt.token_blacklist",
    "corsheaders",
    "django_filters",
    "django_celery_beat",
]

LOCAL_APPS = [
    "apps.common",
    "apps.dashboard",
    "apps.feedback",
    "apps.nlp",
    "apps.notifications",
]

INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

# ─── Custom user model ───────────────────────────────────────────────────────
AUTH_USER_MODEL = "dashboard.User"

# ─── Database ────────────────────────────────────────────────────────────────
DATABASES = {
    "default": dj_database_url.config(
        env="DATABASE_URL",
        conn_max_age=600,
        conn_health_checks=True,
    )
}
DEFAULT_AUTO_FIELD = "django.db.models.AutoField"

# ─── Cache (Redis) ───────────────────────────────────────────────────────────
CACHES = {
    "default": {
        "BACKEND": "django_redis.cache.RedisCache",
        "LOCATION": os.environ.get("REDIS_URL", "redis://redis:6379/0"),
        "OPTIONS": {
            "CLIENT_CLASS": "django_redis.client.DefaultClient",
            "SOCKET_CONNECT_TIMEOUT": 5,
            "SOCKET_TIMEOUT": 5,
        },
    }
}

# ─── Password hashing (bcrypt first) ─────────────────────────────────────────
PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.BCryptSHA256PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2SHA1PasswordHasher",
    "django.contrib.auth.hashers.Argon2PasswordHasher",
]

# ─── Internationalization ────────────────────────────────────────────────────
LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

# ─── Static / Media ──────────────────────────────────────────────────────────
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"

MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

# ─── REST Framework ──────────────────────────────────────────────────────────
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "DEFAULT_PAGINATION_CLASS": "apps.dashboard.pagination.StandardResultsPagination",
    "PAGE_SIZE": 25,
    "DEFAULT_FILTER_BACKENDS": [
        "django_filters.rest_framework.DjangoFilterBackend",
        "rest_framework.filters.SearchFilter",
        "rest_framework.filters.OrderingFilter",
    ],
    "DEFAULT_RENDERER_CLASSES": [
        "rest_framework.renderers.JSONRenderer",
    ],
    "DEFAULT_THROTTLE_CLASSES": [
        "rest_framework.throttling.AnonRateThrottle",
        "rest_framework.throttling.UserRateThrottle",
    ],
    "DEFAULT_THROTTLE_RATES": {
        "anon": "60/minute",
        "user": "300/minute",
    },
    "EXCEPTION_HANDLER": "apps.common.exceptions.custom_exception_handler",
}

# ─── JWT ─────────────────────────────────────────────────────────────────────
from datetime import timedelta

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(hours=1),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=7),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
    "ALGORITHM": "HS256",
    "AUTH_HEADER_TYPES": ("Bearer",),
    "USER_ID_FIELD": "user_id",
    "USER_ID_CLAIM": "user_id",
}

# ─── Celery ──────────────────────────────────────────────────────────────────
CELERY_BROKER_URL = os.environ.get("CELERY_BROKER_URL", "redis://redis:6379/0")
CELERY_RESULT_BACKEND = os.environ.get("CELERY_RESULT_BACKEND", "redis://redis:6379/1")
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_TIMEZONE = "UTC"
CELERY_TASK_TRACK_STARTED = True
CELERY_TASK_TIME_LIMIT = 1200         # 20 minutes hard limit (allows first-time HF model download)
CELERY_TASK_SOFT_TIME_LIMIT = 1140    # 19 minutes soft limit
CELERY_WORKER_PREFETCH_MULTIPLIER = 1
CELERY_BEAT_SCHEDULER = "django_celery_beat.schedulers:DatabaseScheduler"

# ─── Encryption ──────────────────────────────────────────────────────────────
ENCRYPTION_KEY = os.environ.get("ENCRYPTION_KEY", "")

# ─── External API keys ───────────────────────────────────────────────────────
GOOGLE_TRANSLATE_API_KEY = os.environ.get("GOOGLE_TRANSLATE_API_KEY", "")
AFRICAS_TALKING_API_KEY = os.environ.get("AFRICAS_TALKING_API_KEY", "")
AFRICAS_TALKING_USERNAME = os.environ.get("AFRICAS_TALKING_USERNAME", "sandbox")
SMS_SHORT_CODE = os.environ.get("SMS_SHORT_CODE", "")
USSD_SHORT_CODE = os.environ.get("USSD_SHORT_CODE", "")
WHATSAPP_ACCESS_TOKEN = os.environ.get("WHATSAPP_ACCESS_TOKEN", "")
WHATSAPP_PHONE_NUMBER_ID = os.environ.get("WHATSAPP_PHONE_NUMBER_ID", "")
WHATSAPP_VERIFY_TOKEN = os.environ.get("WHATSAPP_VERIFY_TOKEN", "")
WHATSAPP_APP_SECRET = os.environ.get("WHATSAPP_APP_SECRET", "")

# ─── Phone anonymisation ──────────────────────────────────────────────────────
# Salt used when hashing phone numbers to produce anonymous_user_id values.
# Must be set in production via environment variable.
PHONE_HASH_SALT = os.environ.get("PHONE_HASH_SALT", "")

# Alias so adapters can try AT_API_KEY first (shorter env var name)
AT_API_KEY = os.environ.get("AT_API_KEY", AFRICAS_TALKING_API_KEY)

# Skip SMS signature verification (useful for sandbox/local testing)
AT_SKIP_SMS_SIGNATURE = os.environ.get("AT_SKIP_SMS_SIGNATURE", "").lower() in ("true", "1", "yes")

# ─── AI model paths ──────────────────────────────────────────────────────────
FASTTEXT_MODEL_PATH = os.environ.get("FASTTEXT_MODEL_PATH", str(BASE_DIR / "models" / "lid.176.bin"))
AFROLID_MODEL_PATH = os.environ.get("AFROLID_MODEL_PATH", str(BASE_DIR / "models" / "afrolid"))
# Optional external AfroLID microservice URL (e.g. http://afrolid:8000)
AFROLID_SERVICE_URL = os.environ.get("AFROLID_SERVICE_URL", "")

# Ensure HuggingFace cache paths are exported before transformers/huggingface_hub import.
HUGGINGFACE_CACHE_DIR = os.environ.get(
    "HUGGINGFACE_CACHE_DIR", str(BASE_DIR / "models" / "huggingface")
)
os.environ.setdefault("HF_HOME", HUGGINGFACE_CACHE_DIR)
os.environ.setdefault("TRANSFORMERS_CACHE", HUGGINGFACE_CACHE_DIR)
os.environ.setdefault(
    "HUGGINGFACE_HUB_CACHE", os.path.join(HUGGINGFACE_CACHE_DIR, "hub")
)

# ─── Language Detection Thresholds ───────────────────────────────────────────
# Per-language confidence thresholds for language detection
LANGUAGE_CONFIDENCE_THRESHOLDS = {
    "en": 0.85,  # English
    "sw": 0.85,  # Swahili
}

# Minimum confidence required to proceed with translation
LANGUAGE_CONFIDENCE_THRESHOLD_TRANSLATION = 0.75

# Always translate these languages even when confidence is below threshold.
LANGUAGES_ALWAYS_TRANSLATE = ("sw",)

# ─── Logging ─────────────────────────────────────────────────────────────────
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "{levelname} {asctime} {module} {process:d} {thread:d} {message}",
            "style": "{",
        },
        "simple": {
            "format": "{levelname} {message}",
            "style": "{",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "verbose",
        },
    },
    "root": {
        "handlers": ["console"],
        "level": "INFO",
    },
    "loggers": {
        "django": {
            "handlers": ["console"],
            "level": "INFO",
            "propagate": False,
        },
        "apps": {
            "handlers": ["console"],
            "level": "DEBUG",
            "propagate": False,
        },
        "celery": {
            "handlers": ["console"],
            "level": "INFO",
            "propagate": False,
        },
    },
}
