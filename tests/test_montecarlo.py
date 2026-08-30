"""The pick probability, and the properties that make it trustworthy."""
from dataclasses import dataclass, field

import numpy as np
import pytest

from ffcc.config import load_league
from ffcc.draft.montecarlo import _reach_index, _wants, simulate, value_share
from ffcc.draft.state import DraftState


@dataclass
class P:
    key: str
    name: str
    position: str
    proj_points: float
    vor: float
    adp: float
    adp_stdev: float = 3.0
    adp_high: int = 1
    adp_low: int = 200
    bye: int | None = None
    tier: int = 1


def board(n=60):
    out = []
    for i in range(n):
        pos = ("RB", "WR", "TE", "QB")[i % 4]
        out.append(P(key=f"p{i}|{pos}", name=f"Player {i}", position=pos,
                     proj_points=300.0 - i * 3, vor=150.0 - i * 2.0, adp=float(i + 1)))
    return out


@dataclass
class Rec:
    player: object
    score: float
    vona: float = 0.0
    survival_next: float = 0.0
    reasons: list = field(default_factory=list)
    warnings: list = field(default_factory=list)


def test_is_deterministic_under_a_fixed_seed():
    cfg, players = load_league(), board()
    st = DraftState(cfg)
    a = simulate(st, players, cfg, players[:5], sims=60, rng=np.random.default_rng(42))
    b = simulate(st, players, cfg, players[:5], sims=60, rng=np.random.default_rng(42))
    assert [(x.key, x.probability) for x in a] == [(x.key, x.probability) for x in b]


def test_a_strictly_better_candidate_wins_more_often():
    cfg, players = load_league(), board()
    st = DraftState(cfg)
    odds = {o.key: o.probability
            for o in simulate(st, players, cfg, players[:4], sims=120,
                              rng=np.random.default_rng(1))}
    assert odds[players[0].key] >= odds[players[3].key]


def test_probabilities_are_a_distribution():
    cfg, players = load_league(), board()
    st = DraftState(cfg)
    odds = simulate(st, players, cfg, players[:6], sims=80, rng=np.random.default_rng(3))
    total = sum(o.probability for o in odds)
    assert 0.98 <= total <= 1.02
    assert all(0.0 < o.probability < 1.0 for o in odds)


def test_a_clean_sweep_is_never_displayed_as_certainty():
    """Smoothing must keep a small sample from claiming 100%."""
    cfg, players = load_league(), board()
    st = DraftState(cfg)
    odds = simulate(st, players, cfg, players[:3], sims=40, rng=np.random.default_rng(9))
    assert max(o.probability for o in odds) < 1.0


def test_respects_its_time_budget():
    cfg, players = load_league(), board()
    st = DraftState(cfg)
    odds = simulate(st, players, cfg, players[:8], sims=100000, budget=0.35,
                    rng=np.random.default_rng(5))
    assert odds and odds[0].sims < 100000


def test_value_share_sums_to_one_and_favours_the_higher_score():
    players = board()
    recs = [Rec(player=players[0], score=90.0), Rec(player=players[1], score=40.0)]
    shares = value_share(recs)
    assert sum(shares.values()) == pytest.approx(1.0, abs=1e-3)
    assert shares[players[0].key] > shares[players[1].key]


def test_hazards_shift_the_simulated_probability():
    """Without this, the simulation ignores a real positional run happening
    in front of it and can contradict the tool's own survival numbers, which
    already adapt to exactly this signal."""
    cfg, players = load_league(), board()
    st = DraftState(cfg)
    candidates = players[:4]
    base = {o.key: o.probability
            for o in simulate(st, players, cfg, candidates, sims=150,
                              rng=np.random.default_rng(7))}
    hot = {o.key: o.probability
           for o in simulate(st, players, cfg, candidates, sims=150,
                             rng=np.random.default_rng(7),
                             hazards={"RB": 1.8, "WR": 0.5})}
    # An RB candidate should look meaningfully less safe to wait on once RBs
    # are known to be flying off the board faster than their ADP suggests.
    rb = next(c for c in candidates if c.position == "RB")
    assert hot[rb.key] != base[rb.key]


def test_wants_hard_caps_a_full_position():
    cfg = load_league()
    cap = cfg.roster.get("RB", 1) + 2   # RB is flex-eligible, so cap includes flex slots
    assert not _wants(cfg, {"RB": cap}, "RB")
    assert _wants(cfg, {"RB": cap - 1}, "RB")


def test_reach_index_prefers_a_position_with_an_unfilled_starter_gap():
    """A simulated opponent should reach a little for a real roster hole
    within the perceived-value window, not draft purely best-available --
    this is what makes opponents in the sim behave like real drafters."""
    cfg = load_league()
    pool = [
        P(key="rb|RB", name="RB Guy", position="RB", proj_points=200, vor=100, adp=1),
        P(key="wr|WR", name="WR Guy", position="WR", proj_points=190, vor=95, adp=2),
        P(key="qb|QB", name="QB Guy", position="QB", proj_points=180, vor=90, adp=3),
    ]
    board_order = np.array([0, 1, 2])
    taken = np.zeros(len(pool), dtype=bool)
    counts = {"RB": 2, "WR": 2}   # both starter slots already filled; QB still needed
    bi = _reach_index(cfg, counts, pool, board_order, taken)
    assert pool[bi].position == "QB"


def test_reach_index_falls_back_to_best_available_with_no_gap_in_window():
    cfg = load_league()
    pool = [
        P(key="rb|RB", name="RB Guy", position="RB", proj_points=200, vor=100, adp=1),
        P(key="wr|WR", name="WR Guy", position="WR", proj_points=190, vor=95, adp=2),
    ]
    board_order = np.array([0, 1])
    taken = np.zeros(len(pool), dtype=bool)
    bi = _reach_index(cfg, {}, pool, board_order, taken)
    assert pool[bi].position == "RB"
