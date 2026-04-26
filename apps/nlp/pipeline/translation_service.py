"""
Translation service with Redis caching and Azure fallback.

Translates text from any detected language into English for downstream
NLP processing. Uses Google Cloud Translation as primary with Azure
Cognitive Services as fallback. Results are cached in Redis.

Authentication for Google Cloud is handled via Application Default Credentials
or GOOGLE_APPLICATION_CREDENTIALS env variable. Azure uses AZURE_TRANSLATOR_KEY,
AZURE_TRANSLATOR_ENDPOINT, and AZURE_TRANSLATOR_REGION.
"""
from __future__ import annotations

import hashlib
import logging
from typing import Optional

logger = logging.getLogger(__name__)

_google_client = None
_azure_configured = False
_redis_client = None

_CACHE_TTL = 604800  # 7 days in seconds
_MAX_TEXT_LENGTH = 5000  # 5000 character limit for translations


def _get_google_client():
    global _google_client
    if _google_client is not None:
        return _google_client

    try:
        from google.cloud import translate_v2 as translate  # type: ignore[import]

        _google_client = translate.Client()
        logger.info("Google Cloud Translation client initialised.")
    except Exception:
        logger.exception(
            "Failed to initialise Google Cloud Translation client. "
            "Will fall back to Azure if configured."
        )
        _google_client = None

    return _google_client


def _get_redis_client():
    global _redis_client
    if _redis_client is not None:
        return _redis_client

    try:
        import redis

        _redis_client = redis.Redis(decode_responses=True)
        # Test connection
        _redis_client.ping()
        logger.info("Redis cache client connected.")
    except Exception:
        logger.warning("Redis cache unavailable. Translations will not be cached.")
        _redis_client = None

    return _redis_client


def _is_azure_configured() -> bool:
    """Check if Azure credentials are configured."""
    global _azure_configured
    if _azure_configured:
        return True

    import os

    key = os.environ.get("AZURE_TRANSLATOR_KEY")
    endpoint = os.environ.get("AZURE_TRANSLATOR_ENDPOINT")
    region = os.environ.get("AZURE_TRANSLATOR_REGION")

    _azure_configured = bool(key and endpoint and region)
    return _azure_configured


def _translate_with_azure(
    text: str, source_language: Optional[str] = None
) -> Optional[str]:
    """
    Translate using Azure Cognitive Services.

    Returns
    -------
    Translated text, or None if translation fails.
    """
    import os

    import requests  # type: ignore[import]

    key = os.environ.get("AZURE_TRANSLATOR_KEY")
    endpoint = os.environ.get("AZURE_TRANSLATOR_ENDPOINT")
    region = os.environ.get("AZURE_TRANSLATOR_REGION")

    if not (key and endpoint and region):
        return None

    try:
        url = f"{endpoint}/translate?api-version=3.0&from={source_language or ''}&to=en"
        headers = {
            "Ocp-Apim-Subscription-Key": key,
            "Ocp-Apim-Subscription-Region": region,
            "Content-Type": "application/json",
        }
        body = [{"Text": text}]

        response = requests.post(url, json=body, headers=headers, timeout=10)
        response.raise_for_status()

        result = response.json()
        if result and len(result) > 0:
            translated = result[0].get("translations", [{}])[0].get("text")
            if translated:
                logger.info("Azure translation successful.")
                return translated
    except Exception:
        logger.exception("Azure translation failed.")
        return None

    return None


def _make_cache_key(language: str, text: str) -> str:
    """Generate cache key from language + text hash."""
    combined = f"{language}:{text}"
    text_hash = hashlib.sha256(combined.encode()).hexdigest()
    return f"trans:{text_hash}"


def translate_to_english(
    text: str,
    source_language: Optional[str] = None,
    context: Optional[dict] = None,
) -> tuple[str, dict]:
    """
    Translate *text* to English with caching and fallback.

    Parameters
    ----------
    text:            The source text to translate.
    source_language: BCP 47 language code of the source, or ``None`` to
                     let the API auto-detect.
    context:         Optional dict to track translation_failed flag and feedback_id.

    Returns
    -------
    (translated_text, updated_context_dict)
        translated_text: English translation or original text if translation fails.
        updated_context_dict: Context with translation_failed flag set if needed.
    """
    if context is None:
        context = {}

    if source_language == "en":
        return text, context

    if not text or not text.strip():
        return text, context

    # Truncate if necessary
    if len(text) > _MAX_TEXT_LENGTH:
        feedback_id = context.get("feedback_id", "unknown")
        logger.warning(
            "Text truncated to %d chars. feedback_id=%s",
            _MAX_TEXT_LENGTH,
            feedback_id,
        )
        text = text[:_MAX_TEXT_LENGTH]

    # Check cache first
    cache_key = _make_cache_key(source_language or "", text)
    redis_client = _get_redis_client()
    if redis_client is not None:
        try:
            cached = redis_client.get(cache_key)
            if cached:
                logger.debug("Translation cache hit. key=%s", cache_key)
                return cached, context
            logger.debug("Translation cache miss. key=%s", cache_key)
        except Exception:
            logger.exception("Redis cache check failed.")

    # Try Google Cloud Translation
    google_client = _get_google_client()
    if google_client is not None:
        try:
            result = google_client.translate(
                text,
                target_language="en",
                source_language=source_language if source_language != "unknown" else None,
            )
            translated: str = result.get("translatedText", text)

            # Cache result
            if redis_client is not None:
                try:
                    redis_client.setex(cache_key, _CACHE_TTL, translated)
                    logger.debug("Translation cached. key=%s", cache_key)
                except Exception:
                    logger.exception("Failed to cache translation.")

            return translated, context
        except Exception:
            logger.warning("Google Cloud translation failed. Trying Azure fallback.")

    # Try Azure as fallback
    if _is_azure_configured():
        azure_result = _translate_with_azure(text, source_language)
        if azure_result:
            # Cache result
            if redis_client is not None:
                try:
                    redis_client.setex(cache_key, _CACHE_TTL, azure_result)
                except Exception:
                    logger.exception("Failed to cache Azure translation.")

            return azure_result, context

    # Both failed
    logger.error("Translation failed (both Google and Azure).")
    context["translation_failed"] = True
    return text, context


def detect_and_translate(text: str) -> tuple[str, str]:
    """
    Detect the source language *and* translate to English in one API call.

    Returns
    -------
    (detected_language, english_text)
    """
    google_client = _get_google_client()
    if google_client is None:
        return "unknown", text

    try:
        result = google_client.translate(text, target_language="en")
        detected = result.get("detectedSourceLanguage", "unknown")
        translated = result.get("translatedText", text)
        return detected, translated
    except Exception:
        logger.exception("Detect-and-translate failed.")
        return "unknown", text
