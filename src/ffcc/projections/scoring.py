"""Apply league scoring to raw stat lines.

We score raw stats rather than trusting a canned point total, which is what
makes PPR/half/TE-premium/superflex a config edit instead of a rewrite.
Verified against 2025: McCaffrey 416.6, Nacua 377.0 in 12-team PPR.
"""
from __future__ import annotations

import pandas as pd


def score_frame(df: pd.DataFrame, scoring: dict[str, float]) -> pd.Series:
    """Fantasy points per row for a weekly-stats frame."""
    pts = pd.Series(0.0, index=df.index)
    for stat, weight in scoring.items():
        if stat in df.columns:
            pts = pts + pd.to_numeric(df[stat], errors="coerce").fillna(0.0) * float(weight)
    return pts


def season_totals(df: pd.DataFrame, scoring: dict[str, float], season_type: str = "REG") -> pd.DataFrame:
    """Per-player season totals: points, games, points/game."""
    d = df[df["season_type"] == season_type].copy() if "season_type" in df.columns else df.copy()
    d["fantasy_points"] = score_frame(d, scoring)
    g = (
        d.groupby(["player_id", "player_display_name", "position"], dropna=False)
        .agg(points=("fantasy_points", "sum"), games=("fantasy_points", "size"))
        .reset_index()
    )
    g["ppg"] = g["points"] / g["games"].clip(lower=1)
    return g.sort_values("points", ascending=False)
