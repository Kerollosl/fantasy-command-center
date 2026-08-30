"""Team-level context beyond a player's own stat line: O-line strength, this
season's schedule difficulty by position, and offseason-vacated volume.

None of this is a market signal like ADP, so it has to be derived from the
same free nflverse releases the rest of the app already trusts -- play-by-play
for O-line proxies, the release schedule for strength-of-schedule, and a
roster diff (last season's usage vs this season's roster) for what a team
lost. Built once at snapshot time and cached, same as production history and
round-value insight: an enhancement, never a draft-day dependency.
"""
from __future__ import annotations

import json
import logging

import numpy as np
import pandas as pd

from ..config import DATA_DIR, LeagueConfig
from ..identity.normalize import norm_team
from ..projections.scoring import score_frame
from ..sources import nflverse

log = logging.getLogger(__name__)

CACHE = DATA_DIR / "context.json"

SOS_POSITIONS = ("QB", "RB", "WR", "TE")
VACATED_VOLUME_COL = {"RB": "carries", "WR": "targets", "TE": "targets"}
OLINE_SNAP_POSITIONS = ("OL", "T", "G", "C")


def _zscore(s: pd.Series) -> pd.Series:
    sd = s.std()
    return (s - s.mean()) / sd if sd else s * 0.0


def _oline_scores(prior_season: int) -> dict:
    """Pass-block + run-block proxy from play-by-play: sack/hit rate and
    stuffed-run rate allowed, each z-scored and averaged. No public free
    source publishes real O-line grades, so this stands in for one.
    """
    df = nflverse.pbp(prior_season)
    df = df[(df.season_type == "REG") & df.posteam.notna()].copy()
    df["posteam"] = df.posteam.map(norm_team)

    pass_plays = df[(df.pass_attempt == 1) | (df.sack == 1)]
    pb = pass_plays.groupby("posteam").agg(
        dropbacks=("posteam", "size"), sacks=("sack", "sum"), hits=("qb_hit", "sum"),
    )
    pb["pressure_rate"] = (pb.sacks + pb.hits) / pb.dropbacks.clip(lower=1)

    rush_plays = df[df.rush_attempt == 1]
    rb = rush_plays.groupby("posteam").agg(
        rushes=("posteam", "size"),
        stuffed=("rushing_yards", lambda s: int((s <= 0).sum())),
    )
    rb["stuff_rate"] = rb.stuffed / rb.rushes.clip(lower=1)

    combo = pb.join(rb, how="outer")
    combo["score"] = (
        0.5 * _zscore(-combo.pressure_rate).fillna(0.0)
        + 0.5 * _zscore(-combo.stuff_rate).fillna(0.0)
    )
    ranked = combo["score"].sort_values(ascending=False)
    rank = {team: i + 1 for i, team in enumerate(ranked.index)}

    out = {}
    for team, row in combo.iterrows():
        out[team] = {
            "score": round(float(row["score"]), 2),
            "rank": rank.get(team),
            "pressure_rate": None if pd.isna(row.pressure_rate) else round(float(row.pressure_rate), 3),
            "stuff_rate": None if pd.isna(row.stuff_rate) else round(float(row.stuff_rate), 3),
        }
    return out


def _oline_continuity(prior_season: int, season: int) -> dict:
    """Of last season's five most-used linemen, how many are still on this
    team's roster. A quality O-line that lost its starters is not the same
    bet as one that kept them -- this is the "did it stay intact" half.

    Snap counts key players by pfr_id; a preseason roster snapshot only has
    gsis_id reliably populated (pfr_id lags real-world signings by weeks), so
    the join goes through nflverse's own pfr_id -> gsis_id crosswalk rather
    than matching snap_counts.pfr_player_id straight against roster.pfr_id.
    """
    pfr_to_gsis = (
        nflverse.players()[["pfr_id", "gsis_id"]].dropna()
        .drop_duplicates("pfr_id").set_index("pfr_id")["gsis_id"].to_dict()
    )

    snaps = nflverse.snap_counts(prior_season)
    snaps = snaps[snaps.position.isin(OLINE_SNAP_POSITIONS)].copy()
    snaps["team"] = snaps.team.map(norm_team)
    snaps["gsis_id"] = snaps.pfr_player_id.map(pfr_to_gsis)
    usage = snaps.groupby(["team", "player", "gsis_id"], as_index=False)["offense_pct"].mean()

    ros = nflverse.rosters(season)
    ros = ros[ros.season == season].copy()
    ros["team"] = ros.team.map(norm_team)
    current_by_team = ros.groupby("team")["gsis_id"].apply(lambda s: set(s.dropna())).to_dict()

    out = {}
    for team, grp in usage.groupby("team"):
        starters = grp.sort_values("offense_pct", ascending=False).head(5)
        current = current_by_team.get(team, set())
        back = starters.gsis_id.notna() & starters.gsis_id.isin(current)
        returning = int(back.sum())
        out[team] = {
            "returning": returning,
            "total": int(len(starters)),
            "continuity": round(returning / len(starters), 2) if len(starters) else None,
            "departed": starters.loc[~back, "player"].tolist(),
        }
    return out


