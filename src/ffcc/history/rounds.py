"""Which positions have actually worked out, round by round.

This is not "what champions drafted" -- championship rosters are not available
from any free source, and inventing them would be worse than saying nothing.
It is the more answerable and more useful question: taking historical ADP and
joining it to what those players actually scored, how often did a pick from
this round return a startable season at each position?

Nine seasons of real outcomes. The pattern it finds is legible: running backs
hold up in round 2, receivers overtake them in round 3, and by round 8 a
quarterback is far likelier to return a starter than a back or receiver -- the
case for waiting on quarterback, measured rather than asserted.
"""
from __future__ import annotations

import json
import logging
from collections import defaultdict

from ..config import DATA_DIR, LeagueConfig
from ..identity.normalize import norm_name, norm_position
from ..projections.scoring import season_totals
from ..sources import ffc as ffc_src
from ..sources import nflverse

log = logging.getLogger(__name__)

CACHE = DATA_DIR / "round_value.json"
SEASONS = tuple(range(2017, 2026))
POSITIONS = ("RB", "WR", "TE", "QB")
MIN_SAMPLE = 12          # below this a cell is directional, not evidence


def _startable(cfg: LeagueConfig) -> dict[str, int]:
    """How many of each position are startable league-wide."""
    return {p: cfg.replacement_rank(p) for p in POSITIONS}


def build(cfg: LeagueConfig, seasons=SEASONS) -> dict:
    limits = _startable(cfg)
    agg: dict[tuple[int, str], dict] = defaultdict(lambda: {"n": 0, "hit": 0})

    for year in seasons:
        try:
            entries, _ = ffc_src.fetch_adp(
                fmt=cfg.adp_format, teams=cfg.teams, year=year, ttl=30 * 24 * 3600
            )
            tot = season_totals(nflverse.weekly_stats(year), cfg.scoring)
        except Exception as exc:  # noqa: BLE001
            log.warning("round value: %s unavailable (%s)", year, exc)
            continue
        if not entries:
            continue

        tot = tot.copy()
        tot["pos"] = tot["position"].map(norm_position)
        finish: dict[tuple[str, str], int] = {}
        for pos in POSITIONS:
            sub = tot[tot["pos"] == pos].sort_values("points", ascending=False)
            for rank, row in enumerate(sub.itertuples(), start=1):
                finish[(norm_name(row.player_display_name), pos)] = rank

        for e in entries:
            pos = norm_position(e.position)
            if pos not in POSITIONS:
                continue
            rnd = int((e.adp - 1) // cfg.teams) + 1
            cell = agg[(rnd, pos)]
            cell["n"] += 1
            got = finish.get((norm_name(e.name), pos))
            if got is not None and got <= limits[pos]:
                cell["hit"] += 1

    rounds: dict[str, dict] = {}
    for (rnd, pos), cell in agg.items():
        if not cell["n"]:
            continue
        rounds.setdefault(str(rnd), {})[pos] = {
            "n": cell["n"],
            "hit_rate": round(cell["hit"] / cell["n"], 3),
            "thin": cell["n"] < MIN_SAMPLE,
        }
    return {"seasons": list(seasons), "rounds": rounds, "teams": cfg.teams}


def load_or_build(cfg: LeagueConfig, refresh: bool = False) -> dict:
    if not refresh and CACHE.exists():
        try:
            cached = json.loads(CACHE.read_text())
            # Rounds are cut at cfg.teams picks and "startable" is a league-wide
            # count, so a cache built for a different league size is wrong, not
            # merely stale.
            if cached.get("teams") == cfg.teams:
                return cached
            log.info("round-value cache built for %s teams; rebuilding for %s",
                     cached.get("teams"), cfg.teams)
        except Exception:  # noqa: BLE001
            log.warning("round-value cache unreadable; rebuilding")
    data = build(cfg)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(json.dumps(data))
    return data


def insight(data: dict, rnd: int) -> dict | None:
    """One honest sentence about this round, or None when evidence is thin."""
    cells = (data.get("rounds") or {}).get(str(rnd))
    if not cells:
        return None
    solid = {p: c for p, c in cells.items() if not c["thin"]}
    if len(solid) < 2:
        return None

    ranked = sorted(solid.items(), key=lambda kv: -kv[1]["hit_rate"])
    best, second = ranked[0], ranked[1]
    gap = best[1]["hit_rate"] - second[1]["hit_rate"]
    total_n = sum(c["n"] for c in solid.values())

    if gap < 0.08:
        text = (
            f"Round {rnd}: {best[0]} and {second[0]} have returned starters at "
            f"about the same rate ({best[1]['hit_rate']:.0%} vs "
            f"{second[1]['hit_rate']:.0%}). No clear positional edge here."
        )
    else:
        text = (
            f"Round {rnd}: {best[0]}s taken here returned a startable season "
            f"{best[1]['hit_rate']:.0%} of the time, against {second[1]['hit_rate']:.0%} "
            f"for {second[0]}s."
        )
    return {
        "round": rnd, "text": text, "n": total_n,
        "cells": [{"pos": p, **c} for p, c in ranked],
        "seasons": len(data.get("seasons", [])),
    }
