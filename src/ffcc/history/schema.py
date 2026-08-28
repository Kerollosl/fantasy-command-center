"""One internal shape that every history importer normalizes into.

Manual CSV works today, Sleeper works today, Yahoo slots in behind the same
interface whenever its application review clears. Nothing downstream knows or
cares which one produced the data.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class HistoricalPick:
    season: int
    overall: int
    round: int
    franchise: str
    player_name: str
    position: str = ""
    is_me: bool = False


@dataclass
class HistoricalSeason:
    season: int
    league_name: str
    teams: int
    picks: list[HistoricalPick] = field(default_factory=list)
    my_finish: int | None = None


@dataclass
class HistoryBundle:
    seasons: list[HistoricalSeason] = field(default_factory=list)

    def my_picks(self) -> list[HistoricalPick]:
        return [p for s in self.seasons for p in s.picks if p.is_me]


class HistoryImporter(Protocol):
    def available(self) -> bool: ...
    def load(self) -> HistoryBundle: ...
