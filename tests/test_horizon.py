"""At a snake turn you hold consecutive picks, which makes 'who survives to my
next pick' a meaningless question -- everyone does. The recommender must look
past the turn, or VONA collapses to zero for the entire board."""
from dataclasses import dataclass

from ffcc.config import load_league
from ffcc.draft.recommend import _decision_horizon
from ffcc.draft.state import DraftState


@dataclass
class P:
    key: str
    name: str
    position: str
    proj_points: float = 100.0
    bye: int | None = None


def test_horizon_skips_back_to_back_picks_at_the_turn():
    cfg = load_league()          # slot 1 -> picks 24 and 25 are consecutive
    st = DraftState(cfg)
    for i in range(23):
        st.record(P(f"k{i}", f"p{i}", "RB"))
    assert st.current_pick == 24
    assert st.next_pick_for(cfg.my_draft_slot, after=24) == 25   # the trap
    assert _decision_horizon(st, cfg, 24) == 48                  # the real horizon


def test_horizon_is_the_next_pick_when_not_at_the_turn():
    cfg = load_league()
    st = DraftState(cfg)
    assert _decision_horizon(st, cfg, 1) == 24


def test_horizon_is_none_when_draft_is_over():
    cfg = load_league()
    st = DraftState(cfg)
    for i in range(cfg.total_picks):
        st.record(P(f"k{i}", f"p{i}", "RB"))
    assert _decision_horizon(st, cfg, st.current_pick) is None
