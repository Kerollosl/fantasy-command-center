"""The survival model is the backbone of every recommendation, so its
mathematical properties are asserted directly rather than eyeballed."""
from dataclasses import dataclass

import pytest

from ffcc.draft.survival import raw_survival, survival_prob


@dataclass
class P:
    adp: float
    adp_stdev: float
    adp_high: int
    adp_low: int
    position: str = "RB"


GIBBS = P(1.5, 0.7, 1, 4)
JEANTY = P(17.6, 5.6, 8, 40)
HENRY = P(17.4, 2.7, 11, 28)


def test_survival_is_monotonic_non_increasing():
    prev = 1.01
    for pick in range(1, 120):
        s = raw_survival(GIBBS, pick)
        assert s <= prev + 1e-9, f"survival rose at pick {pick}"
        prev = s


def test_survival_bounded_in_unit_interval():
    for p in (GIBBS, JEANTY, HENRY):
        for pick in (1, 5, 24, 60, 180):
            assert 0.0 <= raw_survival(p, pick) <= 1.0


def test_high_adp_player_gone_early():
    assert survival_prob(GIBBS, 24, 1) < 0.05


def test_variance_drives_survival_not_just_adp():
    """Jeanty and Henry have near-identical ADP; the high-variance one must be
    meaningfully likelier to last. This distinction is the whole point of
    modelling the distribution instead of using a rank."""
    assert abs(JEANTY.adp - HENRY.adp) < 1.0
    assert survival_prob(JEANTY, 24, 1) > 2 * survival_prob(HENRY, 24, 1)


def test_hazard_above_one_reduces_survival():
    base = survival_prob(JEANTY, 30, 12)
    hot = survival_prob(JEANTY, 30, 12, hazards={"RB": 1.8})
    cold = survival_prob(JEANTY, 30, 12, hazards={"RB": 0.5})
    assert hot < base < cold


def test_conditioning_never_exceeds_one():
    # A first-rounder somehow available deep should not produce a probability > 1.
    assert survival_prob(GIBBS, 80, 60) <= 1.0
