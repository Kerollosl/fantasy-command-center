"""Blend own-history baseline with the market-implied projection.

Neither signal wins outright. A proven veteran carries real evidence in their
own production; a rookie has none and the market is all we have. So the weight
on personal history scales with how much evidence exists, and the market
carries the rest. This is deliberately more honest than claiming to beat the
field outright.
"""
from __future__ import annotations

from ..identity.normalize import norm_name
from ..history.production import load_or_build as load_production
from ..history.production import trajectory as rank_trajectory
from .aging import load_or_fit as load_aging
from .aging import multiplier as age_multiplier
from .baseline import baseline_projection, player_history
from .market import build_rank_curves, market_points

# Even a fully-proven player never fully escapes the market prior; the field
# knows things our stat history does not (scheme changes, camp reports, trades).
MAX_HISTORY_WEIGHT = 0.55

# How much a player's rank trajectory may move the projection. Kept small on
# purpose: direction of travel is a real signal but a noisy one, and it should
# tilt a close call rather than override production and market together.
TRAJECTORY_WEIGHT = 0.06


def attach_projections(players, scoring, current_season=2026, fmt="ppr", teams=12,
                       cfg=None, use_signals=True):
    """Fill proj_points on each Player, blending history and market.

    With `use_signals`, three further adjustments apply -- age, durability and
    rank trajectory. Each is recorded on the player so the profile can show why
    a projection moved rather than shifting the number invisibly.
    """
    curves = build_rank_curves(scoring, fmt=fmt, teams=teams)
    hist = player_history(scoring, current_season)

    aging, production = {}, {}
    if use_signals and cfg is not None:
        try:
            aging = load_aging(cfg)
            production = load_production(cfg)
        except Exception:  # noqa: BLE001 - signals are an enhancement, not a dependency
            aging, production = {}, {}

    # Last season's finish rank across every position combined, computed once
    # up front rather than per player -- the positional version of this rank
    # is already stored per season line, but mixing positions on screen (the
    # unfiltered board) needs a rank on the same shared scale, not "everyone
    # reads RB3-ish small numbers that mean different things."
    last_year_overall: dict[str, int] = {}
    last_season = current_season - 1
    last_year_lines = [
        (key, ln["points"]) for key, lines in production.items()
        for ln in lines if ln["season"] == last_season
    ]
    for i, (key, _pts) in enumerate(sorted(last_year_lines, key=lambda kv: -kv[1]), start=1):
        last_year_overall[key] = i

    # Positional ADP rank drives the market term.
    by_pos: dict[str, list] = {}
    for p in sorted(players, key=lambda x: (x.adp if x.adp is not None else 9999)):
        by_pos.setdefault(p.position, []).append(p)
    pos_rank = {id(p): i + 1 for lst in by_pos.values() for i, p in enumerate(lst)}

    for p in players:
        mkt = market_points(p.position, pos_rank[id(p)], curves)
        recs = hist.get((norm_name(p.name), p.position), [])
        base, conf, games = baseline_projection(recs)

        if not recs:
            proj, w = mkt, 0.0            # rookie / no history: market only
        else:
            w = MAX_HISTORY_WEIGHT * conf
            proj = w * base + (1 - w) * mkt

        p.proj_market = round(mkt, 1)
        p.proj_baseline = round(base, 1)
        p.history_weight = round(w, 2)
        p.evidence_games = games

        adjustments = []
        if use_signals:
            # Apply the age effect only in proportion to how much this projection
            # leans on our own history. The market half already prices age -- the
            # field knows how old these players are -- so applying the full step
            # on top of ADP would double-count it.
            raw_am = age_multiplier(aging, p.position, p.age)
            damp = max(w, 0.25) if recs else 0.25
            am = 1.0 + (raw_am - 1.0) * damp
            if abs(am - 1.0) > 0.005:
                proj *= am
                adjustments.append({
                    "kind": "age", "factor": round(am, 3),
                    "note": f"age {p.age}: {(am - 1) * 100:+.0f}% "
                            f"({(raw_am - 1) * 100:+.0f}% on the {p.position} curve, "
                            f"damped because the market already prices age)",
                })

            key = f"{norm_name(p.name)}|{p.position}"
            lines = production.get(key, [])
            p.seasons = lines
            last_year = next((ln for ln in lines if ln["season"] == last_season), None)
            p.last_year_rank = last_year["rank"] if last_year else None
            p.last_year_rank_overall = last_year_overall.get(key)
            if lines:
                tr = rank_trajectory(lines)
                p.trajectory = tr
                if abs(tr) > 0.05 and abs(TRAJECTORY_WEIGHT * tr) >= 0.005:
                    tf = 1.0 + TRAJECTORY_WEIGHT * tr
                    proj *= tf
                    direction = "rising" if tr > 0 else "falling"
                    adjustments.append({
                        "kind": "trajectory", "factor": round(tf, 3),
                        "note": f"positional rank {direction}: {(tf - 1) * 100:+.0f}%",
                    })

        p.adjustments = adjustments
        p.proj_points = round(proj, 1)

    return players
