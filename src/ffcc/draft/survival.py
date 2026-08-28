"""Probability a player is still on the board at a future pick.

FFC gives adp, stdev, and observed high/low across ~8k drafts. Those
distributions are right-skewed: Jahmyr Gibbs is adp=1.5 with high=1, low=4,
so the tail runs +2.5 up and only -0.5 down. Players fall much further than
they rise, and nobody is ever taken before their observed earliest pick.

So we model the pick as a SHIFTED LOG-NORMAL with a hard floor at `high`:

    D = a + exp(N(m, s^2)),   a = high - 0.5

moment-matched to adp and stdev exactly. This respects the floor, is
right-skewed by construction, and has a closed-form CDF.

Three corrections make it survive contact with a real draft:

1. An off-market mixture. Real drafts contain players who slide for reasons
   the market never priced (a bad camp report, a manager who hates him).
   Without this the conditional update divides by ~0 for a first-rounder who
   is somehow still there in round 4 -- exactly the "why is he still here?"
   case we most need to handle.

2. Conditioning on the live board. Still-available mass below the current
   pick is dead and must be renormalized away.

3. Online positional hazard. FFC ADP describes the internet's average room,
   not yours. We refit a per-position speed multiplier from the picks actually
   entered, so "RBs are flying off the board" becomes math instead of a
   hardcoded alert.
"""
from __future__ import annotations

import math

SQRT2 = math.sqrt(2.0)
EPS_OFF_MARKET = 0.03
# Roughly one round: how long a clear faller realistically lasts once he slides.
OFF_MARKET_DECAY_PICKS = 12.0


def _phi(z: float) -> float:
    return 0.5 * (1.0 + math.erf(z / SQRT2))


def _lognormal_params(adp: float, sd: float, high: float) -> tuple[float, float, float] | None:
    """Moment-match a shifted log-normal to (adp, stdev) with floor at high."""
    a = high - 0.5
    mu_c = adp - a
    if mu_c <= 1e-6:
        return None
    s2 = math.log(1.0 + (sd * sd) / (mu_c * mu_c))
    if s2 <= 0:
        return None
    return a, math.log(mu_c) - s2 / 2.0, math.sqrt(s2)


def raw_survival(player, pick: float, total_picks: int = 180) -> float:
    """P(player lasts to `pick`), unconditioned. Includes the off-market mixture."""
    adp = player.adp
    if adp is None:
        return 1.0
    sd = max(player.adp_stdev or 1.0, 0.5)
    high = float(player.adp_high or 1)

    p = _lognormal_params(adp, sd, high)
    if p is None:
        # Degenerate (adp at or below its own floor): fall back to a normal.
        s = 1.0 - _phi((pick - adp) / sd)
    else:
        a, m, s_ln = p
        if pick <= a:
            s = 1.0
        else:
            s = 1.0 - _phi((math.log(pick - a) - m) / s_ln)

    # Off-market mass: a small chance he slides regardless of market opinion.
    # The decay must be FAST. A player who slips well past his ADP is a visible
    # value, and visible values get scooped within a round or so -- they do not
    # keep sliding indefinitely. A slow decay here makes the conditional update
    # claim an undrafted first-rounder will survive another two rounds, which is
    # exactly backwards.
    off = math.exp(-max(pick - adp, 0.0) / OFF_MARKET_DECAY_PICKS)
    return min(max((1.0 - EPS_OFF_MARKET) * s + EPS_OFF_MARKET * off, 0.0), 1.0)


def survival_prob(
    player,
    target_pick: int,
    current_pick: int,
    hazards: dict[str, float] | None = None,
    total_picks: int = 180,
) -> float:
    """P(available at `target_pick` | still available now), with league hazard applied."""
    s_now = raw_survival(player, max(current_pick - 1, 0), total_picks)
    s_then = raw_survival(player, target_pick, total_picks)
    if s_now <= 1e-9:
        return 0.0
    s = min(max(s_then / s_now, 0.0), 1.0)

    if hazards:
        lam = hazards.get(player.position, 1.0)
        if lam > 0 and lam != 1.0:
            s = s ** lam
    return min(max(s, 0.0), 1.0)


def positional_hazards(
    state, players, window: int = 15, kappa: float = 5.0
) -> dict[str, float]:
    """Per-position speed multiplier learned from picks actually made.

    lambda_p = (observed_p + kappa * expected_p) / (expected_p + kappa)

    lambda > 1 means the position is going faster than the market expects, so
    survival drops and the tool pulls that position up the board. The kappa
    prior keeps early noise from whipsawing it; it converges in ~15 picks.
    """
    recent = state.picks[-window:]
    if not recent:
        return {}

    n = len(recent)
    observed: dict[str, int] = {}
    for p in recent:
        observed[p.position] = observed.get(p.position, 0) + 1

    # Expected positional mix over that same window, from ADP ordering.
    start = state.current_pick - n
    by_adp = sorted(
        [p for p in players if p.adp is not None], key=lambda x: x.adp
    )[max(start, 0) : state.current_pick]
    expected: dict[str, float] = {}
    for p in by_adp:
        expected[p.position] = expected.get(p.position, 0.0) + 1.0

    hazards: dict[str, float] = {}
    for pos in set(observed) | set(expected):
        o = float(observed.get(pos, 0))
        e = float(expected.get(pos, 0.0))
        # Shrunk toward 1.0: equals o/e with no prior, and returns exactly 1.0
        # when the room is drafting the position at market pace.
        hazards[pos] = (o + kappa) / (e + kappa)
    return hazards