PLAYOFF_WEEKS = frozenset({15, 16, 17})


def _defense_quality(cfg: LeagueConfig, prior_season: int) -> dict:
    """Per position: each defense's fantasy points allowed per game last
    season, z-scored. Shared baseline for both the full-season and the
    fantasy-playoffs-only schedule cut below -- only the opponent list
    differs between them, not the quality read on each defense.
    """
    weekly = nflverse.weekly_stats(prior_season)
    reg = weekly[weekly.season_type == "REG"].copy()
    reg["opponent_team"] = reg.opponent_team.map(norm_team)
    reg["fantasy_points"] = score_frame(reg, cfg.scoring)

    allowed = (
        reg[reg.position.isin(SOS_POSITIONS)]
        .groupby(["opponent_team", "position"])["fantasy_points"].sum()
        .unstack(fill_value=0.0)
    )
    games_played = reg.groupby("opponent_team")["week"].nunique()
    allowed_pg = allowed.div(games_played, axis=0)

    return {pos: _zscore(allowed_pg[pos]) for pos in SOS_POSITIONS if pos in allowed_pg.columns}


def _sos_from_schedule(z_by_pos: dict, season: int, weeks: frozenset | None = None) -> tuple[dict, dict]:
    """Average a team's opponents' defense-quality z-scores over the games
    that fall in `weeks` (None = every regular-season game). Returns
    (score, rank) -- rank 1 is the easiest slate for that position.
    """
    games = nflverse.schedules()
    sched = games[(games.season == season) & (games.game_type == "REG")]
    if weeks is not None:
        sched = sched[sched.week.isin(weeks)]
    opponents: dict[str, list[str]] = {}
    for row in sched.itertuples():
        home, away = norm_team(row.home_team), norm_team(row.away_team)
        opponents.setdefault(home, []).append(away)
        opponents.setdefault(away, []).append(home)

    score: dict[str, dict[str, float]] = {}
    for team, opps in opponents.items():
        score[team] = {}
        for pos, z in z_by_pos.items():
            vals = [z.get(o) for o in opps if o in z.index]
            vals = [v for v in vals if pd.notna(v)]
            score[team][pos] = round(float(np.mean(vals)), 2) if vals else 0.0

    rank: dict[str, dict[str, int]] = {pos: {} for pos in z_by_pos}
    for pos in z_by_pos:
        ranked = sorted(score.items(), key=lambda kv: -kv[1].get(pos, 0.0))
        for i, (team, _) in enumerate(ranked, start=1):
            rank[pos][team] = i

    return score, rank


RED_ZONE_YARDLINE = 20


