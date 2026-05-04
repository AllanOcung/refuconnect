"""
Translation service with HuggingFace Helsinki-NLP/opus-mt models and Redis caching.

Translates text from any detected language into English for downstream
NLP processing. Uses Helsinki-NLP/opus-mt models for offline, credential-free
translation. Results are cached in Redis.

Model selection:
  sw (Swahili) → Helsinki-NLP/opus-mt-sw-en
  others       → Helsinki-NLP/opus-mt-mul-en

Set HUGGINGFACE_CACHE_DIR to control where model weights are stored.
"""
from __future__ import annotations

import hashlib
import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

_redis_client = None
_translation_pipelines: dict = {}

_CACHE_TTL = 604800  # 7 days in seconds
_MAX_TEXT_LENGTH = 5000  # 5000 character limit for translations

# Model registry: maps language code → HuggingFace model name
_MODEL_REGISTRY = {
    # swc = Congo Swahili (ISO 639-3) — covers standard Swahili (sw)
    "sw": "Helsinki-NLP/opus-mt-swc-en",
}
_FALLBACK_MODEL = "Helsinki-NLP/opus-mt-mul-en"


def _get_model_name(source_language: Optional[str]) -> str:
    """Return the appropriate HuggingFace model for the given source language."""
    if source_language and source_language not in ("unknown", "other"):
        return _MODEL_REGISTRY.get(source_language, _FALLBACK_MODEL)
    return _FALLBACK_MODEL


def _get_translation_pipeline(source_language: Optional[str]):
    """Load and cache a HuggingFace translation pipeline for the given language."""
    global _translation_pipelines

    model_name = _get_model_name(source_language)

    if model_name in _translation_pipelines:
        return _translation_pipelines[model_name]

    try:
        cache_dir = os.environ.get("HUGGINGFACE_CACHE_DIR", None)
        if cache_dir:
            os.makedirs(cache_dir, exist_ok=True)
            os.environ["HF_HOME"] = cache_dir
            os.environ["HUGGINGFACE_HUB_CACHE"] = os.path.join(cache_dir, "hub")
            os.environ["TRANSFORMERS_CACHE"] = cache_dir

        from transformers import pipeline  # type: ignore[import]

        pipe = pipeline("translation", model=model_name)
        _translation_pipelines[model_name] = pipe
        logger.info("HuggingFace translation pipeline loaded. model=%s", model_name)
        return pipe
    except Exception:
        logger.exception(
            "Failed to load HuggingFace translation pipeline. model=%s", model_name
        )
        _translation_pipelines[model_name] = None
        return None


def _get_redis_client():
    global _redis_client
    if _redis_client is not None:
        return _redis_client

    try:
        import redis

        redis_url = os.environ.get("REDIS_URL", "redis://redis:6379/0")
        _redis_client = redis.Redis.from_url(redis_url, decode_responses=True)
        # Test connection
        _redis_client.ping()
        logger.info("Redis cache client connected. url=%s", redis_url)
    except Exception:
        logger.warning("Redis cache unavailable. Translations will not be cached.")
        _redis_client = None

    return _redis_client


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
    Translate *text* to English with caching.

    Parameters
    ----------
    text:            The source text to translate.
    source_language: BCP 47 language code of the source, or ``None`` to
                     skip translation (language not detected).
    context:         Optional dict to track translation_failed flag and feedback_id.

    Returns
    -------
    (translated_text, updated_context_dict)
        translated_text: English translation or original text if translation fails.
        updated_context_dict: Context with translation_failed flag set if needed.
    """
    if context is None:
        context = {}

    # C-07: if language is English OR missing, keep original text.
    if source_language in ("en", None):
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

    # Translate with HuggingFace
    pipe = _get_translation_pipeline(source_language)
    if pipe is not None:
        try:
            output = pipe(text)
            translated: str = output[0].get("translation_text", text)

            # Cache result
            if redis_client is not None:
                try:
                    redis_client.setex(cache_key, _CACHE_TTL, translated)
                    logger.debug("Translation cached. key=%s", cache_key)
                except Exception:
                    logger.exception("Failed to cache translation.")

            return translated, context
        except Exception:
            logger.exception("HuggingFace translation failed.")

    # Translation failed
    feedback_id = context.get("feedback_id", "unknown")
    logger.error("Translation failed. feedback_id=%s", feedback_id)
    context["translation_failed"] = True
    return text, context


def detect_and_translate(text: str) -> tuple[str, str]:
    """
    Translate text to English using the multilingual fallback model.

    Language detection is handled separately by LanguageDetector.
    This function exists for backward compatibility.

    Returns
    -------
    ('unknown', english_text)
    """
    translated, _ = translate_to_english(text, source_language="unknown")
    return "unknown", translated
