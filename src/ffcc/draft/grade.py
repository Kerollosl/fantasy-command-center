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


# Letter cutoffs in standard deviations above the picks made around this one.
# Deliberately coarse: the underlying value estimate is not precise enough to
# separate a B+ from a B, and pretending otherwise is the thing this module
# exists to avoid. Fixed cutoffs rather than a forced curve, so a round where
# everyone drafted sensibly does not have to produce an F.
PICK_LETTERS = (
    (1.50, "A+"), (1.10, "A"), (0.75, "A-"), (0.40, "B+"), (0.10, "B"),
    (-0.20, "B-"), (-0.50, "C+"), (-0.85, "C"), (-1.20, "C-"), (-1.60, "D"),
)

# Rounds either side of a pick that count as "around here". Three rounds is
# enough sample to make a standard deviation mean something without reaching
# into a part of the draft that plays by different rules.
PICK_WINDOW = 1


def _letter_index(letter: str) -> int:
    """Position of a letter on the scale; lower is better."""
    for i, (_, name) in enumerate(PICK_LETTERS):
        if name == letter:
            return i
    return len(PICK_LETTERS)


def _pick_letter(z: float) -> str:
    for floor, letter in PICK_LETTERS:
        if z >= floor:
            return letter
    return "F"


def pick_report(state, players, cfg: LeagueConfig, overall: int) -> dict | None:
    """One pick, judged.

    The same value-above-slot the team grade aggregates, but for a single
    selection, plus the two things you actually want to know afterwards: how
    it ranks against every other pick in this draft, and who was still on the
    board when it was made.

    The letter grades a pick against the picks made around it, not against
    the whole draft. Value-above-slot is not comparable across rounds: the
    VOR curve is steep early and flat late, so late picks routinely post
    larger deltas than a perfect round-1 pick can (in this league round 15
    averages +64 and round 1 averages +9). Grading on the whole draft rates
    a round-15 kicker above the second player off the board, which is not a
    judgment anyone would defend. Within a three-round window the comparison
    is fair, and an A means the same thing everywhere: you beat what picks
    made around here actually returned.
    """
    by_key = {p.key: p for p in players}
    made = {pk.overall: pk for pk in state.picks}
    pk = made.get(overall)
    if not pk:
        return None
    p = by_key.get(pk.player_key)
    if not p:
        return None

    curve = _vor_curve(players)
    values = {
        o: by_key[q.player_key].vor - _expected_vor_at(curve, o)
        for o, q in made.items()
        if q.player_key in by_key
    }
    value = values[overall]
    rnd = (overall - 1) // cfg.teams + 1

    def _round_of(o: int) -> int:
        return (o - 1) // cfg.teams + 1

    # Comparison set: this round and its neighbours.
    window = [v for o, v in values.items()
              if abs(_round_of(o) - rnd) <= PICK_WINDOW]
    arr = np.array(window, dtype=float)
    sd = float(arr.std())
    z = 0.0 if sd < 1e-9 else (value - float(arr.mean())) / sd
    pct = 100.0 * sum(1 for v in window if v < value) / max(len(window), 1)

    # Rank inside its own round -- the concrete version of the letter.
    in_round = sorted(
        (v for o, v in values.items() if _round_of(o) == rnd), reverse=True
    )
    rank = sum(1 for v in in_round if v > value) + 1

    # The board as it stood the moment before this pick.
    gone = {q.player_key for o, q in made.items() if o < overall}
    open_then = [q for q in players if q.key not in gone and q.key != p.key]
    best_then = max(open_then, key=lambda q: q.vor, default=None)
    same_pos = [q for q in open_then if q.position == p.position]
    best_pos_then = max(same_pos, key=lambda q: q.vor, default=None)
    # Nth off the board at his position -- the scarcity read on the pick.
    pos_rank = 1 + sum(
        1 for o, q in made.items() if o < overall and q.position == p.position
    )

    # This player's VOR against the best one left behind. Negative is value
    # left on the board; zero or positive means nobody available was worth
    # more, and the margin says by how much he was the best pick on offer.
    left = round(p.vor - best_then.vor, 1) if best_then else 0.0
    took_best = left >= 0

    # Value-above-slot cannot be positive at the very top of the draft: the
    # curve at pick 1 IS the best player's VOR, so taking him scores exactly
    # zero and every early pick reads as a reach. That is an artefact of the
    # measuring stick, not a bad pick. Taking the best player on the board is
    # the most this board can ask of a pick, so it floors the letter.
    letter = _pick_letter(z)
    if took_best and _letter_index("A") < _letter_index(letter):
        letter = "A"

    def _brief(q):
        return None if q is None else {
            "key": q.key, "name": q.name, "pos": q.position,
            "vor": q.vor, "proj": q.proj_points,
        }

    return {
        "overall": overall,
        "slot": pk.team_slot,
        "round": (overall - 1) // cfg.teams + 1,
        "pick_in_round": (overall - 1) % cfg.teams + 1,
        "mine": pk.team_slot == cfg.my_draft_slot,
        "letter": letter,
        "percentile": round(pct),
        "z": round(z, 2),
        "rank": rank,
        "of": len(in_round),
        "compared_to": len(window),
        "value": round(value, 1),
        "expected_vor": round(_expected_vor_at(curve, overall), 1),
        "vor": p.vor,
        "proj": p.proj_points,
        "adp": p.adp,
        # Positive = he lasted past his ADP, so you got him later than the
        # market said you would. Negative = taken ahead of his ADP.
        "adp_delta": round(overall - p.adp, 1) if p.adp is not None else None,
        "pos_rank": pos_rank,
        "left_on_board": left,
        "took_best": took_best,
        "best_available": _brief(best_then),
        "best_at_position": _brief(best_pos_then),
    }
