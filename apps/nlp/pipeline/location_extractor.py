"""
Location extractor for Uganda-specific settlement and district names.

Uses a simple gazetteer lookup.  For higher precision a spaCy NER model
fine-tuned on Ugandan place names can replace this layer without changing
the interface.
"""
from __future__ import annotations

import re
from typing import Optional

# ── Ugandan refugee settlements and major districts ───────────────────────────

_GAZETTEER: list[str] = [
    # Refugee settlements
    "Nakivale", "Kyangwali", "Bidi Bidi", "Palabek", "Rhino Camp",
    "Adjumani", "Kiryandongo", "Obongi", "Rwamwanja", "Oruchinga",
    "Lobule", "Imvepi",
    # Districts
    "Kampala", "Gulu", "Lira", "Mbarara", "Jinja", "Fort Portal",
    "Arua", "Moroto", "Soroti", "Hoima", "Kabale", "Masaka",
    "Mukono", "Wakiso", "Mbale", "Tororo", "Iganga", "Bugiri",
    "Yumbe", "Moyo", "Zombo", "Nebbi", "Pakwach",
]

# Pre-compile a pattern for all gazetteer entries (case-insensitive)
_LOCATION_PATTERN = re.compile(
    r"\b(" + "|".join(re.escape(loc) for loc in _GAZETTEER) + r")\b",
    re.IGNORECASE,
)


def extract_location(text: str) -> Optional[str]:
    """
    Return the first recognised Ugandan location found in *text*, or ``None``.

    The returned string is title-cased to ensure consistent storage.
    """
    if not text:
        return None

    match = _LOCATION_PATTERN.search(text)
    if match:
        return match.group(0).title()

    return None