def _redzone_shares(prior_season: int) -> dict:
    """Share of each team's red-zone (inside the 20) touches -- carries plus
    targets -- that belonged to each player last season, keyed by gsis_id.
    A raw opportunity signal about the player himself, distinct from vacated
    share (which is about who left).
    """
    df = nflverse.pbp(prior_season)
    df = df[(df.season_type == "REG") & df.posteam.notna() & df.yardline_100.notna()].copy()
    df = df[df.yardline_100 <= RED_ZONE_YARDLINE]
    df["posteam"] = df.posteam.map(norm_team)

    rushes = df.loc[df.rush_attempt == 1, ["posteam", "rusher_player_id"]] \
        .rename(columns={"rusher_player_id": "player_id"})
    targets = df.loc[df.pass_attempt == 1, ["posteam", "receiver_player_id"]] \
        .rename(columns={"receiver_player_id": "player_id"})
    touches = pd.concat([rushes, targets], ignore_index=True)
    touches = touches[touches.player_id.notna()]

    out: dict[str, dict] = {}
    for team, grp in touches.groupby("posteam"):
        total = len(grp)
        if total < 5:   # too little red-zone volume that season to mean anything
            continue
        for player_id, n in grp.player_id.value_counts().items():
            out.setdefault(team, {})[player_id] = {
                "share": round(float(n) / total, 3), "touches": int(n),
            }
    return out


def _vacated_shares(prior_season: int, season: int) -> dict:
    """Of last season's carries/targets, how much belonged to players no
    longer on this team's roster this season -- retired, cut, or signed
    elsewhere. Shown as context; the algorithm redistributes a capped
    fraction of it across the remaining players at that position, weighted
    by their own already-projected share of the group (never guessing a
    specific "who inherits it" beyond that).
    """
    weekly = nflverse.weekly_stats(prior_season)
    reg = weekly[weekly.season_type == "REG"].copy()
    reg["team"] = reg.team.map(norm_team)

    ros = nflverse.rosters(season)
    ros = ros[ros.season == season].copy()
    ros["team"] = ros.team.map(norm_team)
    current_by_team = ros.groupby("team")["gsis_id"].apply(lambda s: set(s.dropna())).to_dict()

    out: dict[str, dict] = {}
    for pos, col in VACATED_VOLUME_COL.items():
        sub = reg[reg.position == pos]
        totals = sub.groupby(["team", "player_id", "player_display_name"], as_index=False)[col].sum()
        for team, grp in totals.groupby("team"):
            team_total = grp[col].sum()
            if team_total <= 0:
                continue
            current = current_by_team.get(team, set())
            grp = grp.assign(share=grp[col] / team_total)
            gone = grp[~grp.player_id.isin(current)].sort_values("share", ascending=False)
            if gone.empty:
                continue
            out.setdefault(team, {})[pos] = {
                "share": round(float(gone.share.sum()), 3),
                "departed": [
                    {"name": r.player_display_name, "share": round(float(r.share), 3)}
                    for r in gone.itertuples() if r.share >= 0.03
                ][:4],
            }
    return out


def build(cfg: LeagueConfig, season: int = 2026) -> dict:
    prior = season - 1
    oline = _oline_scores(prior)
    continuity = _oline_continuity(prior, season)
    z_by_pos = _defense_quality(cfg, prior)
    sos, sos_rank = _sos_from_schedule(z_by_pos, season)
    playoff_sos, playoff_sos_rank = _sos_from_schedule(z_by_pos, season, weeks=PLAYOFF_WEEKS)
    vacated = _vacated_shares(prior, season)
    redzone = _redzone_shares(prior)

    all_teams = set(oline) | set(continuity) | set(sos) | set(vacated) | set(redzone)
    teams = {}
    for team in all_teams:
        teams[team] = {
            "oline": oline.get(team),
            "oline_continuity": continuity.get(team),
            "sos": sos.get(team, {}),
            "sos_rank": {pos: sos_rank[pos].get(team) for pos in SOS_POSITIONS if team in sos_rank.get(pos, {})},
            "playoff_sos": playoff_sos.get(team, {}),
            "playoff_sos_rank": {pos: playoff_sos_rank[pos].get(team)
                                 for pos in SOS_POSITIONS if team in playoff_sos_rank.get(pos, {})},
            "vacated": vacated.get(team, {}),
            "redzone": redzone.get(team, {}),
        }
    return {"season": season, "prior_season": prior, "teams": teams}


def load_or_build(cfg: LeagueConfig, season: int = 2026, refresh: bool = False) -> dict:
    if not refresh and CACHE.exists():
        try:
            return json.loads(CACHE.read_text())
        except Exception:  # noqa: BLE001
            log.warning("context cache unreadable; rebuilding")
    data = build(cfg, season=season)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(json.dumps(data))
    return data
