"""At a snake turn you hold consecutive picks, which makes 'who survives to my
next pick' a meaningless question -- everyone does. The recommender must look
past the turn, or VONA collapses to zero for the entire board."""
import dataclasses
from dataclasses import dataclass

from ffcc.config import load_league
from ffcc.draft.recommend import _decision_horizon
from ffcc.draft.state import DraftState


def cfg_at_slot(slot: int):
    """League config pinned to a slot.

    These tests must not read my_draft_slot from league.yaml: the app now
    rewrites that file when you change your slot in the UI, so a test coupled
    to it fails for reasons that have nothing to do with the horizon logic.
    """
    return dataclasses.replace(load_league(), my_draft_slot=slot)


@dataclass
class P:
    key: str
    name: str
    position: str
    proj_points: float = 100.0
    bye: int | None = None


def test_horizon_skips_back_to_back_picks_at_the_turn():
    cfg = cfg_at_slot(1)         # slot 1 -> the round 2/3 turn is consecutive
    turn = 2 * cfg.teams         # 24 in a 12-team league, 28 in a 14
    st = DraftState(cfg)
    for i in range(turn - 1):
        st.record(P(f"k{i}", f"p{i}", "RB"))
    assert st.current_pick == turn
    assert st.next_pick_for(cfg.my_draft_slot, after=turn) == turn + 1  # the trap
    assert _decision_horizon(st, cfg, turn) == 4 * cfg.teams      # the real horizon


def test_horizon_is_the_next_pick_when_not_at_the_turn():
    cfg = cfg_at_slot(1)
    st = DraftState(cfg)
    assert _decision_horizon(st, cfg, 1) == 2 * cfg.teams


def test_horizon_is_none_when_draft_is_over():
    cfg = cfg_at_slot(1)
    st = DraftState(cfg)
    for i in range(cfg.total_picks):
        st.record(P(f"k{i}", f"p{i}", "RB"))
    assert _decision_horizon(st, cfg, st.current_pick) is None
