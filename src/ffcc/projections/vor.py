"""Value over replacement + tiers.

Raw projected points are misleading: a QB outscores an RB in gross points, but
if the 12th-best QB also scores a lot, drafting an elite QB early buys little
*marginal* advantage. VOR measures points above the player you could have had
for free at that position, which is the only comparison that works across
positions. Replacement level comes from the league config, never hardcoded.
"""
from __future__ import annotations

import numpy as np


def replacement_levels(players, cfg) -> dict[str, float]:
    """Projected points of the last startable player at each position."""
    levels: dict[str, float] = {}
    for pos in {p.position for p in players}:
        pool = sorted(
            [p.proj_points for p in players if p.position == pos], reverse=True
        )
        if not pool:
            continue
        idx = min(cfg.replacement_rank(pos), len(pool)) - 1
        levels[pos] = float(pool[idx])
    return levels


def attach_vor(players, cfg) -> dict[str, float]:
    levels = replacement_levels(players, cfg)
    for p in players:
        p.vor = round(p.proj_points - levels.get(p.position, 0.0), 1)
    return levels


def attach_tiers(players, max_tiers: int = 12) -> None:
    """Gap-based tiers within each position.

    Tiers matter more than raw rank during a draft: what you need to know is
    'is there a cliff after this guy'. We cut where the drop between adjacent
    players is unusually large relative to that position's typical spacing.
    """
    by_pos: dict[str, list] = {}
    for p in players:
        by_pos.setdefault(p.position, []).append(p)

    for pos, lst in by_pos.items():
        lst.sort(key=lambda x: -x.proj_points)
        if len(lst) < 2:
            for p in lst:
                p.tier = 1
            continue

        pts = np.array([p.proj_points for p in lst], dtype=float)
        gaps = -np.diff(pts)
        if gaps.size == 0 or not np.isfinite(gaps).any():
            for p in lst:
                p.tier = 1
            continue

        # A cliff is a gap meaningfully larger than typical spacing.
        threshold = float(np.mean(gaps) + 0.9 * np.std(gaps))
        tier = 1
        lst[0].tier = 1
        for i in range(1, len(lst)):
            if gaps[i - 1] > threshold and tier < max_tiers:
                tier += 1
            lst[i].tier = tier
