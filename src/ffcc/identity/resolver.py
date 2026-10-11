"""Unify FFC + Sleeper + nflverse into one canonical player table.

This is the highest-risk module in the system. The source ID crosswalks are
genuinely incomplete: Sleeper carries yahoo_id for only ~55% of players and
gsis_id for ~32%, and Jahmyr Gibbs — the #1 ADP player in 2026 — has none of
yahoo_id, gsis_id, or espn_id. So we match on a cascade of keys and report
every failure loudly instead of silently dropping a player off the board.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

from ..config import Overrides, load_overrides
from ..sources import ffc as ffc_src
from ..sources import crosswalk, nflverse, sleeper
from .normalize import norm_name, norm_position, norm_team

log = logging.getLogger(__name__)


@dataclass
class Player:
    """One draftable player, unified across sources."""
    key: str                  # canonical id: "<norm_name>|<pos>"
    name: str
    position: str
    team: str
    bye: int | None = None

    # market
    adp: float | None = None
    adp_stdev: float | None = None
    adp_high: int | None = None
    adp_low: int | None = None
    times_drafted: int = 0

    # cross-source ids
    sleeper_id: str | None = None
    gsis_id: str | None = None
    yahoo_id: str | None = None
    espn_id: str | None = None

    # live status
    injury_status: str | None = None
    depth_chart_order: int | None = None
    age: int | None = None
    years_exp: int | None = None

    # projections filled in later
    proj_points: float = 0.0
    proj_market: float = 0.0
    proj_baseline: float = 0.0
    history_weight: float = 0.0
    evidence_games: int = 0
    trajectory: float = 0.0
    seasons: list = field(default_factory=list)
    adjustments: list = field(default_factory=list)
    headshot: str | None = None
    headshot_url: str | None = None   # live CDN thumbnail -- fallback when the local cache is stale
    birth_date: str | None = None
    team_logo: str | None = None

    # Board-wide rank context, filled in by projections.vor.attach_ranks and
    # projections.blend.attach_projections.
    predicted_rank: int | None = None    # this season's positional rank by ADP
    last_year_rank: int | None = None    # positional finish rank, most recent completed season
    predicted_rank_overall: int | None = None   # this season's rank by ADP, all positions
    last_year_rank_overall: int | None = None   # finish rank by points, all positions, last season
    vor: float = 0.0
    tier: int = 0

    # team context, filled in by context.attach.attach_context
    oline_rank: int | None = None          # 1-32, this team's O-line last season (1 = best)
    oline_score: float | None = None
    oline_continuity: float | None = None  # 0-1, fraction of last season's starting five still on the roster
    oline_returning: int | None = None
    oline_total: int | None = None
    oline_departed: list = field(default_factory=list)
    sos_rank: int | None = None            # 1-32, this season's schedule vs this position (1 = easiest)
    sos_score: float | None = None
    playoff_sos_rank: int | None = None    # 1-32, schedule across fantasy-playoff weeks 15-17 only
    playoff_sos_score: float | None = None
    vacated_share: float | None = None     # 0-1, share of last season's team volume at this position now gone
    vacated_departed: list = field(default_factory=list)
    redzone_share: float | None = None     # 0-1, share of his team's red-zone touches last season
    redzone_touches: int | None = None

    # QB only, filled in by context.attach.attach_context -- pass-game weapons
    # this team added and lost since last season (display only, no proj input).
    weapons_added: list = field(default_factory=list)
    weapons_lost: list = field(default_factory=list)
    weapons_added_total: int | None = None
    weapons_lost_total: int | None = None

    # career durability, filled in by context.attach.attach_context -- display
    # only, never a proj_points input (baseline_projection already discounts
    # for missed games via its own exp_games calculation)
    durability: float | None = None        # 0-1, career-average share of a season's games played
    durability_seasons: int | None = None

    # handcuff, filled in by context.attach.attach_handcuffs (RB only)
    handcuff_key: str | None = None
    handcuff_name: str | None = None

    @property
    def is_risky(self) -> bool:
        return (self.injury_status or "") in sleeper.RISK_STATUSES


@dataclass
class ResolutionReport:
    """What matched and what did not. Surfaced at startup — never swallowed."""
    total: int = 0
    matched_sleeper: int = 0
    matched_gsis: int = 0
    matched_yahoo: int = 0
    unmatched_sleeper: list[str] = field(default_factory=list)
    unmatched_gsis: list[str] = field(default_factory=list)

    def summary(self) -> str:
        return (
            f"resolved {self.total} draftable players | "
            f"sleeper {self.matched_sleeper}/{self.total} | "
            f"nflverse {self.matched_gsis}/{self.total} | "
            f"yahoo-id {self.matched_yahoo}/{self.total}"
        )


def _index(rows, name_fn, pos_fn, team_fn):
    """Build (name,pos) -> row and name -> [rows] indexes for cascade matching."""
    by_name_pos: dict[tuple[str, str], object] = {}
    by_name: dict[str, list] = {}
    for r in rows:
        n, p = name_fn(r), pos_fn(r)
        if not n:
            continue
        by_name_pos.setdefault((n, p), r)
        by_name.setdefault(n, []).append(r)
    return by_name_pos, by_name


def _lookup(name: str, pos: str, team: str, by_name_pos, by_name):
    """Cascade: (name+pos) -> (name+team) -> unique name -> None."""
    hit = by_name_pos.get((name, pos))
    if hit is not None:
        return hit
    cands = by_name.get(name) or []
    if len(cands) == 1:
        return cands[0]
    return None


def build_players(
    league_adp_format: str = "ppr",
    teams: int = 12,
    year: int = 2026,
    overrides: Overrides | None = None,
    current_season: int = 2026,
) -> tuple[list[Player], ResolutionReport]:
    """Build the canonical draftable player list from ADP outward."""
    ov = overrides or load_overrides()
    alias_map = {
        norm_name(a["ffc_name"]): norm_name(a["nflverse_name"])
        for a in ov.aliases
        if a.get("ffc_name") and a.get("nflverse_name")
    }
    excluded = {norm_name(x) for x in ov.exclude}

    adp_entries, _meta = ffc_src.fetch_adp(fmt=league_adp_format, teams=teams, year=year)

    sp = sleeper.all_players()
    sleeper_rows = [
        {
            "id": pid,
            "n": norm_name(v.get("full_name") or f"{v.get('first_name','')} {v.get('last_name','')}"),
            "p": norm_position(v.get("position")),
            "t": norm_team(v.get("team")),
            "raw": v,
        }
        for pid, v in sp.items()
    ]
    s_np, s_n = _index(sleeper_rows, lambda r: r["n"], lambda r: r["p"], lambda r: r["t"])

    nv = nflverse.players()
    nv_rows = [
        {
            "gsis": r.get("gsis_id"),
            "n": norm_name(r.get("display_name")),
            "p": norm_position(r.get("position")),
            "t": norm_team(r.get("latest_team")),
        }
        for r in nv.to_dict("records")
        if r.get("gsis_id")
    ]
    n_np, n_n = _index(nv_rows, lambda r: r["n"], lambda r: r["p"], lambda r: r["t"])

    # roster_{season} carries every id on one row -- the only source that ties
    # yahoo_id to gsis_id, which is what the future Yahoo importer will join on.
    def _s(v):
        return None if v is None or str(v) in {"nan", "NA", ""} else str(v).split(".")[0]

    xw = crosswalk.season_roster(current_season)
    xw_rows = [
        {
            "n": norm_name(r.get("full_name")),
            "p": norm_position(r.get("position")),
            "t": norm_team(r.get("team")),
            "gsis": _s(r.get("gsis_id")),
            "yahoo": _s(r.get("yahoo_id")),
            "espn": _s(r.get("espn_id")),
            "sleeper": _s(r.get("sleeper_id")),
        }
        for r in (xw.to_dict("records") if len(xw) else [])
    ]
    x_np, x_n = _index(xw_rows, lambda r: r["n"], lambda r: r["p"], lambda r: r["t"])

    players: list[Player] = []
    rep = ResolutionReport()

    for e in adp_entries:
        nn = norm_name(e.name)
        if nn in excluded:
            continue
        nn = alias_map.get(nn, nn)
        pos = norm_position(e.position)
        team = norm_team(e.team)

        p = Player(
            key=f"{nn}|{pos}",
            name=e.name,
            position=pos,
            team=team,
            bye=e.bye,
            adp=e.adp,
            adp_stdev=e.stdev,
            adp_high=e.high,
            adp_low=e.low,
            times_drafted=e.times_drafted,
        )
        rep.total += 1

        # DEF/K never join cleanly to player tables and don't need to.
        if pos in {"DEF", "K"}:
            players.append(p)
            continue

        srow = _lookup(nn, pos, team, s_np, s_n)
        if srow:
            raw = srow["raw"]
            p.sleeper_id = srow["id"]
            p.injury_status = raw.get("injury_status")
            p.depth_chart_order = raw.get("depth_chart_order")
            p.age = raw.get("age")
            p.years_exp = raw.get("years_exp")
            rep.matched_sleeper += 1
        else:
            rep.unmatched_sleeper.append(f"{e.name} ({pos}, {team})")

        xrow = _lookup(nn, pos, team, x_np, x_n)
        if xrow:
            p.gsis_id = p.gsis_id or xrow["gsis"]
            p.yahoo_id = xrow["yahoo"]
            p.espn_id = xrow["espn"]
            p.sleeper_id = p.sleeper_id or xrow["sleeper"]
            if xrow["yahoo"]:
                rep.matched_yahoo += 1

        nrow = _lookup(nn, pos, team, n_np, n_n)
        if nrow:
            p.gsis_id = p.gsis_id or nrow["gsis"]
            rep.matched_gsis += 1
        elif p.gsis_id:
            rep.matched_gsis += 1
        else:
            rep.unmatched_gsis.append(f"{e.name} ({pos}, {team})")

        players.append(p)

    return players, rep
