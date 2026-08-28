"""Aging curves must come from paired within-player deltas.

Averaging points-per-game by age is survivorship-biased: fitted that way this
same data claims receivers peak at 21 and tight ends at 32, because only the
good ones are still playing. These tests pin the properties the correct method
produces and the biased one does not.
"""
import pytest

from ffcc.config import load_league
from ffcc.projections.aging import fit, multiplier


@pytest.fixture(scope="module")
def curves():
    return fit(load_league())


def test_running_backs_decline_through_their_late_twenties(curves):
    assert multiplier(curves, "RB", 28) < 1.0
    assert multiplier(curves, "RB", 28) < multiplier(curves, "RB", 23)


def test_quarterbacks_age_better_than_running_backs(curves):
    assert multiplier(curves, "QB", 28) > multiplier(curves, "RB", 28)


def test_beyond_the_fitted_range_decline_is_carried_forward(curves):
    """Returning 1.0 for a 34-year-old back would claim he does not age."""
    assert multiplier(curves, "RB", 34) < 1.0


def test_unknown_age_or_position_is_neutral(curves):
    assert multiplier(curves, "RB", None) == 1.0
    assert multiplier(curves, "LB", 25) == 1.0
    assert multiplier({}, "RB", 25) == 1.0
