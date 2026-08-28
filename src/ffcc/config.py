"""League configuration. Everything downstream derives from this — no hardcoded league math."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = REPO_ROOT / "config"
DATA_DIR = REPO_ROOT / "data"
CACHE_DIR = DATA_DIR / "cache"

# Positions we actually value. DEF/K are drafted but modelled crudely on purpose.
SKILL_POSITIONS = ("QB", "RB", "WR", "TE")
ALL_POSITIONS = ("QB", "RB", "WR", "TE", "DEF", "K")


@dataclass(frozen=True)
class LeagueConfig:
    name: str
    teams: int
    rounds: int
    draft_type: str
    my_draft_slot: int
    roster: dict[str, int]
    flex_eligible: list[str]
    scoring: dict[str, float]
    adp_format: str

    @property
    def total_picks(self) -> int:
        return self.teams * self.rounds

    @property
    def starters_per_team(self) -> dict[str, int]:
        """Starting slots only, excluding bench."""
        return {k: v for k, v in self.roster.items() if k != "BENCH"}

    def replacement_rank(self, position: str) -> int:
        """How many of `position` are rostered as starters league-wide.

        This is the replacement level for VOR. FLEX is distributed across
        eligible positions by historical usage rather than split evenly,
        because flex is overwhelmingly RB/WR in practice.
        """
        base = self.roster.get(position, 0) * self.teams
        flex_slots = self.roster.get("FLEX", 0) * self.teams
        if flex_slots and position in self.flex_eligible:
            # Empirical flex distribution: RB and WR absorb nearly all of it.
            share = {"RB": 0.45, "WR": 0.45, "TE": 0.10}.get(position, 0.0)
            base += round(flex_slots * share)
        return max(base, 1)

    def snake_order(self) -> list[int]:
        """Draft slot (1-indexed) owning each overall pick, in order."""
        order: list[int] = []
        for rnd in range(self.rounds):
            slots = list(range(1, self.teams + 1))
            if rnd % 2 == 1:
                slots.reverse()
            order.extend(slots)
        return order

    def my_pick_numbers(self) -> list[int]:
        """Overall pick numbers (1-indexed) that belong to me."""
        return [i + 1 for i, slot in enumerate(self.snake_order()) if slot == self.my_draft_slot]


@dataclass
class Overrides:
    aliases: list[dict] = field(default_factory=list)
    exclude: list[str] = field(default_factory=list)


def load_league(path: Path | None = None) -> LeagueConfig:
    path = path or CONFIG_DIR / "league.yaml"
    raw = yaml.safe_load(path.read_text())
    return LeagueConfig(
        name=raw["name"],
        teams=int(raw["teams"]),
        rounds=int(raw["rounds"]),
        draft_type=raw.get("draft_type", "snake"),
        my_draft_slot=int(raw.get("my_draft_slot", 1)),
        roster=dict(raw["roster"]),
        flex_eligible=list(raw.get("flex_eligible", ["RB", "WR", "TE"])),
        scoring={k: float(v) for k, v in raw["scoring"].items()},
        adp_format=raw.get("adp_format", "ppr"),
    )


def load_overrides(path: Path | None = None) -> Overrides:
    path = path or CONFIG_DIR / "overrides.yaml"
    if not path.exists():
        return Overrides()
    raw = yaml.safe_load(path.read_text()) or {}
    return Overrides(aliases=raw.get("aliases") or [], exclude=raw.get("exclude") or [])
