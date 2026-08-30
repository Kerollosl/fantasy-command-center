"""Live draft grades for every team, decomposed so they can be argued with.

A bare letter is useless mid-draft. Four components, each in interpretable
units, always rendered alongside the grade:

  SLP  Starting-lineup projection. What actually wins leagues. Unfilled
       starter slots are credited with the value the team can still expect
       from its remaining picks -- without that forward-looking term, whoever
       picked first trivially "wins" at pick 12 and the grade says nothing.
  VAS  Value above slot, in fantasy points. Measured against a VOR-by-pick
       curve rather than raw ADP delta: a 10-pick steal in round 1 is worth
       far more than one in round 12, and ADP delta gets that backwards.
  RF   Roster fit: unfilled starters, over-allocation, bye pileups, and
       early K/DST.

Early grades are genuinely noisy, so we publish a confidence level instead of
implying precision we do not have.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from ..config import LeagueConfig
from .lineup import bye_conflicts, optimal_lineup
from .needs import starter_gaps
from ..projections.vor import replacement_levels


@dataclass
class TeamGrade:
    slot: int
    letter: str
    score: float
    slp: float
    vas: float
    rf: float
    confidence: str
    notes: list[str] = field(default_factory=list)


def _vor_curve(players) -> np.ndarray:
    """Expected VOR by overall pick, from the market's own ordering."""
    ranked = sorted(
        [p for p in players if p.adp is not None], key=lambda p: p.adp
    )
    vals = np.array([p.vor for p in ranked], dtype=float)
    if vals.size == 0:
        return np.zeros(1)
    # Monotone non-increasing: later picks should not be expected to beat earlier.
    return np.minimum.accumulate(vals)


def _expected_vor_at(curve: np.ndarray, pick: int) -> float:
    if curve.size == 0:
        return 0.0
    return float(curve[min(max(pick, 1), curve.size) - 1])


# How much of a future pick's expected edge to count. A pick you have not made
# is not a player you have; discounting it keeps early grades honest.
FUTURE_PICK_DISCOUNT = 0.5


def grade_all(state, players, cfg: LeagueConfig) -> list[TeamGrade]:
    by_key = {p.key: p for p in players}
    curve = _vor_curve(players)
    levels = replacement_levels(players, cfg)
    starter_positions = [p for p in cfg.starters_per_team if p != "FLEX"]
    base_replacement = (
        sum(levels.get(p, 0.0) for p in starter_positions) / max(len(starter_positions), 1)
    )

    # Value a team can still expect from its remaining picks.
    remaining_pool = sorted(state.available(players), key=lambda p: -p.proj_points)

    raw: list[TeamGrade] = []
    for slot in range(1, cfg.teams + 1):
        roster = [by_key[p.player_key] for p in state.roster(slot) if p.player_key in by_key]

        # SLP: current lineup, plus forward credit for the starter slots this
        # team has not filled yet.
        #
        # The credit is essential and must be in the SAME UNITS as the lineup.
        # Without it the team currently on the clock always grades last -- it has
        # simply made fewer picks than everyone else, which is not a judgment
        # about how it is drafting. We estimate each future pick as the player
        # this team could realistically still get: walk down the remaining pool
        # by how many picks elapse before that selection.
        slp, _ = optimal_lineup(roster, cfg)
        counts: dict[str, int] = {}
        for q in roster:
            counts[q.position] = counts.get(q.position, 0) + 1
        unfilled = sum(starter_gaps(cfg, counts).values())

        future_picks = [
            i + 1
            for i, s in enumerate(state._order[state.current_pick - 1:], start=state.current_pick - 1)
            if s == slot
        ]
        # Each unfilled slot is credited at roughly replacement level plus a
        # small edge for picking earlier. Keeping the credit nearly flat is the
        # point: an empty slot should not differentiate teams, because nobody
        # knows who will fill it. Real picks do the differentiating; otherwise
        # the grade just measures how many picks you happen to have made.
        credit = 0.0
        for pick in future_picks[: max(unfilled, 0)]:
            edge = max(_expected_vor_at(curve, pick), 0.0) * FUTURE_PICK_DISCOUNT
            credit += base_replacement + edge
        slp_total = slp + credit

        # VAS: points captured above what that draft slot normally returns.
        picks = state.roster(slot)
        if picks:
            deltas = [
                by_key[p.player_key].vor - _expected_vor_at(curve, p.overall)
                for p in picks
                if p.player_key in by_key
            ]
            vas = float(np.mean(deltas)) if deltas else 0.0
        else:
            vas = 0.0

        # RF: structural penalties.
        notes: list[str] = []
        rf = 0.0
        counts: dict[str, int] = {}
        for p in roster:
            counts[p.position] = counts.get(p.position, 0) + 1
        for pos in ("DEF", "K"):
            if counts.get(pos, 0) and state.current_pick < cfg.teams * 12:
                rf -= 12.0
                notes.append(f"early {pos}")
        for pos, have in counts.items():
            cap = cfg.roster.get(pos, 1) + 3
            if have > cap:
                rf -= 6.0 * (have - cap)
                notes.append(f"{have} {pos}s")
        byes = bye_conflicts(roster, cfg)
        for wk, n in byes.items():
            rf -= 4.0 * (n - 2)
            notes.append(f"{n} starters on bye {wk}")

        raw.append(TeamGrade(slot, "", 0.0, round(slp_total, 1), round(vas, 1),
                             round(rf, 1), "", notes))

    # Z-score across the league so grades are mutually comparable.
    def z(vals):
        a = np.array(vals, dtype=float)
        sd = a.std()
        return np.zeros_like(a) if sd < 1e-9 else (a - a.mean()) / sd

    zs, zv, zr = z([g.slp for g in raw]), z([g.vas for g in raw]), z([g.rf for g in raw])
    picks_made = len(state.picks) / max(cfg.total_picks, 1)
    conf = "low" if picks_made < 0.25 else ("medium" if picks_made < 0.6 else "high")

    for i, g in enumerate(raw):
        g.score = float(0.55 * zs[i] + 0.30 * zv[i] + 0.15 * zr[i])
        g.confidence = conf

    order = sorted(raw, key=lambda g: -g.score)
    letters = ["A+", "A", "A-", "B+", "B", "B", "B-", "C+", "C", "C-", "D+", "D"]
    for rank, g in enumerate(order):
        g.letter = letters[min(rank * len(letters) // max(len(order), 1), len(letters) - 1)]
    return sorted(raw, key=lambda g: g.slot)


def pick_values(state, players, cfg: LeagueConfig, slot: int) -> list[dict]:
    """One team's picks, each with value captured above the VOR that draft
    slot normally returns -- the same VAS logic `grade_all` aggregates,
    exposed per-pick. Basis for an end-of-draft "best value" / "biggest
    reach" recap.
    """
    by_key = {p.key: p for p in players}
    curve = _vor_curve(players)
    out = []
    for pk in state.roster(slot):
        p = by_key.get(pk.player_key)
        if not p:
            continue
        expected = _expected_vor_at(curve, pk.overall)
        out.append({
            "key": p.key, "name": p.name, "pos": p.position, "team": p.team,
            "overall": pk.overall, "round": (pk.overall - 1) // cfg.teams + 1,
            "proj": p.proj_points, "vor": p.vor,
            "expected_vor": round(expected, 1), "value": round(p.vor - expected, 1),
        })
    return out
