"""Blend own-history baseline with the market-implied projection.

Neither signal wins outright. A proven veteran carries real evidence in their
own production; a rookie has none and the market is all we have. So the weight
on personal history scales with how much evidence exists, and the market
carries the rest. This is deliberately more honest than claiming to beat the
field outright.
"""
from __future__ import annotations

from ..identity.normalize import norm_name
from .baseline import baseline_projection, player_history
from .market import build_rank_curves, market_points

# Even a fully-proven player never fully escapes the market prior; the field
# knows things our stat history does not (scheme changes, camp reports, trades).
MAX_HISTORY_WEIGHT = 0.55


def attach_projections(players, scoring, current_season=2026, fmt="ppr", teams=12):
    """Fill proj_points on each Player, blending history and market."""
    curves = build_rank_curves(scoring, fmt=fmt, teams=teams)
    hist = player_history(scoring, current_season)

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

        p.proj_points = round(proj, 1)
        p.proj_market = round(mkt, 1)
        p.proj_baseline = round(base, 1)
        p.history_weight = round(w, 2)
        p.evidence_games = games

    return players
