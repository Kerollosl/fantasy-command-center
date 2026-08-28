"""Roster need: how much a team still gains from another player at a position."""
from __future__ import annotations

from ..config import LeagueConfig


def starter_gaps(cfg: LeagueConfig, counts: dict[str, int]) -> dict[str, int]:
    """Unfilled starting slots by position, after flex absorption."""
    gaps: dict[str, int] = {}
    remaining = dict(counts)
    for pos, need in cfg.starters_per_team.items():
        if pos == "FLEX":
            continue
        have = remaining.get(pos, 0)
        gaps[pos] = max(need - have, 0)
        remaining[pos] = max(have - need, 0)

    flex_need = cfg.roster.get("FLEX", 0)
    surplus = sum(remaining.get(p, 0) for p in cfg.flex_eligible)
    gaps["FLEX"] = max(flex_need - surplus, 0)
    return gaps


def need_multiplier(cfg: LeagueConfig, counts: dict[str, int], position: str) -> float:
    """Scale a player's value by how badly the roster still needs that position.

    Unfilled starter > flex-fillable > pure bench depth. Kept deliberately mild
    so it nudges between close players rather than overriding real value.
    """
    if position in {"DEF", "K"}:
        # Never take these early; they are nearly interchangeable.
        filled = counts.get(position, 0) >= cfg.roster.get(position, 1)
        return 0.05 if filled else 0.35

    gaps = starter_gaps(cfg, counts)
    if gaps.get(position, 0) > 0:
        return 1.15
    if position in cfg.flex_eligible and gaps.get("FLEX", 0) > 0:
        return 1.05

    have = counts.get(position, 0)
    cap = cfg.roster.get(position, 1) + 3
    return 0.9 if have < cap else 0.6
