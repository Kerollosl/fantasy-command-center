"""One place that assembles the board so every entry point agrees."""
from __future__ import annotations

import logging
from dataclasses import dataclass

import dataclasses
import re

from .config import CONFIG_DIR, LeagueConfig, load_league
from .draft.state import DraftState
from .identity.resolver import ResolutionReport, build_players
from .projections.blend import attach_projections
from .projections.vor import attach_tiers, attach_vor

log = logging.getLogger(__name__)


@dataclass
class Board:
    cfg: LeagueConfig
    players: list
    report: ResolutionReport
    replacement: dict[str, float]
    state: DraftState

    def by_key(self) -> dict[str, object]:
        return {p.key: p for p in self.players}

    def find(self, query: str, limit: int = 8, available_only: bool = True) -> list:
        """Fuzzy-ish player search built for speed of entry under a draft clock.

        Ranks exact match, then prefix, then initials ("jg" -> Jahmyr Gibbs),
        then substring -- ADP order inside each band so the common case is first.
        """
        q = (query or "").strip().lower()
        if not q:
            return []
        pool = self.state.available(self.players) if available_only else self.players

        scored = []
        for p in pool:
            name = p.name.lower()
            parts = name.split()
            initials = "".join(w[0] for w in parts if w)
            last = parts[-1] if parts else ""
            if name == q:
                rank = 0
            elif last.startswith(q) or name.startswith(q):
                rank = 1
            elif q == initials:
                rank = 2
            elif q in name:
                rank = 3
            elif all(t in name for t in q.split()):
                rank = 4
            else:
                continue
            scored.append((rank, p.adp if p.adp is not None else 999, p))

        scored.sort(key=lambda t: (t[0], t[1]))
        return [p for _, _, p in scored[:limit]]


def set_draft_slot(board: "Board", slot: int, persist: bool = True) -> None:
    """Change which draft slot is mine, mid-draft if need be.

    Picks already recorded keep their own team_slot, so history is untouched --
    only the question of which column is *yours* changes, and every survival
    horizon, recommendation, and grade re-derives from it.
    """
    slot = max(1, min(int(slot), board.cfg.teams))
    board.cfg = dataclasses.replace(board.cfg, my_draft_slot=slot)
    board.state.cfg = board.cfg

    if not persist:
        return
    # Write it back so the setting survives a restart -- forgetting to set this
    # before a draft silently invalidates every number on the board.
    path = CONFIG_DIR / "league.yaml"
    try:
        # Rewrite just this one line. A safe_dump round-trip would silently strip
        # every comment out of the user's config file.
        text = path.read_text()
        lines = text.splitlines(keepends=True)
        for i, line in enumerate(lines):
            if re.match(r"^\s*my_draft_slot\s*:", line):
                head, _, tail = line.partition(":")
                comment = ""
                if "#" in tail:
                    comment = "  " + tail[tail.index("#"):].rstrip("\n")
                lines[i] = f"{head}: {slot}{comment}\n"
                path.write_text("".join(lines))
                return
    except Exception:  # noqa: BLE001 - a read-only config must not break the draft
        pass


def build_board(cfg: LeagueConfig | None = None, season: int = 2026) -> Board:
    cfg = cfg or load_league()
    players, report = build_players(
        league_adp_format=cfg.adp_format, teams=cfg.teams, year=season, current_season=season
    )
    attach_projections(players, cfg.scoring, current_season=season, fmt=cfg.adp_format,
                       teams=cfg.teams)
    replacement = attach_vor(players, cfg)
    attach_tiers(players)

    if report.unmatched_gsis:
        log.warning(
            "%d draftable players unresolved against nflverse: %s",
            len(report.unmatched_gsis), ", ".join(report.unmatched_gsis[:10]),
        )

    return Board(cfg=cfg, players=players, report=report, replacement=replacement,
                 state=DraftState(cfg))
