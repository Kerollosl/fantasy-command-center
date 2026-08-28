"""Production history and the trajectory signal."""
import pytest

from ffcc.config import load_league
from ffcc.history.production import build, trajectory


@pytest.fixture(scope="module")
def hist():
    return build(load_league(), seasons=(2023, 2024, 2025))


def test_known_finish_is_correct(hist):
    lines = hist["christian mccaffrey|RB"]
    y2025 = next(l for l in lines if l["season"] == 2025)
    assert y2025["rank"] == 1
    assert y2025["points"] == pytest.approx(416.6, abs=0.5)


def test_seasons_are_chronological(hist):
    for lines in list(hist.values())[:50]:
        assert [l["season"] for l in lines] == sorted(l["season"] for l in lines)


def test_trajectory_uses_log_scale_not_raw_rank():
    """RB1 -> RB3 is a small move at the elite end. A plain relative change
    divides by the rank and reads it as a 200% collapse, which would mark a
    stable elite player as falling apart."""
    stable = [
        {"season": 2023, "rank": 10, "games": 16},
        {"season": 2024, "rank": 1, "games": 17},
        {"season": 2025, "rank": 3, "games": 17},
    ]
    assert trajectory(stable) > -0.15


def test_trajectory_detects_a_real_climb():
    climbing = [
        {"season": 2023, "rank": 60, "games": 15},
        {"season": 2024, "rank": 30, "games": 16},
        {"season": 2025, "rank": 8, "games": 17},
    ]
    assert trajectory(climbing) > 0.2


def test_injury_seasons_do_not_read_as_decline():
    lines = [
        {"season": 2023, "rank": 2, "games": 16},
        {"season": 2024, "rank": 70, "games": 3},   # injured, must be skipped
        {"season": 2025, "rank": 1, "games": 17},
    ]
    assert trajectory(lines) >= 0.0


def test_too_little_history_is_neutral():
    assert trajectory([]) == 0.0
    assert trajectory([{"season": 2025, "rank": 5, "games": 17}]) == 0.0
