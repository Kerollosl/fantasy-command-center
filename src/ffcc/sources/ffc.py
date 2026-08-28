"""Fantasy Football Calculator ADP.

The critical source: real ADP from thousands of mock drafts, and crucially
`stdev`/`high`/`low`, which let us model the probability a player survives
until our next pick. Verified live 2026-08-27 with 7,986 drafts.
"""
from __future__ import annotations

from dataclasses import dataclass

from .cache import fetch_json

BASE = "https://fantasyfootballcalculator.com/api/v1/adp"


@dataclass(frozen=True)
class AdpEntry:
    name: str
    position: str
    team: str
    adp: float
    stdev: float
    high: int
    low: int
    times_drafted: int
    bye: int | None
    ffc_id: int


def fetch_adp(fmt: str = "ppr", teams: int = 12, year: int = 2026, ttl: float = 6 * 3600):
    """Return (entries, meta). Falls back to prior season if the new one is empty."""
    url = f"{BASE}/{fmt}?teams={teams}&year={year}"
    data = fetch_json(url, key=f"ffc_{fmt}_{teams}_{year}.json", ttl=ttl)

    players = data.get("players") or []
    if not players and year > 2000:
        url = f"{BASE}/{fmt}?teams={teams}&year={year - 1}"
        data = fetch_json(url, key=f"ffc_{fmt}_{teams}_{year-1}.json", ttl=ttl)
        players = data.get("players") or []

    entries = [
        AdpEntry(
            name=p["name"],
            position=(p["position"] or "").upper(),
            team=(p.get("team") or "").upper(),
            adp=float(p["adp"]),
            # Guard the deep board: stdev can be 0 for thinly-drafted players,
            # which would make the survival CDF a step function.
            stdev=max(float(p.get("stdev") or 0.0), 0.5),
            high=int(p.get("high") or 1),
            low=int(p.get("low") or 300),
            times_drafted=int(p.get("times_drafted") or 0),
            bye=int(p["bye"]) if p.get("bye") else None,
            ffc_id=int(p.get("player_id") or 0),
        )
        for p in players
    ]
    return entries, data.get("meta", {})
