"""Optimal starting lineup from a roster.

Used constantly -- it is the basis of both grading and recommendation scoring
-- so it must be cheap. With <=10 slots a greedy fill by dedicated position
then best-remaining-into-flex is optimal, because flex is the only ambiguity
and it always wants the highest remaining eligible scorer.
"""
from __future__ import annotations

from ..config import LeagueConfig


def optimal_lineup(players, cfg: LeagueConfig) -> tuple[float, dict[str, list]]:
    """Return (projected starting points, slot -> players)."""
    pool = sorted(players, key=lambda p: -p.proj_points)
    used: set[int] = set()
    slots: dict[str, list] = {}
    total = 0.0

    for pos, count in cfg.starters_per_team.items():
        if pos == "FLEX":
            continue
        picked = []
        for p in pool:
            if len(picked) >= count:
                break
            if id(p) not in used and p.position == pos:
                picked.append(p)
                used.add(id(p))
                total += p.proj_points
        slots[pos] = picked

    flex_n = cfg.roster.get("FLEX", 0)
    flex = []
    for p in pool:
        if len(flex) >= flex_n:
            break
        if id(p) not in used and p.position in cfg.flex_eligible:
            flex.append(p)
            used.add(id(p))
            total += p.proj_points
    if flex_n:
        slots["FLEX"] = flex

    return round(total, 1), slots


def bye_conflicts(players, cfg: LeagueConfig) -> dict[int, int]:
    """Bye week -> count of would-be starters idle that week."""
    starters = []
    _, slots = optimal_lineup(players, cfg)
    for lst in slots.values():
        starters.extend(lst)
    counts: dict[int, int] = {}
    for p in starters:
        if p.bye:
            counts[p.bye] = counts.get(p.bye, 0) + 1
    return {wk: n for wk, n in counts.items() if n >= 3}
