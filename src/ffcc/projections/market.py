"""Market-implied projections, calibrated on history.

ADP is itself a crowd projection built from thousands of drafts, so it is a
strong prior — but ADP is a *rank*, not points. We convert rank to points by
fitting, per position, what the ADP RB12 / WR24 / QB6 actually scored in past
seasons. That calibration is done on real outcomes, not assumed.
"""
from __future__ import annotations

import logging

import numpy as np
import pandas as pd

from ..identity.normalize import norm_name, norm_position
from ..sources import ffc as ffc_src
from ..sources import nflverse
from .scoring import season_totals

log = logging.getLogger(__name__)

CALIBRATION_YEARS = (2023, 2024, 2025)


def _actuals(season: int, scoring: dict[str, float]) -> dict[tuple[str, str], float]:
    """(norm_name, position) -> actual fantasy points for a season."""
    tot = season_totals(nflverse.weekly_stats(season), scoring)
    out: dict[tuple[str, str], float] = {}
    for r in tot.itertuples():
        k = (norm_name(r.player_display_name), norm_position(r.position))
        out[k] = max(out.get(k, 0.0), float(r.points))
    return out


def build_rank_curves(
    scoring: dict[str, float],
    fmt: str = "ppr",
    teams: int = 12,
    years: tuple[int, ...] = CALIBRATION_YEARS,
) -> dict[str, np.ndarray]:
    """Fit points-by-positional-ADP-rank curves from historical seasons.

    Returns position -> array where index i is expected points for positional
    ADP rank i+1. Smoothed with a rolling median so one boom/bust season does
    not put a spike in the curve.
    """
    samples: dict[str, dict[int, list[float]]] = {}

    for yr in years:
        try:
            entries, _ = ffc_src.fetch_adp(fmt=fmt, teams=teams, year=yr, ttl=30 * 24 * 3600)
            actual = _actuals(yr, scoring)
        except Exception as exc:  # noqa: BLE001
            log.warning("calibration year %s unavailable: %s", yr, exc)
            continue
        if not entries:
            continue

        by_pos: dict[str, list] = {}
        for e in sorted(entries, key=lambda x: x.adp):
            by_pos.setdefault(norm_position(e.position), []).append(e)

        for pos, lst in by_pos.items():
            for rank, e in enumerate(lst, start=1):
                pts = actual.get((norm_name(e.name), pos))
                if pts is not None:
                    samples.setdefault(pos, {}).setdefault(rank, []).append(pts)

    curves: dict[str, np.ndarray] = {}
    for pos, by_rank in samples.items():
        if not by_rank:
            continue
        max_rank = max(by_rank)
        raw = np.array(
            [float(np.mean(by_rank[r])) if r in by_rank else np.nan for r in range(1, max_rank + 1)]
        )
        s = pd.Series(raw).interpolate(limit_direction="both")
        # Smooth, then enforce monotonic decline: a later ADP rank should never
        # project higher than an earlier one, or the board becomes incoherent.
        s = s.rolling(7, center=True, min_periods=1).median()
        curves[pos] = np.maximum.accumulate(s.values[::-1])[::-1]

    return curves


def market_points(position: str, pos_rank: int, curves: dict[str, np.ndarray]) -> float:
    """Expected points for a positional ADP rank, extrapolating past the curve."""
    c = curves.get(position)
    if c is None or len(c) == 0:
        return 0.0
    i = min(max(pos_rank, 1), len(c)) - 1
    val = float(c[i])
    if pos_rank > len(c):
        # Decay gently beyond the calibrated range instead of clipping flat.
        val *= 0.92 ** (pos_rank - len(c))
    return max(val, 0.0)
