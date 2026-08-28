"""nflverse season roster: the one place every player ID lives on a single row.

players.csv has no yahoo_id and Sleeper's is only ~55% populated, but
roster_{season}.csv carries gsis_id, espn_id, sleeper_id, yahoo_id,
sportradar_id and more together. That makes it both the best join bridge and
the thing that will let the Yahoo adapter map its players when access lands.
"""
from __future__ import annotations

import io

import pandas as pd

from .cache import fetch

REL = "https://github.com/nflverse/nflverse-data/releases/download"

ID_COLUMNS = (
    "gsis_id", "espn_id", "sleeper_id", "yahoo_id",
    "sportradar_id", "pfr_id", "pff_id", "fantasy_data_id",
)


def season_roster(season: int, ttl: float = 24 * 3600) -> pd.DataFrame:
    """One row per player with the full ID set. Falls back a season if needed."""
    for yr in (season, season - 1):
        try:
            raw = fetch(
                f"{REL}/rosters/roster_{yr}.csv", key=f"nflverse_roster_{yr}.csv", ttl=ttl
            )
            df = pd.read_csv(io.BytesIO(raw), low_memory=False)
            if len(df):
                return df
        except Exception:  # noqa: BLE001
            continue
    return pd.DataFrame()
