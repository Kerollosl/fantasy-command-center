"""Pick recommendations, with the reasoning shown.

Score = VONA, adjusted for roster need, with the survival read attached so the
user can see *why* rather than being handed a ranked list to trust blindly.
The output always says what happens if you wait, because that is the decision
actually being made.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ..config import LeagueConfig
from ..sources.sleeper import RISK_STATUSES
from .needs import need_multiplier
from .survival import positional_hazards, survival_prob
from .vona import expected_best_available


def _decision_horizon(state, cfg: LeagueConfig, current: int) -> int | None:
    """The pick that 'waiting' actually costs you.

    At the turn you hold consecutive picks (e.g. 24 and 25), so asking who
    survives to your immediate next pick is trivial -- almost everyone does,
    and VONA collapses to zero for the whole board. What you really give up by
    passing now is whoever is gone by your next *separated* pick. So we skip
    over back-to-back picks and measure against the one after the turn.
    """
    nxt = state.next_pick_for(cfg.my_draft_slot, after=current)
    if nxt is None:
        return None
    if nxt - current <= 1:
        after = state.next_pick_for(cfg.my_draft_slot, after=nxt)
        return after or nxt
    return nxt


@dataclass
class Recommendation:
    player: object
    score: float
    vona: float
    survival_next: float
    reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def recommend(state, players, cfg: LeagueConfig, limit: int = 10) -> list[Recommendation]:
    available = state.available(players)
    if not available:
        return []

    current = state.current_pick
    my_next = _decision_horizon(state, cfg, current)
    hazards = positional_hazards(state, players)

    counts = {}
    for p in state.roster(cfg.my_draft_slot):
        counts[p.position] = counts.get(p.position, 0) + 1

    # Expected best available per position at my next pick, computed once.
    by_pos: dict[str, list] = {}
    for p in available:
        by_pos.setdefault(p.position, []).append(p)
    exp_next = {
        pos: (
            expected_best_available(lst, my_next, current)
            if my_next
            else 0.0
        )
        for pos, lst in by_pos.items()
    }

    recs: list[Recommendation] = []
    for p in sorted(available, key=lambda x: -x.vor)[:60]:
        same = [q for q in by_pos.get(p.position, []) if q.key != p.key]
        e_next = (
            expected_best_available(same, my_next, current) if (same and my_next) else 0.0
        )
        vona = p.vor - e_next
        mult = need_multiplier(cfg, counts, p.position)
        score = (0.45 * p.vor + 0.55 * vona) * mult

        surv = survival_prob(p, my_next, current, hazards) if my_next else 0.0

        reasons, warnings = [], []
        reasons.append(f"VOR {p.vor:.0f} · tier {p.tier} {p.position}")
        if my_next:
            if surv < 0.15:
                reasons.append(f"almost certainly gone by pick {my_next} ({surv:.0%})")
            elif surv > 0.7:
                reasons.append(f"likely still there at {my_next} ({surv:.0%}) — can wait")
            else:
                reasons.append(f"{surv:.0%} to last to pick {my_next}")
            if vona > 12:
                reasons.append(f"+{vona:.0f} pts vs next {p.position} you'd get")

        lam = hazards.get(p.position)
        if lam and lam > 1.35:
            reasons.append(f"{p.position} run in progress ({lam:.1f}x market pace)")

        if p.injury_status in RISK_STATUSES:
            warnings.append(f"injury: {p.injury_status}")
        if p.depth_chart_order and p.depth_chart_order > 1 and p.position in ("RB", "WR", "TE"):
            warnings.append(f"depth chart #{p.depth_chart_order}")
        if p.evidence_games and p.evidence_games < 10:
            warnings.append(f"thin history ({p.evidence_games} career games)")
        if p.position in ("DEF", "K") and state.current_pick < cfg.teams * 12:
            warnings.append("too early for this position")

        recs.append(Recommendation(p, round(score, 1), round(vona, 1), surv, reasons, warnings))

    recs.sort(key=lambda r: -r.score)
    return recs[:limit]
