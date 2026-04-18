from __future__ import annotations

import logging
import re

import spacy

logger = logging.getLogger(__name__)

#  Gazetteer 

SETTLEMENTS: dict[str, dict] = {
    "bidibidi": {
        "canonical": "Bidibidi",
        "district": "Yumbe",
        "aliases": ["bidi bidi", "bidi-bidi"],
    },
    "nakivale": {
        "canonical": "Nakivale",
        "district": "Isingiro",
        "aliases": [],
    },
    "kyangwali": {
        "canonical": "Kyangwali",
        "district": "Kikuube",
        "aliases": [],
    },
    "kiryandongo": {
        "canonical": "Kiryandongo",
        "district": "Kiryandongo",
        "aliases": ["kirya"],
    },
    "pagirinya": {
        "canonical": "Pagirinya",
        "district": "Adjumani",
        "aliases": [],
    },
    "rhino": {
        "canonical": "Rhino Camp",
        "district": "Arua",
        "aliases": ["rhino camp"],
    },
    "adjumani": {
        "canonical": "Adjumani",
        "district": "Adjumani",
        "aliases": [],
    },
    "obongi": {
        "canonical": "Obongi",
        "district": "Obongi",
        "aliases": [],
    },
    "rwamwanja": {
        "canonical": "Rwamwanja",
        "district": "Kamwenge",
        "aliases": [],
    },
    "kampala": {
        "canonical": "Kampala",
        "district": "Kampala",
        "aliases": ["city", "urban"],
    },
    "kyaka": {
        "canonical": "Kyaka II",
        "district": "Kyegegwa",
        "aliases": ["kyaka 2", "kyaka ii"],
    },
    "oruchinga": {
        "canonical": "Oruchinga",
        "district": "Isingiro",
        "aliases": [],
    },
    "palabek": {
        "canonical": "Palabek",
        "district": "Lamwo",
        "aliases": [],
    },
    "lobule": {
        "canonical": "Lobule",
        "district": "Koboko",
        "aliases": [],
    },
    "imvepi": {
        "canonical": "Imvepi",
        "district": "Terego",
        "aliases": [],
    },
    "gulu": {
        "canonical": "Gulu",
        "district": "Gulu",
        "aliases": [],
    },
    "lira": {
        "canonical": "Lira",
        "district": "Lira",
        "aliases": [],
    },
    "mbarara": {
        "canonical": "Mbarara",
        "district": "Mbarara",
        "aliases": [],
    },
    "arua": {
        "canonical": "Arua",
        "district": "Arua",
        "aliases": [],
    },
    "yumbe": {
        "canonical": "Yumbe",
        "district": "Yumbe",
        "aliases": [],
    },
    "moyo": {
        "canonical": "Moyo",
        "district": "Moyo",
        "aliases": [],
    },
}

# Flat lookup: any key or alias (lowercased) → canonical name.
# Built once at module load; sorted by length descending for longest-match priority.
_LOOKUP: dict[str, str] = {}
for _key, _meta in SETTLEMENTS.items():
    _LOOKUP[_key] = _meta["canonical"]
    for _alias in _meta["aliases"]:
        _LOOKUP[_alias.lower()] = _meta["canonical"]

_LOOKUP_KEYS_SORTED: list[str] = sorted(_LOOKUP, key=len, reverse=True)

# Zone/block regex 

_ZONE_RE = re.compile(r"\b(zone|block|section)\s*([a-z0-9]+)\b", re.IGNORECASE)

#  spaCy 

_NLP = None


def _get_spacy() -> spacy.language.Language:
    global _NLP
    if _NLP is None:
        logger.info("Loading spaCy model en_core_web_sm.")
        try:
            _NLP = spacy.load("en_core_web_sm")
        except OSError:
            logger.error(
                "spaCy model 'en_core_web_sm' not found. "
                "Run: python -m spacy download en_core_web_sm"
            )
            raise
    return _NLP


#  Helpers 

def _gazetteer_match(text: str) -> str | None:
    """Return the canonical settlement name for the first (longest) match in *text*."""
    lower = text.lower()
    for key in _LOOKUP_KEYS_SORTED:
        if re.search(r"\b" + re.escape(key) + r"\b", lower):
            return _LOOKUP[key]
    return None


def _zone_match(text: str) -> str | None:
    """Return a normalised zone string (e.g. 'Zone 3', 'Block A') or ``None``."""
    m = _ZONE_RE.search(text)
    if not m:
        return None
    zone_type = m.group(1).capitalize()
    zone_id = m.group(2).upper() if m.group(2).isalpha() else m.group(2)
    return f"{zone_type} {zone_id}"


#  Extractor class 

class LocationExtractor:
    

    def __init__(self) -> None:
        _get_spacy()  # fail fast if the model is missing

    def process(self, record, context: dict) -> tuple:
        
        feedback_id = record.pk
        text: str = record.message_text_en or record.message_text or ""

        if not text:
            return record, context

        # Pass 1 – Gazetteer
        settlement = _gazetteer_match(text)

        # Pass 2 – Zone/block regex
        zone = _zone_match(text)

        # Pass 3 – spaCy NER (only when gazetteer found nothing)
        if not settlement:
            try:
                doc = _get_spacy()(text)
                for ent in doc.ents:
                    if ent.label_ == "GPE":
                        matched = _gazetteer_match(ent.text)
                        if matched:
                            settlement = matched
                            break
            except Exception as exc:
                logger.warning(
                    "feedback_id=%s: spaCy NER failed: %s", feedback_id, exc
                )

        if settlement and zone:
            record.location = f"{settlement}, {zone}"
        elif settlement:
            record.location = settlement
        else:
            record.location = None

        logger.debug("feedback_id=%s: location=%s", feedback_id, record.location)
        return record, context
