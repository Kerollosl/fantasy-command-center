"""Manual CSV import — the path that works with no API access at all.

Columns: season, round, overall, franchise, player, position, is_me, finish
Only season, round and player are strictly required; the rest are inferred.
"""
from __future__ import annotations

import csv
from pathlib import Path

from ..schema import HistoricalPick, HistoricalSeason, HistoryBundle


def _truthy(v) -> bool:
    return str(v or "").strip().lower() in {"1", "true", "yes", "y", "me"}


class ManualImporter:
    def __init__(self, path: Path):
        self.path = Path(path)

    def available(self) -> bool:
        return self.path.exists()

    def load(self) -> HistoryBundle:
        by_season: dict[int, HistoricalSeason] = {}
        with self.path.open() as fh:
            for row in csv.DictReader(fh):
                if not row.get("player") or not row.get("season"):
                    continue
                season = int(row["season"])
                s = by_season.setdefault(
                    season,
                    HistoricalSeason(
                        season=season,
                        league_name=row.get("league") or "My League",
                        teams=int(row["teams"]) if row.get("teams") else 12,
                        my_finish=int(row["finish"]) if row.get("finish") else None,
                    ),
                )
                rnd = int(row["round"]) if row.get("round") else 0
                s.picks.append(
                    HistoricalPick(
                        season=season,
                        overall=int(row["overall"]) if row.get("overall") else 0,
                        round=rnd,
                        franchise=row.get("franchise") or ("me" if _truthy(row.get("is_me")) else "?"),
                        player_name=row["player"].strip(),
                        position=(row.get("position") or "").upper(),
                        is_me=_truthy(row.get("is_me")),
                    )
                )
        return HistoryBundle(seasons=[by_season[k] for k in sorted(by_season)])
