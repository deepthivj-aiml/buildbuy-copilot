"""Optional delivery location — MANUAL input only, never auto-detected.

The user types a delivery location themselves (city / ZIP / address) into
an optional field that is BLANK by default. Only when they fill it in do
we compute distance + transportation cost and include it in total landed
cost. Blank means landed cost is shown "excl. transport" and ranking
works without it.

Privacy rule (non-negotiable):
- NO browser geolocation API, NO IP lookup, NO device location, NO
  auto-use of the requirement's location field. The delivery location
  is a separate, explicit, user-typed input.
- This module is OFFLINE: it resolves a typed place against a small
  built-in table of demo-area cities plus ``lat,lng`` input. Anything
  it does not recognise returns ``None`` — transport is then excluded
  and the user is told so, never guessed.
"""
from __future__ import annotations

import re

# Built-in table: demo-area cities only (same cities as the synthetic
# supplier directory, plus nearby Bay Area cities a buyer may type).
# Coordinates are city-centre approximations for the demo; a real
# deployment would resolve the typed place with a geocoding service
# the user explicitly opts into — still never silently.
KNOWN_PLACES: dict[str, tuple[float, float]] = {
    "fremont": (37.5485, -121.9886),
    "hayward": (37.6688, -122.0808),
    "san jose": (37.3387, -121.8853),
    "oakland": (37.8044, -122.2712),
    "redwood city": (37.4852, -122.2364),
    "union city": (37.5934, -122.0438),
    "alameda": (37.7652, -122.2416),
    "santa clara": (37.3541, -121.9552),
    "novato": (38.0874, -122.5699),
    "modesto": (37.6391, -120.9969),
    "portland": (45.5152, -122.6784),
    "phoenix": (33.4484, -112.074),
    "san francisco": (37.7749, -122.4194),
    "san mateo": (37.5630, -122.3255),
    "sunnyvale": (37.3688, -122.0363),
    "milpitas": (37.4323, -121.8996),
    "newark": (37.5297, -122.0402),
    "livermore": (37.6819, -121.7680),
    "pleasanton": (37.6624, -121.8747),
    "stockton": (37.9577, -121.2908),
    "sacramento": (38.5816, -121.4944),
}

_LATLNG_RE = re.compile(
    r"^\s*(-?\d{1,2}(?:\.\d+)?)\s*,\s*(-?\d{1,3}(?:\.\d+)?)\s*$"
)


def geocode_location(text: str | None) -> tuple[float, float, str] | None:
    """Resolve a user-typed location to (lat, lng, matched_name).

    Accepts a known city name (case-insensitive, ", CA" suffix ok) or a
    literal ``lat,lng`` pair. Returns ``None`` for blank / unrecognised
    input — the caller must then exclude transport, never guess.
    """
    if not text or not str(text).strip():
        return None
    raw = str(text).strip()
    m = _LATLNG_RE.match(raw)
    if m:
        lat, lng = float(m.group(1)), float(m.group(2))
        if -90.0 <= lat <= 90.0 and -180.0 <= lng <= 180.0:
            return lat, lng, f"{lat},{lng}"
        return None
    key = raw.lower().rstrip(",").strip()
    key = key.removesuffix(", ca").removesuffix(", california").strip()
    if key in KNOWN_PLACES:
        lat, lng = KNOWN_PLACES[key]
        return lat, lng, key.title()
    return None
