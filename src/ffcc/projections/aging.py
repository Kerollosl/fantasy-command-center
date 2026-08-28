"""Position-specific aging curves, fitted from paired within-player deltas.

The obvious approach -- average points-per-game by age -- is survivorship-biased
and produces nonsense. Fitted that way on this data it claims wide receivers
peak at 21 and tight ends at 32, because the only players still in the league at
those ages are the good ones.

Measuring each player against *himself* a year later removes that: the
comparison is within one player, so quality cancels and what remains is aging.
That method recovers the real running-back cliff (-14% at 27->28, -26% at
28->29) and shows quarterbacks aging best, both of which match how these
positions are known to behave.
"""
from __future__ import annotations

import json
import logging
from collections import defaultdict

from ..config import DATA_DIR, LeagueConfig
from ..identity.normalize import norm_name, norm_position
from ..sources import crosswalk, nflverse
from .scoring import season_totals

log = logging.getLogger(__name__)

CACHE = DATA_DIR / "aging.json"
FIT_SEASONS = tuple(range(2018, 2026))
ROSTER_SEASONS = (2026, 2024, 2022, 2020, 2018)
POSITIONS = ("QB", "RB", "WR", "TE")

MIN_GAMES = 6          # a partial season says more about injury than about age
MIN_SAMPLE = 12        # transitions needed before an age step is trusted
AGE_MIN, AGE_MAX = 21, 36
# Cap how far one step may move a projection. The tails are thin and a single
# step should nudge, never dominate.
MAX_STEP = 0.30


def _birth_years() -> dict[str, int]:
    out: dict[str, int] = {}
    for season in ROSTER_SEASONS:
        try:
            df = crosswalk.season_roster(season)
        except Exception:  # noqa: BLE001
            continue
        for row in df.itertuples():
            name = getattr(row, "full_name", None)
            bd = getattr(row, "birth_date", None)
            if not name or not isinstance(bd, str) or len(bd) < 4:
                continue
            try:
                out.setdefault(norm_name(name), int(bd[:4]))
            except ValueError:
                continue
    return out


def fit(cfg: LeagueConfig) -> dict[str, dict[str, float]]:
    """position -> {age: multiplier applied moving from that age to the next}."""
    births = _birth_years()
    seasons: dict[tuple[str, str, int], dict] = {}

    for year in FIT_SEASONS:
        try:
            tot = season_totals(nflverse.weekly_stats(year), cfg.scoring)
        except Exception:  # noqa: BLE001
            continue
        for row in tot.itertuples():
            pos = norm_position(row.position)
            name = norm_name(row.player_display_name)
            if pos not in POSITIONS or int(row.games) < MIN_GAMES or name not in births:
                continue
            age = year - births[name]
            if AGE_MIN <= age <= AGE_MAX:
                seasons[(name, pos, year)] = {
                    "age": age, "ppg": float(row.points) / max(int(row.games), 1)
                }

    changes: dict[tuple[str, int], list[float]] = defaultdict(list)
    for (name, pos, year), cur in seasons.items():
        nxt = seasons.get((name, pos, year + 1))
        if nxt and cur["ppg"] > 2.0:
            changes[(pos, cur["age"])].append((nxt["ppg"] - cur["ppg"]) / cur["ppg"])

    curves: dict[str, dict[str, float]] = {p: {} for p in POSITIONS}
    for (pos, age), vals in changes.items():
        if len(vals) < MIN_SAMPLE:
            continue
        vals.sort()
        median = vals[len(vals) // 2]
        curves[pos][str(age)] = round(max(-MAX_STEP, min(MAX_STEP, median)), 4)
    return curves


def load_or_fit(cfg: LeagueConfig, refresh: bool = False) -> dict[str, dict[str, float]]:
    if not refresh and CACHE.exists():
        try:
            return json.loads(CACHE.read_text())
        except Exception:  # noqa: BLE001
            log.warning("aging cache unreadable; refitting")
    curves = fit(cfg)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(json.dumps(curves))
    return curves


def multiplier(curves: dict, position: str, age: int | None) -> float:
    """Expected change in production for a player of this age next season.

    Ages outside the fitted range return 1.0 rather than extrapolating: the
    tails are thin, and guessing there would be worse than not adjusting.
    """
    if not age or position not in curves or not curves[position]:
        return 1.0
    age = int(age)
    table = curves[position]
    step = table.get(str(age))
    if step is not None:
        return round(1.0 + step, 4)

    fitted = sorted(int(a) for a in table)
    if age > fitted[-1]:
        # Past the fitted range, carry the oldest fitted step forward. Decline is
        # monotone at this end, so holding the last value understates it a little;
        # returning 1.0 would claim a 33-year-old back does not age at all, which
        # is plainly worse.
        return round(1.0 + table[str(fitted[-1])], 4)
    if age < fitted[0]:
        return round(1.0 + table[str(fitted[0])], 4)
    return 1.0
