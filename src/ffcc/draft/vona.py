"""VONA — value over next available.

The real snake-draft question is never "who is best?" but "what do I actually
lose by waiting?". If the position is deep, the best player on the board costs
you nothing to pass on; if there is a cliff, passing is expensive.

E[best survivor at a position] is the expected value of the max over the
remaining pool: walking the pool best-first, player i is the best survivor iff
i survives and every better player does not.
"""
from __future__ import annotations

from .survival import survival_prob


def expected_best_available(pool, target_pick: int, current_pick: int, value=lambda p: p.vor) -> float:
    """Expected value of the best player left at `target_pick`."""
    ranked = sorted(pool, key=lambda p: -value(p))
    exp = 0.0
    none_better_survived = 1.0
    for p in ranked:
        s = survival_prob(p, target_pick, current_pick)
        exp += value(p) * s * none_better_survived
        none_better_survived *= (1.0 - s)
        if none_better_survived < 1e-6:
            break
    return exp


def vona_by_position(available, target_pick: int, current_pick: int) -> dict[str, float]:
    """Expected best-available VOR per position at my next pick."""
    by_pos: dict[str, list] = {}
    for p in available:
        by_pos.setdefault(p.position, []).append(p)
    return {
        pos: expected_best_available(lst, target_pick, current_pick)
        for pos, lst in by_pos.items()
    }


def player_vona(player, available, target_pick: int, current_pick: int) -> float:
    """What taking this player now gains over the best I'd expect later at his position."""
    same_pos = [p for p in available if p.position == player.position and p.key != player.key]
    if not same_pos:
        return player.vor
    return player.vor - expected_best_available(same_pos, target_pick, current_pick)
