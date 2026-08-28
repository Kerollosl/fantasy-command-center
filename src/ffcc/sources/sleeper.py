"""Sleeper: player metadata, live injury status, and free league/draft import.

No auth at all. Injury status here is the freshest free signal we have for
draft day. Note the ID crosswalk is incomplete (only ~55% have yahoo_id,
~32% gsis_id) — the resolver must not depend on it alone.
"""
from __future__ import annotations

from .cache import fetch_json

BASE = "https://api.sleeper.app/v1"

# Statuses that should visibly flag a player on the board.
RISK_STATUSES = {"IR", "PUP", "Out", "Doubtful", "Suspended", "NA", "DNR"}


def all_players(ttl: float = 12 * 3600) -> dict:
    """~12k players keyed by sleeper id. 14.6MB, so cache generously."""
    return fetch_json(f"{BASE}/players/nfl", key="sleeper_players.json", ttl=ttl)


def nfl_state(ttl: float = 3600) -> dict:
    return fetch_json(f"{BASE}/state/nfl", key="sleeper_state.json", ttl=ttl)


def trending_adds(hours: int = 24, limit: int = 50, ttl: float = 1800) -> list[dict]:
    return fetch_json(
        f"{BASE}/players/nfl/trending/add?lookback_hours={hours}&limit={limit}",
        key=f"sleeper_trending_{hours}_{limit}.json",
        ttl=ttl,
    )


# --- Free league/draft import (used by the history importer) ---

def user(username: str, ttl: float = 24 * 3600) -> dict:
    return fetch_json(f"{BASE}/user/{username}", key=f"sleeper_user_{username}.json", ttl=ttl)


def user_leagues(user_id: str, season: int, ttl: float = 6 * 3600) -> list[dict]:
    return fetch_json(
        f"{BASE}/user/{user_id}/leagues/nfl/{season}",
        key=f"sleeper_leagues_{user_id}_{season}.json",
        ttl=ttl,
    )


def league_drafts(league_id: str, ttl: float = 6 * 3600) -> list[dict]:
    return fetch_json(
        f"{BASE}/league/{league_id}/drafts", key=f"sleeper_drafts_{league_id}.json", ttl=ttl
    )


def draft_picks(draft_id: str, ttl: float = 6 * 3600) -> list[dict]:
    return fetch_json(
        f"{BASE}/draft/{draft_id}/picks", key=f"sleeper_picks_{draft_id}.json", ttl=ttl
    )
