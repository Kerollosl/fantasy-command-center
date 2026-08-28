"""Per-player baseline projection from their own production history."""
from __future__ import annotations

import numpy as np

from ..identity.normalize import norm_name, norm_position
from ..sources import nflverse
from .scoring import season_totals

# Recency weights. Last season dominates; older seasons only stabilize the estimate.
SEASON_WEIGHTS = {0: 0.60, 1: 0.28, 2: 0.12}
FANTASY_GAMES = 17


def player_history(
    scoring: dict[str, float], current_season: int, lookback: int = 3
) -> dict[tuple[str, str], list[dict]]:
    """(norm_name, pos) -> list of season records, most recent first."""
    hist: dict[tuple[str, str], list[dict]] = {}
    for offset in range(lookback):
        season = current_season - 1 - offset
        try:
            tot = season_totals(nflverse.weekly_stats(season), scoring)
        except Exception:  # noqa: BLE001 - a missing season should not be fatal
            continue
        for r in tot.itertuples():
            k = (norm_name(r.player_display_name), norm_position(r.position))
            hist.setdefault(k, []).append(
                {"season": season, "offset": offset, "points": float(r.points),
                 "games": int(r.games), "ppg": float(r.ppg)}
            )
    return hist


def baseline_projection(records: list[dict]) -> tuple[float, float, int]:
    """Return (projected_points, confidence 0-1, total_games_of_evidence).

    Projects recency-weighted points-per-game across a full season, then
    discounts by how durable the player has actually been. Confidence rises
    with games played, so a one-good-season sample is not treated as proven.
    """
    if not records:
        return 0.0, 0.0, 0

    num = den = 0.0
    total_games = 0
    for r in records:
        w = SEASON_WEIGHTS.get(r["offset"], 0.05) * min(r["games"] / 8.0, 1.0)
        num += r["ppg"] * w
        den += w
        total_games += r["games"]

    ppg = num / den if den else 0.0
    # Availability: how many games they actually play in a season, capped at 17.
    avg_games = float(np.mean([min(r["games"], FANTASY_GAMES) for r in records]))
    exp_games = min(0.5 * avg_games + 0.5 * FANTASY_GAMES, FANTASY_GAMES)

    confidence = min(total_games / 30.0, 1.0)
    return ppg * exp_games, confidence, total_games
