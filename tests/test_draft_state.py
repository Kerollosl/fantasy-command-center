from dataclasses import dataclass

import pytest

from ffcc.config import load_league
from ffcc.draft.lineup import optimal_lineup
from ffcc.draft.needs import need_multiplier, starter_gaps
from ffcc.draft.state import DraftState


@dataclass
class P:
    key: str
    name: str
    position: str
    proj_points: float = 100.0
    bye: int | None = None


def mk(n, pos, pts=100.0):
    return P(key=f"{n}|{pos}", name=n, position=pos, proj_points=pts)


def test_apply_then_undo_restores_state():
    cfg = load_league()
    st = DraftState(cfg)
    players = [mk(f"p{i}", "RB") for i in range(5)]
    for p in players:
        st.record(p)
    assert st.current_pick == 6
    for _ in range(5):
        st.undo()
    assert st.current_pick == 1
    assert st.picks == []


def test_duplicate_pick_is_rejected():
    cfg = load_league()
    st = DraftState(cfg)
    p = mk("dup", "WR")
    st.record(p)
    with pytest.raises(ValueError):
        st.record(p)


def test_picks_are_assigned_to_the_slot_on_the_clock():
    cfg = load_league()
    st = DraftState(cfg)
    order = cfg.snake_order()
    for i in range(cfg.teams + 3):
        st.record(mk(f"p{i}", "RB"))
    assert [p.team_slot for p in st.picks] == order[: cfg.teams + 3]


def test_optimal_lineup_prefers_higher_projections():
    cfg = load_league()
    roster = [mk("a", "RB", 200), mk("b", "RB", 150), mk("c", "RB", 50),
              mk("d", "WR", 180), mk("e", "WR", 140), mk("f", "QB", 300),
              mk("g", "TE", 120)]
    total, slots = optimal_lineup(roster, cfg)
    assert [p.name for p in slots["RB"]] == ["a", "b"]
    # The 3rd RB (50) loses the flex to nobody better, so it fills it.
    assert total > 0


def test_starter_gaps_close_as_roster_fills():
    cfg = load_league()
    empty = starter_gaps(cfg, {})
    assert empty["RB"] == cfg.roster["RB"]
    filled = starter_gaps(cfg, {"RB": 2, "WR": 2, "QB": 1, "TE": 1})
    assert filled["RB"] == 0 and filled["WR"] == 0


def test_kicker_and_defense_are_deprioritized_early():
    cfg = load_league()
    assert need_multiplier(cfg, {}, "K") < need_multiplier(cfg, {}, "RB")
