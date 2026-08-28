"""Live draft state: the board, every roster, and whose turn it is."""
from __future__ import annotations

from dataclasses import dataclass, field

from ..config import LeagueConfig


@dataclass
class Pick:
    overall: int          # 1-indexed overall pick number
    team_slot: int        # 1-indexed draft slot that made it
    player_key: str
    player_name: str
    position: str


@dataclass
class DraftState:
    cfg: LeagueConfig
    picks: list[Pick] = field(default_factory=list)
    _order: list[int] = field(default_factory=list)

    def __post_init__(self):
        if not self._order:
            self._order = self.cfg.snake_order()

    # --- position in the draft ---
    @property
    def current_pick(self) -> int:
        return len(self.picks) + 1

    @property
    def is_complete(self) -> bool:
        return len(self.picks) >= self.cfg.total_picks

    def slot_on_clock(self) -> int | None:
        if self.is_complete:
            return None
        return self._order[self.current_pick - 1]

    def is_my_turn(self) -> bool:
        return self.slot_on_clock() == self.cfg.my_draft_slot

    def next_pick_for(self, slot: int, after: int | None = None) -> int | None:
        """Next overall pick number belonging to `slot`, strictly after `after`."""
        start = (after if after is not None else self.current_pick - 1)
        for i in range(start, len(self._order)):
            if self._order[i] == slot:
                return i + 1
        return None

    def my_next_pick(self) -> int | None:
        return self.next_pick_for(self.cfg.my_draft_slot)

    def my_pick_after_next(self) -> int | None:
        n = self.my_next_pick()
        return self.next_pick_for(self.cfg.my_draft_slot, after=n) if n else None

    def picks_until_my_next(self) -> int:
        n = self.my_next_pick()
        return max((n - self.current_pick), 0) if n else 0

    # --- mutation ---
    def drafted_keys(self) -> set[str]:
        return {p.player_key for p in self.picks}

    def record(self, player, slot: int | None = None) -> Pick:
        if self.is_complete:
            raise ValueError("draft is already complete")
        if player.key in self.drafted_keys():
            raise ValueError(f"{player.name} has already been drafted")
        pick = Pick(
            overall=self.current_pick,
            team_slot=slot if slot is not None else self.slot_on_clock(),
            player_key=player.key,
            player_name=player.name,
            position=player.position,
        )
        self.picks.append(pick)
        return pick

    def undo(self) -> Pick | None:
        return self.picks.pop() if self.picks else None

    # --- rosters ---
    def roster(self, slot: int) -> list[Pick]:
        return [p for p in self.picks if p.team_slot == slot]

    def position_counts(self, slot: int) -> dict[str, int]:
        counts: dict[str, int] = {}
        for p in self.roster(slot):
            counts[p.position] = counts.get(p.position, 0) + 1
        return counts

    def available(self, players):
        taken = self.drafted_keys()
        return [p for p in players if p.key not in taken]

    def recent_positions(self, n: int = 8) -> list[str]:
        return [p.position for p in self.picks[-n:]]
