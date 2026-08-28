"""nflverse: historical weekly stats + the player crosswalk.

Weekly stats go back to 1999 (27 seasons verified). We compute fantasy points
from raw stat lines rather than trusting canned totals, so any scoring change
is a config edit.
"""
from __future__ import annotations

import io

import pandas as pd

from .cache import fetch

REL = "https://github.com/nflverse/nflverse-data/releases/download"

# Stat columns we score. Names match nflverse weekly stats.
STAT_COLUMNS = (
    "passing_yards", "passing_tds", "interceptions", "passing_2pt_conversions",
    "rushing_yards", "rushing_tds", "rushing_2pt_conversions",
    "receptions", "receiving_yards", "receiving_tds", "receiving_2pt_conversions",
    "rushing_fumbles_lost", "receiving_fumbles_lost", "sack_fumbles_lost",
)


def weekly_stats(season: int, ttl: float = 24 * 3600) -> pd.DataFrame:
    """Weekly player stats for one season."""
    url = f"{REL}/stats_player/stats_player_week_{season}.csv"
    raw = fetch(url, key=f"nflverse_week_{season}.csv", ttl=ttl)
    df = pd.read_csv(io.BytesIO(raw), low_memory=False)

    # Build every missing/coerced stat column in one shot; assigning them one
    # at a time fragments the frame badly on a 19k-row, 100+ column table.
    filled = {
        c: pd.to_numeric(df[c], errors="coerce").fillna(0.0)
        if c in df.columns
        else pd.Series(0.0, index=df.index)
        for c in STAT_COLUMNS
    }
    filled["fumbles_lost"] = (
        filled["rushing_fumbles_lost"]
        + filled["receiving_fumbles_lost"]
        + filled["sack_fumbles_lost"]
    )
    return pd.concat([df.drop(columns=[c for c in filled if c in df.columns]),
                      pd.DataFrame(filled, index=df.index)], axis=1)


def players(ttl: float = 24 * 3600) -> pd.DataFrame:
    """Canonical player table. Has gsis_id/espn_id/pfr_id but NO yahoo or sleeper id."""
    raw = fetch(f"{REL}/players/players.csv", key="nflverse_players.csv", ttl=ttl)
    return pd.read_csv(io.BytesIO(raw), low_memory=False)


def depth_charts(season: int, ttl: float = 12 * 3600) -> pd.DataFrame | None:
    """Depth-chart order. 2026 is available, so this reflects the current season."""
    try:
        raw = fetch(
            f"{REL}/depth_charts/depth_charts_{season}.csv",
            key=f"nflverse_depth_{season}.csv",
            ttl=ttl,
        )
        return pd.read_csv(io.BytesIO(raw), low_memory=False)
    except Exception:
        return None
