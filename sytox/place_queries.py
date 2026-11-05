"""Small, privacy-conscious helpers for offering Instant Street View links.

Only the user choosing to load/open a view causes network access; phrase
recognition alone never calls an external service.
"""
from __future__ import annotations

import re
from urllib.parse import quote

_BASE_URL = "https://www.instantstreetview.com/s/"
_PLACE_RULES = (
    r"(?:wofuer|wofür|für was)\s+ist\s+(?P<place>.+?)\s+bekannt",
    r"(?:wie\s+sieht|wie\s+schaut)\s+(?P<place>.+?)\s+aus",
    r"(?:wo\s+liegt|wo\s+befindet\s+sich)\s+(?P<place>.+)",
    r"(?:erzähl(?:e)?\s+(?:mir\s+)?(?:etwas\s+)?über|was\s+weißt\s+du\s+über|"
    r"informationen\s+(?:über|zu)|infos?\s+über)\s+(?P<place>.+)",
    r"(?:zeige?|öffne)\s+(?:mir\s+)?(?:den\s+|die\s+|das\s+)?"
    r"(?:street\s*view|straßenansicht)\s+(?:von\s+|für\s+|in\s+)?(?P<place>.+)",
    r"(?:street\s*view|straßenansicht)\s+(?:von|für|in)\s+(?P<place>.+)",
)


def normalize_place(place: str) -> str:
    """Strip casual punctuation, but preserve international street names."""
    text = " ".join(str(place).strip().split())
    text = re.sub(r"[.!?;]+$", "", text).strip()
    return text


def place_from_message(message: str) -> str | None:
    """Conservative on-device hint, never an automatic web lookup.

    Only fairly explicit location prompts are recognized. Other addresses can
    always be pasted into the sidebar manually.
    """
    text = " ".join(str(message).strip().split())
    if len(text) > 280:
        return None
    for rule in _PLACE_RULES:
        match = re.search(r"(?i)(?:^|[.!?]\s+)" + rule + r"\s*[.!?]*$", text)
        if match:
            candidate = normalize_place(match.group("place"))
            if 2 <= len(candidate) <= 150 and not re.search(
                r"\b(?:passwort|password|api[_ -]?key|token|geheimnis)\b",
                candidate, re.IGNORECASE,
            ):
                return candidate
    return None


def instant_street_view_url(place: str) -> str:
    """Public address-search URL documented by Instant Street View."""
    if any(ord(ch) < 32 for ch in str(place)):
        raise ValueError("Bitte einen gültigen Ortsnamen oder eine Adresse eingeben.")
    place = normalize_place(place)
    if not place or len(place) > 180:
        raise ValueError("Bitte einen gültigen Ortsnamen oder eine Adresse eingeben.")
    return _BASE_URL + quote(place, safe="")
