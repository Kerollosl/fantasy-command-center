"""Multi-year production history: what each player actually did, per season.

Position rank is the number a drafter thinks in -- "he was RB1 two years ago"
carries more meaning than a point total, because it is already normalised for
the scoring era. Built once at snapshot and cached to disk so opening a profile
mid-draft costs nothing.
"""
from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass

from ..config import DATA_DIR, LeagueConfig
from ..identity.normalize import norm_name, norm_position
from ..projections.scoring import season_totals
from ..sources import nflverse

log = logging.getLogger(__name__)

# Seven seasons back. Deep enough to show a real career arc, recent enough that
# the league it describes still resembles the one being drafted.
DEFAULT_SEASONS = (2019, 2020, 2021, 2022, 2023, 2024, 2025)
RANKED_POSITIONS = ("QB", "RB", "WR", "TE")
CACHE = DATA_DIR / "production.json"

# One full tier of positional rank (~12 places) as a log distance, used to put
# the trajectory signal on a -1..1 scale.
LOG_TIER = math.log(12)


@dataclass(frozen=True)
class SeasonLine:
    season: int
    rank: int
    points: float
    games: int
    ppg: float

    def as_dict(self) -> dict:
        return {
            "season": self.season, "rank": self.rank, "points": self.points,
            "games": self.games, "ppg": self.ppg,
        }


def build(cfg: LeagueConfig, seasons=DEFAULT_SEASONS) -> dict[str, list[dict]]:
    """`"<norm_name>|<POS>" -> [season lines]`, most recent last."""
    out: dict[str, list[dict]] = {}
    for season in seasons:
        try:
            tot = season_totals(nflverse.weekly_stats(season), cfg.scoring)
        except Exception as exc:  # noqa: BLE001 - a missing season is not fatal
            log.warning("production history: season %s unavailable (%s)", season, exc)
            continue

        tot = tot.copy()
        tot["pos"] = tot["position"].map(norm_position)
        for pos in RANKED_POSITIONS:
            sub = tot[tot["pos"] == pos].sort_values("points", ascending=False)
            for rank, row in enumerate(sub.itertuples(), start=1):
                key = f"{norm_name(row.player_display_name)}|{pos}"
                games = int(row.games) or 1
                out.setdefault(key, []).append(
                    SeasonLine(
                        season=season, rank=rank, points=round(float(row.points), 1),
                        games=int(row.games), ppg=round(float(row.points) / games, 1),
                    ).as_dict()
                )
    for lines in out.values():
        lines.sort(key=lambda r: r["season"])
    return out


def load_or_build(cfg: LeagueConfig, refresh: bool = False) -> dict[str, list[dict]]:
    if not refresh and CACHE.exists():
        try:
            return json.loads(CACHE.read_text())
        except Exception:  # noqa: BLE001 - a corrupt cache should rebuild, not crash
            log.warning("production cache unreadable; rebuilding")
    data = build(cfg)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(json.dumps(data))
    return data


def trajectory(lines: list[dict]) -> float:
    """Direction of a player's positional rank, as a -1..1 signal.

    Positive means climbing. Uses rank rather than points so a league-wide
    scoring shift does not read as a player improving. Recent seasons dominate,
    and a season under six games is skipped -- an injury year says little about
    trajectory and would otherwise read as collapse.
    """
    usable = [ln for ln in lines if ln["games"] >= 6][-3:]
    if len(usable) < 2:
        return 0.0
    deltas, weights = [], []
    for i in range(1, len(usable)):
        prev, cur = usable[i - 1], usable[i]
        # Log scale, because rank is log-distributed in value: RB1 -> RB3 is a
        # small move at the elite end, while RB30 -> RB10 is a large one. A plain
        # relative change divides by the rank and reads RB1 -> RB3 as a 200%
        # collapse, which would mark a stable elite player as falling apart.
        rel = (math.log(max(prev["rank"], 1)) - math.log(max(cur["rank"], 1))) / LOG_TIER
        deltas.append(max(-1.0, min(1.0, rel)))
        weights.append(float(i))
    return round(sum(d * w for d, w in zip(deltas, weights)) / sum(weights), 3)
