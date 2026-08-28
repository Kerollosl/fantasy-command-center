"""Pick probability by simulating the rest of the draft.

The question a drafter actually has is not "who is worth the most points" but
"which of these choices leaves me with the best team". That depends on what
comes back to you, which depends on what everyone else does. So we simulate.

For each candidate: take that player now, play the draft forward over your next
few picks, and score the roster you end up with. The probability is how often
that candidate produced your best roster.

Two design choices carry the accuracy:

**One perceived board per simulation.** Each simulated draft draws a single
noisy ordering, `adp + N(0, stdev)`, and every team picks the best available
player on it. The tempting alternative -- letting each team draw its own noise
and taking the minimum -- is biased: the minimum of several noisy draws sits
below the mean, so players would come off the board systematically earlier than
their real ADP, and the simulated draft would not reproduce the very
distribution it was built from.

**Common random numbers.** Candidates are compared inside the same simulated
draft, against the same opponent behavior. That turns the comparison into a
paired test and removes the shared variance, which is what lets a few hundred
simulations separate candidates that thousands of independent ones could not.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

import numpy as np

from ..config import LeagueConfig
from .lineup import bye_conflicts, optimal_lineup
from .needs import starter_gaps

DEFAULT_SIMS = 320
DEFAULT_HORIZON = 4          # how many of my own future picks to play out
UNIVERSE = 150               # deepest part of the board worth simulating
TIME_BUDGET = 0.9            # seconds; past this we fall back to the analytic score


@dataclass
class PickOdds:
    key: str
    name: str
    position: str
    probability: float          # smoothed share of simulations won
    wins: int
    sims: int
    margin: float               # mean points ahead of the field, in this sim set
    tied_with: list[str] = field(default_factory=list)

    @property
    def low(self) -> float:
        return max(0.0, self.probability - self.stderr * 1.96)

    @property
    def high(self) -> float:
        return min(1.0, self.probability + self.stderr * 1.96)

    @property
    def stderr(self) -> float:
        p = self.probability
        return (p * (1 - p) / max(self.sims, 1)) ** 0.5


def _roster_positions(players) -> dict[str, int]:
    counts: dict[str, int] = {}
    for p in players:
        counts[p.position] = counts.get(p.position, 0) + 1
    return counts


def _wants(cfg: LeagueConfig, roster, position: str) -> bool:
    """Would a rational team still add this position?"""
    if position in ("DEF", "K"):
        return False          # simulated teams never spend early picks here
    counts = _roster_positions(roster)
    cap = cfg.roster.get(position, 1) + (2 if position in cfg.flex_eligible else 0)
    return counts.get(position, 0) < cap


def simulate(
    state,
    players,
    cfg: LeagueConfig,
    candidates,
    sims: int = DEFAULT_SIMS,
    horizon: int = DEFAULT_HORIZON,
    rng: np.random.Generator | None = None,
    budget: float = TIME_BUDGET,
    hazards: dict[str, float] | None = None,
) -> list[PickOdds]:
    """Probability that each candidate is the right pick right now.

    `hazards` is the same per-position pace multiplier the rest of the app
    already fits from picks actually entered (see draft.survival). Without it
    the simulated opponents draft purely off FFC's preseason ADP even mid-run
    -- so during a real positional run the single most important number this
    tool produces would contradict the tool's own better information, for no
    reason other than one code path having access to what was learned and
    another not asking for it.
    """
    rng = rng or np.random.default_rng()
    started = time.perf_counter()

    pool = sorted(state.available(players), key=lambda p: -p.vor)[:UNIVERSE]
    if not pool or not candidates:
        return []

    idx = {p.key: i for i, p in enumerate(pool)}
    adp = np.array([p.adp if p.adp is not None else 400.0 for p in pool], dtype=float)
    sd = np.array([max(p.adp_stdev or 1.0, 0.5) for p in pool], dtype=float)

    if hazards:
        # A position going faster than market (hazard > 1) is effectively
        # being drafted earlier than its listed ADP; scale each player's
        # perceived pick time down (up) accordingly before the noise is added.
        lam = np.array([hazards.get(p.position, 1.0) or 1.0 for p in pool], dtype=float)
        adp = adp / np.clip(lam, 0.35, 3.0)

    order = state._order
    start = state.current_pick
    my_slot = cfg.my_draft_slot
    my_future = [i + 1 for i, s in enumerate(order[start - 1:], start=start - 1)
                 if s == my_slot][:horizon]
    if not my_future:
        return []
    last_pick = my_future[-1]

    my_current = [p for p in
                  (next((q for q in players if q.key == pk.player_key), None)
                   for pk in state.roster(my_slot)) if p]

    scores = np.zeros((len(candidates), sims), dtype=float)
    completed = 0

    for s in range(sims):
        if time.perf_counter() - started > budget:
            break
        # One perceived board for this simulated draft, shared by every team and
        # every candidate branch: this is the common-random-numbers pairing.
        perceived = adp + rng.normal(0.0, sd)
        board_order = np.argsort(perceived)

        for ci, cand in enumerate(candidates):
            taken = np.zeros(len(pool), dtype=bool)
            if cand.key in idx:
                taken[idx[cand.key]] = True
            mine = list(my_current) + [cand]

            for overall in range(start + 1, last_pick + 1):
                slot = order[overall - 1]
                is_mine = slot == my_slot
                roster = mine if is_mine else []
                for bi in board_order:
                    if taken[bi]:
                        continue
                    p = pool[bi]
                    if is_mine and not _wants(cfg, roster, p.position):
                        continue
                    taken[bi] = True
                    if is_mine:
                        mine.append(p)
                    break

            pts, _ = optimal_lineup(mine, cfg)
            # Unfilled starters are credited identically across candidates, so
            # they cannot decide the comparison -- only the players differ.
            gaps = sum(starter_gaps(cfg, _roster_positions(mine)).values())
            # Same bye-pileup penalty the draft grade already applies -- a
            # roster stacked three-deep on one bye week is a worse team even
            # when its raw projected total looks fine.
            bye_penalty = sum(4.0 * (n - 2) for n in bye_conflicts(mine, cfg).values())
            scores[ci, s] = pts - bye_penalty - gaps * 1e-6
        completed += 1

    if completed == 0:
        return []

    used = scores[:, :completed]
    winners = np.argmax(used, axis=0)
    wins = np.bincount(winners, minlength=len(candidates))

    best_other = np.array([
        np.max(np.delete(used, ci, axis=0), axis=0) if len(candidates) > 1 else np.zeros(completed)
        for ci in range(len(candidates))
    ])
    margins = (used - best_other).mean(axis=1)

    out: list[PickOdds] = []
    for ci, cand in enumerate(candidates):
        # Laplace smoothing: a candidate that wins every one of a few hundred
        # simulations is not a certainty, and must not be displayed as 100%.
        prob = (wins[ci] + 1.0) / (completed + len(candidates))
        out.append(PickOdds(
            key=cand.key, name=cand.name, position=cand.position,
            probability=round(float(prob), 4), wins=int(wins[ci]), sims=completed,
            margin=round(float(margins[ci]), 1),
        ))

    out.sort(key=lambda o: -o.probability)
    # Flag statistical ties so the interface never invents a winner.
    if len(out) > 1:
        top = out[0]
        for other in out[1:]:
            spread = (top.stderr ** 2 + other.stderr ** 2) ** 0.5
            if abs(top.probability - other.probability) < 1.96 * spread:
                top.tied_with.append(other.name)
                other.tied_with.append(top.name)
    return out


def value_share(recommendations, temperature: float = 12.0) -> dict[str, float]:
    """Share of model preference across candidates, from the analytic scores.

    Deliberately a different quantity from the simulated probability: it says
    how strongly the value model prefers each player, not how often that player
    ends up producing the better roster. The temperature is in fantasy points,
    so a ~12-point edge is roughly one e-fold of preference.
    """
    if not recommendations:
        return {}
    scores = np.array([r.score for r in recommendations], dtype=float)
    z = np.exp((scores - scores.max()) / max(temperature, 1e-6))
    z /= z.sum()
    return {r.player.key: round(float(v), 4) for r, v in zip(recommendations, z)}
