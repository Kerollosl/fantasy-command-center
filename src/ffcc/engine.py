"""One place that assembles the board so every entry point agrees."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

import dataclasses
import datetime as _dt
import re

from .config import CONFIG_DIR, LeagueConfig, load_league
from .context.attach import attach_context, attach_handcuffs
from .context.signals import load_or_build as load_context
from .draft.state import DraftState
from .history.production import load_or_build as load_production
from .history.rounds import load_or_build as load_round_value
from .identity.resolver import ResolutionReport, build_players
from .sources import crosswalk, headshots, logos
from .projections.blend import attach_projections
from .projections.vor import attach_ranks, attach_tiers, attach_vor

log = logging.getLogger(__name__)


@dataclass
class Board:
    cfg: LeagueConfig
    players: list
    report: ResolutionReport
    replacement: dict[str, float]
    state: DraftState
    round_value: dict = field(default_factory=dict)

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
    attach_handcuffs(players)
    attach_projections(players, cfg.scoring, current_season=season, fmt=cfg.adp_format,
                       teams=cfg.teams, cfg=cfg)

    try:
        ctx = load_context(cfg, season=season)
        attach_context(players, ctx)
    except Exception:  # noqa: BLE001 - context is an enhancement, never a dependency
        log.warning("team-context signals unavailable; proceeding without them", exc_info=True)

    replacement = attach_vor(players, cfg)
    attach_tiers(players)
    attach_ranks(players)

    if report.unmatched_gsis:
        log.warning(
            "%d draftable players unresolved against nflverse: %s",
            len(report.unmatched_gsis), ", ".join(report.unmatched_gsis[:10]),
        )

    _attach_bio(players, season)

    try:
        round_value = load_round_value(cfg)
    except Exception:  # noqa: BLE001 - an insight is never worth failing a draft over
        round_value = {}

    return Board(cfg=cfg, players=players, report=report, replacement=replacement,
                 state=DraftState(cfg), round_value=round_value)


def _attach_bio(players, season: int) -> None:
    """Age and headshot, from the one roster file that carries both."""
    try:
        df = crosswalk.season_roster(season)
    except Exception:  # noqa: BLE001
        return

    from .identity.normalize import norm_name, norm_position

    bio: dict[tuple[str, str], dict] = {}
    for row in df.to_dict("records"):
        name = row.get("full_name")
        if not name:
            continue
        key = (norm_name(name), norm_position(row.get("position")))
        bd = row.get("birth_date")
        bio.setdefault(key, {
            "birth_date": bd if isinstance(bd, str) else None,
            "headshot": row.get("headshot_url") if isinstance(row.get("headshot_url"), str) else None,
        })

    today = _dt.date.today()
    for p in players:
        # Independent of the roster-bio match below: every player has a team,
        # including DEF entries, which never appear in the roster file at all.
        p.team_logo = logos.local_name(p.team)

        rec = bio.get((norm_name(p.name), p.position))
        if not rec:
            continue
        p.headshot = headshots.local_name(rec["headshot"]) or None
        p.birth_date = rec["birth_date"]
        if rec["birth_date"] and not p.age:
            try:
                b = _dt.date.fromisoformat(rec["birth_date"])
                p.age = today.year - b.year - ((today.month, today.day) < (b.month, b.day))
            except ValueError:
                pass


def cache_media(board: "Board", season: int = 2026) -> int:
    """Download headshots for the draftable board. Called by `ffcc snapshot`."""
    try:
        df = crosswalk.season_roster(season)
    except Exception:  # noqa: BLE001
        return 0

    from .identity.normalize import norm_name, norm_position

    want = {(norm_name(p.name), p.position) for p in board.players}
    urls = [
        r.get("headshot_url") for r in df.to_dict("records")
        if isinstance(r.get("headshot_url"), str)
        and (norm_name(r.get("full_name") or ""), norm_position(r.get("position"))) in want
    ]
    got = headshots.cache_all(urls)
    got_logos = logos.cache_all({p.team for p in board.players if p.team})
    _attach_bio(board.players, season)
    return len(got), len(got_logos)
