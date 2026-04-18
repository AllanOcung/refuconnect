"""
apps/nlp/pipeline/translation_service.py

Translates non-English Feedback to English using:
  Primary:  Google Cloud Translation API (via client library, ADC auth)
  Fallback: Azure Cognitive Services Translator (REST)

Results are cached in Redis (key: trans:{sha256(lang+text)}, TTL: 7 days).
"""
from __future__ import annotations

import hashlib
import logging
import uuid

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

_AZURE_KEY: str = getattr(settings, "AZURE_TRANSLATOR_KEY", "")
_AZURE_ENDPOINT: str = getattr(
    settings, "AZURE_TRANSLATOR_ENDPOINT", "https://api.cognitive.microsofttranslator.com"
)
_AZURE_REGION: str = getattr(settings, "AZURE_TRANSLATOR_REGION", "")
_CACHE_TTL: int = int(getattr(settings, "TRANSLATION_CACHE_TTL", 604800))  # 7 days
_MAX_CHARS: int = int(getattr(settings, "TRANSLATION_MAX_CHARS", 5000))
_REQUEST_TIMEOUT: int = 15


# ── Google Cloud client ───────────────────────────────────────────────────────

_google_client = None


def _get_google_client():
    global _google_client
    if _google_client is not None:
        return _google_client

    try:
        from google.cloud import translate_v2 as translate

        _google_client = translate.Client()
        logger.info("TranslationService: Google Cloud Translation client initialised.")
    except Exception as exc:
        logger.warning(
            "TranslationService: Google Cloud Translation client unavailable: %s", exc
        )
        _google_client = None

    return _google_client


# ── Cache ─────────────────────────────────────────────────────────────────────

def _cache_key(language: str, text: str) -> str:
    digest = hashlib.sha256(f"{language}{text}".encode()).hexdigest()
    return f"trans:{digest}"


def _get_redis():
    from django.core.cache import cache

    return cache


# ── Backend implementations ───────────────────────────────────────────────────

def _translate_google(text: str, source_lang: str) -> str:
    """
    Translate via Google Cloud Translation client library (ADC auth).
    Passing ``source_lang="unknown"`` lets the API auto-detect.
    Raises on any error so the caller can fall through to Azure.
    """
    client = _get_google_client()
    if client is None:
        raise RuntimeError("Google Cloud Translation client is not available.")

    result = client.translate(
        text,
        target_language="en",
        source_language=source_lang if source_lang != "unknown" else None,
    )
    translated = result.get("translatedText")
    if not translated:
        raise ValueError("Google Translate returned an empty translatedText.")
    return translated


def _translate_azure(text: str, source_lang: str) -> str:
    """
    Translate via Azure Cognitive Services Translator (REST).
    Raises on any error so the caller can mark translation_failed.
    """
    url = f"{_AZURE_ENDPOINT}/translate"
    params = {
        "api-version": "3.0",
        "from": source_lang if source_lang != "unknown" else None,
        "to": "en",
    }
    # Azure ignores None params, but filter explicitly to keep the URL clean.
    params = {k: v for k, v in params.items() if v is not None}
    headers = {
        "Ocp-Apim-Subscription-Key": _AZURE_KEY,
        "Ocp-Apim-Subscription-Region": _AZURE_REGION,
        "Content-Type": "application/json",
        "X-ClientTraceId": str(uuid.uuid4()),
    }
    response = requests.post(
        url,
        params=params,
        headers=headers,
        json=[{"text": text}],
        timeout=_REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    return response.json()[0]["translations"][0]["text"]


# ── Service class ─────────────────────────────────────────────────────────────

class TranslationService:
    """
    Translates ``Feedback.message_text`` → ``message_text_en`` (English).

    Usage:
        svc = TranslationService()
        record, context = svc.process(record, context)
    """

    def process(self, record, context: dict) -> tuple:
        """
        Translate the message if it is not already English.
        Mutates record in place; does NOT save.
        """
        feedback_id = record.pk
        language: str = record.language or "unknown"

        if language in ("en", "unknown", "", None):
            record.message_text_en = record.message_text
            logger.debug(
                "feedback_id=%s: no translation needed (language=%s).",
                feedback_id,
                language,
            )
            return record, context

        text: str = record.message_text or ""
        if not text.strip():
            record.message_text_en = text
            return record, context

        if len(text) > _MAX_CHARS:
            logger.warning(
                "feedback_id=%s: text truncated from %d to %d chars for translation.",
                feedback_id,
                len(text),
                _MAX_CHARS,
            )
            text = text[:_MAX_CHARS]

        cache = _get_redis()
        key = _cache_key(language, text)
        cached = cache.get(key)
        if cached:
            record.message_text_en = cached
            logger.debug("feedback_id=%s: translation cache hit.", feedback_id)
            return record, context

        translated: str | None = None
        google_exc: Exception | None = None

        try:
            translated = _translate_google(text, language)
            logger.debug("feedback_id=%s: translated via Google.", feedback_id)
        except Exception as exc:
            google_exc = exc
            logger.warning(
                "feedback_id=%s: Google Translate failed (%s); trying Azure.",
                feedback_id,
                exc,
            )

        if translated is None:
            try:
                translated = _translate_azure(text, language)
                logger.debug("feedback_id=%s: translated via Azure.", feedback_id)
            except Exception as azure_exc:
                logger.error(
                    "feedback_id=%s: both translation backends failed — "
                    "Google: %s | Azure: %s. Falling back to original text.",
                    feedback_id,
                    google_exc,
                    azure_exc,
                    exc_info=True,
                )
                record.message_text_en = record.message_text
                context["translation_failed"] = True
                return record, context

        cache.set(key, translated, timeout=_CACHE_TTL)
        record.message_text_en = translated
        return record, context
