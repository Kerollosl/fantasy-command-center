import pytest

from ffcc.identity.normalize import norm_name, norm_position, norm_team


@pytest.mark.parametrize("raw,expected", [
    ("Ja'Marr Chase", "jamarr chase"),
    ("Travis Etienne Jr.", "travis etienne"),
    ("Kenneth Walker III", "kenneth walker"),
    ("Amon-Ra St. Brown", "amon ra st brown"),
    ("Hollywood Brown", "marquise brown"),      # nickname alias
])
def test_norm_name(raw, expected):
    assert norm_name(raw) == expected


@pytest.mark.parametrize("raw,expected", [
    ("JAC", "JAX"), ("LA", "LAR"), ("WSH", "WAS"), ("OAK", "LV"), ("SD", "LAC"),
])
def test_norm_team(raw, expected):
    assert norm_team(raw) == expected


def test_norm_position_collapses_source_spellings():
    assert norm_position("PK") == "K"
    assert norm_position("DST") == "DEF"
    assert norm_position("FB") == "RB"
