"""
Location extractor for Uganda-specific settlement and district names.

Uses a 3-pass extraction strategy:
  - Pass 1: Gazetteer lookup (settlements and districts)
  - Pass 2: Zone/Block regex extraction
  - Pass 3: spaCy NER fine-tuned model (if available)

Supports aliases and fuzzy matching for settlement name variations.
"""
from __future__ import annotations

import logging
import re
from typing import Optional

logger = logging.getLogger(__name__)

_spacy_model = None

# ── Ugandan refugee settlements and major districts ───────────────────────────

_GAZETTEER: list[str] = [
    # Refugee settlements
    "Nakivale",
    "Kyangwali",
    "Bidi Bidi",
    "Palabek",
    "Rhino Camp",
    "Adjumani",
    "Kiryandongo",
    "Obongi",
    "Rwamwanja",
    "Oruchinga",
    "Lobule",
    "Imvepi",
    # Districts
    "Kampala",
    "Gulu",
    "Lira",
    "Mbarara",
    "Jinja",
    "Fort Portal",
    "Arua",
    "Moroto",
    "Soroti",
    "Hoima",
    "Kabale",
    "Masaka",
    "Mukono",
    "Wakiso",
    "Mbale",
    "Tororo",
    "Iganga",
    "Bugiri",
    "Yumbe",
    "Moyo",
    "Zombo",
    "Nebbi",
    "Pakwach",
]

# Aliases for settlements (variations)
_SETTLEMENT_ALIASES: dict[str, list[str]] = {
    "Nakivale": ["Nakivale Settlement", "NKV", "Nakivale Camp"],
    "Kyangwali": ["Kyangwali Settlement", "KYG", "Kyangwali Camp"],
    "Bidi Bidi": ["Bidi Bidi Settlement", "BDB", "Bidi-Bidi"],
    "Rhino Camp": ["Rhino Camp Settlement", "RHC", "Rhino"],
    "Adjumani": ["Adjumani Settlement", "ADJ"],
    "Kiryandongo": ["Kiryandongo Settlement", "KIR"],
    "Rwamwanja": ["Rwamwanja Settlement", "RWA"],
    "Imvepi": ["Imvepi Settlement", "IMP"],
    "Palabek": ["Palabek Settlement", "PAL"],
}

# Pre-compile gazetteer pattern
_GAZETTEER_PATTERN = re.compile(
    r"\b(" + "|".join(re.escape(loc) for loc in _GAZETTEER) + r")\b",
    re.IGNORECASE,
)

# Zone and Block patterns
_ZONE_BLOCK_PATTERN = re.compile(
    r"\b(Zone\s+[0-9A-Za-z]+|Block\s+[0-9A-Za-z]+|Cell\s+[0-9A-Za-z]+)\b",
    re.IGNORECASE,
)


def _get_spacy_model():
    """Load spaCy model lazily."""
    global _spacy_model
    if _spacy_model is not None:
        return _spacy_model

    try:
        import spacy  # type: ignore[import]

        _spacy_model = spacy.load("en_core_web_sm")
        logger.info("spaCy NER model loaded: en_core_web_sm")
    except Exception:
        logger.warning("spaCy NER model not available. Using gazetteer + regex fallback.")
        _spacy_model = None

    return _spacy_model


def _fuzzy_match_settlement(text: str) -> Optional[str]:
    """
    Try to match settlement using aliases and fuzzy matching.

    Returns canonical settlement name if found, else None.
    """
    text_lower = text.lower().strip()

    # Try exact match first (settlement name)
    for settlement in _SETTLEMENT_ALIASES.keys():
        if text_lower == settlement.lower():
            return settlement

    # Try exact alias match
    for settlement, aliases in _SETTLEMENT_ALIASES.items():
        for alias in aliases:
            if alias.lower() == text_lower:
                return settlement

    # Try substring matching only for longer aliases (5+ chars)
    # Short acronyms like "PAL", "NKV" should only match exactly
    for settlement, aliases in _SETTLEMENT_ALIASES.items():
        for alias in aliases:
            if len(alias) >= 5:  # Only substring match for longer aliases
                if text_lower in alias.lower() or alias.lower() in text_lower:
                    return settlement

    return None


def _extract_zones_from_text(text: str) -> Optional[str]:
    """
    Extract zone/block/cell patterns from text.

    Returns formatted zone string, e.g., "Zone 1" or "Block A".
    """
    if not text:
        return None

    match = _ZONE_BLOCK_PATTERN.search(text)
    if match:
        zone_text = match.group(0)
        # Normalize capitalization
        parts = zone_text.split()
        if len(parts) >= 2:
            return f"{parts[0].capitalize()} {' '.join(parts[1:])}"
        return zone_text.title()

    return None


def _extract_with_spacy(text: str) -> Optional[str]:
    """
    Use spaCy NER to extract locations.

    Returns location string or None.
    """
    model = _get_spacy_model()
    if model is None:
        return None

    try:
        doc = model(text[:512])  # Limit to 512 chars for efficiency
        for ent in doc.ents:
            if ent.label_ in ("LOCATION", "ORG", "FACILITY", "GPE"):
                return ent.text
    except Exception:
        logger.exception("spaCy NER extraction failed.")

    return None


def extract_location(text: str) -> tuple[Optional[str], float, str]:
    """
    Extract location from text using 3-pass strategy.

    Parameters
    ----------
    text: The text to extract location from.

    Returns
    -------
    (location_string or None, confidence: float, location_type: str)
        location_string: Formatted location (e.g., "Nakivale, Zone 1") or None
        confidence: Confidence score [0, 1]
        location_type: "settlement", "zone", or "unknown"
    """
    if not text:
        return None, 0.0, "unknown"

    settlement = None
    zone = None

    # Pass 1: Gazetteer lookup
    match = _GAZETTEER_PATTERN.search(text)
    if match:
        found_name = match.group(0)
        # Normalize to canonical name
        settlement = _fuzzy_match_settlement(found_name) or found_name.title()

    # Pass 2: Zone/Block extraction
    zone = _extract_zones_from_text(text)

    # Pass 3: spaCy NER (only if no settlement found yet)
    if not settlement:
        spacy_location = _extract_with_spacy(text)
        if spacy_location and spacy_location not in [settlement, zone]:
            settlement = spacy_location

    # Format result
    if settlement and zone:
        return f"{settlement}, {zone}", 0.95, "settlement"
    elif settlement:
        return settlement, 0.90, "settlement"
    elif zone:
        return zone, 0.80, "zone"

    return None, 0.0, "unknown"
