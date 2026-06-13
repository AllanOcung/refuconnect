"""
Shared location options for guided incident-location capture.

Single source of truth for the settlement/district list and the helpers that
build the selection menu (SMS/WhatsApp/USSD) and resolve a user's reply into a
canonical location value.

All three channel adapters and the normaliser import from here so the option
list never drifts between channels.
"""
from __future__ import annotations

# ── Canonical settlement / district list ──────────────────────────────────────
# Order is significant: the 1-based index is the menu number shown to users and
# the digit they reply with.  "Other district" is the catch-all sentinel.
LOCATION_OPTIONS: list[str] = [
    "Nakivale", "Kyangwali", "Bidi Bidi", "Palabek",
    "Rhino Camp", "Adjumani", "Kiryandongo", "Obongi",
    "Rwamwanja", "Kampala", "Other district",
]

_OTHER = "Other district"
_OTHER_SW = "Wilaya nyingine"


def build_location_menu(language: str = "en") -> str:
    """
    Build the numbered location menu for SMS/WhatsApp, localized en/sw.

    Parameters
    ----------
    language: ISO 639-1 code; 'sw' renders Swahili, anything else renders English.

    Returns
    -------
    str  A header line followed by one numbered option per line.
    """
    if language == "sw":
        header = "Tukio lilitokea wapi? Jibu kwa nambari:"

        def label(name: str) -> str:
            return _OTHER_SW if name == _OTHER else name
    else:
        header = "Where did this happen? Reply with the number:"

        def label(name: str) -> str:
            return name

    lines = [f"{i + 1}. {label(name)}" for i, name in enumerate(LOCATION_OPTIONS)]
    return header + "\n" + "\n".join(lines)


def resolve_location_reply(body: str) -> tuple[bool, str | None]:
    """
    Map a free-form reply to a location selection.

    Accepts a 1-based menu digit or an exact (case-insensitive) settlement name,
    including the Swahili alias for "Other district".  Anything else is treated
    as a non-selection so the caller can fall through to new-feedback creation.

    The canonical English name is always returned for a match — including the
    literal ``"Other district"`` for option 11 (so the field is never left empty
    when the user explicitly made a choice).  The Swahili alias resolves to the
    same canonical ``"Other district"`` string.

    Parameters
    ----------
    body: Raw reply text from the sender.

    Returns
    -------
    tuple[bool, str | None]
        ``(matched, value)`` where:
          - ``matched=True, value=<canonical name>``  for any valid selection,
          - ``matched=False, value=None``             when the reply is not a selection.
    """
    text = body.strip()

    # Numeric selection (1-based index into LOCATION_OPTIONS)
    if text.isdigit():
        idx = int(text) - 1
        if 0 <= idx < len(LOCATION_OPTIONS):
            return True, LOCATION_OPTIONS[idx]
        return False, None

    # Exact name match (case-insensitive), incl. the SW alias for "Other district"
    low = text.lower()
    if low in (_OTHER_SW.lower(), _OTHER.lower()):
        return True, _OTHER
    for name in LOCATION_OPTIONS:
        if low == name.lower():
            return True, name

    return False, None
