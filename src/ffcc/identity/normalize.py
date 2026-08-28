"""Name and team normalization for cross-source player matching."""
from __future__ import annotations

import re
import unicodedata

# Sources disagree on team abbreviations. Normalize to nflverse's convention.
TEAM_ALIASES = {
    "JAC": "JAX", "JAX": "JAX",
    "LA": "LAR", "LAR": "LAR", "STL": "LAR",
    "LAC": "LAC", "SD": "LAC",
    "WSH": "WAS", "WFT": "WAS", "WAS": "WAS",
    "OAK": "LV", "LV": "LV", "LVR": "LV",
    "ARZ": "ARI", "ARI": "ARI",
    "BLT": "BAL", "BAL": "BAL",
    "HST": "HOU", "HOU": "HOU",
    "CLV": "CLE", "CLE": "CLE",
    "SL": "LAR", "SF": "SF", "TB": "TB", "NE": "NE", "NO": "NO", "NYG": "NYG", "NYJ": "NYJ",
    "GB": "GB", "KC": "KC",
}

SUFFIXES = {"jr", "sr", "ii", "iii", "iv", "v"}

# Nicknames and legal-name changes that pure string matching will never catch.
NAME_ALIASES = {
    "hollywood brown": "marquise brown",
    "gabe davis": "gabriel davis",
    "chig okonkwo": "chigoziem okonkwo",
    "cam ward": "cameron ward",
    "josh palmer": "joshua palmer",
    "mike thomas": "michael thomas",
    "chris brooks": "christopher brooks",
    "deebo samuel sr": "deebo samuel",
    "marvin mims jr": "marvin mims",
    "tank dell": "nathaniel dell",
    "scotty miller": "scott miller",
    "demario douglas": "demario douglas",
    "kenneth walker iii": "kenneth walker",
    "brian robinson jr": "brian robinson",
    "michael penix jr": "michael penix",
}


def norm_team(team: str | None) -> str:
    if not team:
        return ""
    t = str(team).strip().upper()
    return TEAM_ALIASES.get(t, t)


def norm_name(name: str | None) -> str:
    """Aggressively normalized name key: ascii, lowercase, no punctuation/suffix."""
    if not name:
        return ""
    s = unicodedata.normalize("NFKD", str(name))
    s = s.encode("ascii", "ignore").decode("ascii").lower()
    s = re.sub(r"[.\'`]", "", s)
    s = re.sub(r"[^a-z0-9]+", " ", s).strip()
    parts = [p for p in s.split() if p not in SUFFIXES]
    key = " ".join(parts) if parts else s
    return NAME_ALIASES.get(key, key)


def norm_position(pos: str | None) -> str:
    """Collapse source-specific position spellings."""
    if not pos:
        return ""
    p = str(pos).strip().upper()
    if p in {"PK", "K"}:
        return "K"
    if p in {"DEF", "DST", "D/ST", "DEFENSE"}:
        return "DEF"
    if p == "FB":
        return "RB"
    return p
