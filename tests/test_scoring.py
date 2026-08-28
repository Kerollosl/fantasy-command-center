"""Scoring is validated against a real, known outcome rather than a synthetic
fixture, so a change in either our math or nflverse's columns fails loudly."""
import pytest

from ffcc.config import load_league
from ffcc.projections.scoring import season_totals
from ffcc.sources import nflverse


@pytest.fixture(scope="module")
def totals_2025():
    cfg = load_league()
    return season_totals(nflverse.weekly_stats(2025), cfg.scoring)


def test_mccaffrey_2025_ppr_total(totals_2025):
    row = totals_2025[totals_2025.player_display_name == "Christian McCaffrey"]
    assert not row.empty
    assert row.points.iloc[0] == pytest.approx(416.6, abs=0.5)


def test_ppr_reception_scoring_is_actually_applied(totals_2025):
    cfg = load_league()
    assert cfg.scoring["receptions"] == 1.0
    # A high-volume receiver must clear a total only reachable with PPR.
    nacua = totals_2025[totals_2025.player_display_name == "Puka Nacua"]
    assert nacua.points.iloc[0] > 300
