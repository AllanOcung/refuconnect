"""
Google Cloud Translation service.

Translates text from any detected language into English for downstream
NLP processing.  Authentication is handled by the Google Cloud client
library via Application Default Credentials or the GOOGLE_APPLICATION_CREDENTIALS
env variable.
"""
from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)

_client = None


def _get_client():
    global _client
    if _client is not None:
        return _client

    try:
        from google.cloud import translate_v2 as translate  # type: ignore[import]

        _client = translate.Client()
        logger.info("Google Cloud Translation client initialised.")
    except Exception:
        logger.exception(
            "Failed to initialise Google Cloud Translation client. "
            "Translation will be skipped."
        )
        _client = None

    return _client


def translate_to_english(text: str, source_language: Optional[str] = None) -> str:
    """
    Translate *text* to English.

    Parameters
    ----------
    text:            The source text to translate.
    source_language: BCP 47 language code of the source, or ``None`` to
                     let the API auto-detect.

    Returns
    -------
    The translated English text.  Returns the original *text* unchanged if
    translation is unavailable or the source is already English.
    """
    if source_language == "en":
        return text

    client = _get_client()
    if client is None:
        logger.warning("Translation skipped — client unavailable.")
        return text

    if not text or not text.strip():
        return text

    try:
        result = client.translate(
            text,
            target_language="en",
            source_language=source_language if source_language != "unknown" else None,
        )
        translated: str = result.get("translatedText", text)
        return translated
    except Exception:
        logger.exception("Translation failed.")
        return text


def detect_and_translate(text: str) -> tuple[str, str]:
    """
    Detect the source language *and* translate to English in one API call.

    Returns
    -------
    (detected_language, english_text)
    """
    client = _get_client()
    if client is None:
        return "unknown", text

    try:
        result = client.translate(text, target_language="en")
        detected = result.get("detectedSourceLanguage", "unknown")
        translated = result.get("translatedText", text)
        return detected, translated
    except Exception:
        logger.exception("Detect-and-translate failed.")
        return "unknown", text
