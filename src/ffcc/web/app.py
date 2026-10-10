"""FastAPI app driving the live draft board."""
from __future__ import annotations

import json
import copy,os
from threading import RLock
from functools import wraps
from contextlib import asynccontextmanager
from filelock import FileLock
from starlette.concurrency import run_in_threadpool
import zlib
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from ..draft.grade import grade_all, pick_values
from ..draft.lineup import optimal_lineup
from ..draft.needs import starter_gaps
from ..draft.recommend import _decision_horizon, recommend
from ..draft.survival import positional_hazards, survival_prob
from ..config import DATA_DIR
from ..draft import journal
from ..draft.montecarlo import simulate, value_share
from ..engine import build_board, set_draft_slot
from ..history.rounds import insight as round_insight

HERE = Path(__file__).parent
@asynccontextmanager
async def lifespan(app):
    # An in-memory draft cannot safely be served by independent worker processes.
    process_lock=FileLock(str(DATA_DIR / "draft-server.lock"))
    DATA_DIR.mkdir(parents=True,exist_ok=True)
    process_lock.acquire(timeout=0)
    try:yield
    finally:process_lock.release()

app = FastAPI(title="Fantasy Command Center",lifespan=lifespan)
STATE_LOCK=RLock()
def synchronized(fn):
    @wraps(fn)
    def wrapped(*args,**kwargs):
        with STATE_LOCK:return fn(*args,**kwargs)
    return wrapped
_recovered=False
app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
_shots = DATA_DIR / "headshots"
_shots.mkdir(parents=True, exist_ok=True)
app.mount("/headshots", StaticFiles(directory=_shots), name="headshots")
_logos = DATA_DIR / "logos"
_logos.mkdir(parents=True, exist_ok=True)
app.mount("/logos", StaticFiles(directory=_logos), name="logos")

BOARD = None


def _sim_seed(state, cfg) -> int:
    """A stable seed for the pick simulation, keyed to the board state.

    Same picks entered, same slot, same pick number -> same seed -> identical
    simulated probabilities on every refresh. The numbers only move when the
    draft actually moves, so the headline recommendation stops flickering
    between two close candidates while you are deciding.
    """
    picks = "|".join(p.player_key for p in state.picks)
    return zlib.crc32(f"{cfg.my_draft_slot}:{state.current_pick}:{picks}".encode())


@synchronized
def board():
    global BOARD, _recovered
    if BOARD is None:
        BOARD = build_board()
    if not _recovered:
        journal.configure(BOARD.cfg,os.environ.get("FFCC_SESSION","default"))
        recovered = journal.load()
        if recovered:
            BOARD.state.picks = recovered
            print(f"Recovered {len(recovered)} pick(s) from a prior session's journal.")
        if any(p.team_slot > BOARD.cfg.teams for p in BOARD.state.picks):
            raise ValueError("Recovered picks do not match league team count")
        _recovered=True
    return BOARD


def _player_json(p, b, surv=None):
    return {
        "key": p.key, "name": p.name, "pos": p.position, "team": p.team,
        "adp": p.adp, "bye": p.bye, "proj": p.proj_points, "vor": p.vor,
        "tier": p.tier, "injury": p.injury_status,
        "depth": p.depth_chart_order, "survival": surv,
        "age": p.age, "headshot": p.headshot, "team_logo": p.team_logo,
        "predicted_rank": p.predicted_rank, "last_year_rank": p.last_year_rank,
        "predicted_rank_overall": p.predicted_rank_overall,
        "last_year_rank_overall": p.last_year_rank_overall,
    }


def _scarcity(state, players, cfg, hazards, my_next):
    """Remaining players grouped by tier, per position.

    This is what the tier ladder draws. The number that actually drives a draft
    decision is not a player's rank but how many are left before the next cliff
    -- "two RBs left in this tier" is the whole argument for taking one now.
    """
    avail = state.available(players)
    out: dict[str, dict] = {}
    for pos in ("RB", "WR", "TE", "QB", "DEF", "K"):
        pool = sorted([p for p in avail if p.position == pos], key=lambda p: -p.vor)
        if not pool:
            out[pos] = {"tiers": [], "left_in_top_tier": 0, "top_vor": 0.0, "next_cliff": 0.0}
            continue
        tiers: list[dict] = []
        for p in pool[:60]:
            if tiers and tiers[-1]["tier"] == p.tier:
                tiers[-1]["count"] += 1
                tiers[-1]["min_vor"] = round(p.vor, 1)
            else:
                tiers.append({"tier": p.tier, "count": 1,
                              "max_vor": round(p.vor, 1), "min_vor": round(p.vor, 1),
                              "names": []})
            # 12 matches the number of blocks the ladder actually draws per tier
            # (the rest fold into a "+N" count) -- keep this in sync with the
            # frontend's block-rendering cap so every visible square resolves to
            # an actual player. `key` lets a click open that player's profile
            # without a fragile name-only lookup on the client.
            if len(tiers[-1]["names"]) < 12:
                tiers[-1]["names"].append({"name": p.name, "key": p.key})
        top = tiers[0]
        # How far value falls once this tier is exhausted.
        cliff = (top["min_vor"] - tiers[1]["max_vor"]) if len(tiers) > 1 else 0.0
        out[pos] = {
            "tiers": tiers[:6],
            "left_in_top_tier": top["count"],
            "top_vor": top["max_vor"],
            "next_cliff": round(cliff, 1),
            "hazard": round(hazards.get(pos, 1.0), 2),
        }
    return out


def _composition(picks) -> list[dict]:
    """Positional make-up of a roster, ordered so the donut is stable.

    Part-to-whole with at most six segments -- the one place on this board where
    a donut beats a number, because the question is "what shape is this roster"
    rather than "how many of each".
    """
    order = ("QB", "RB", "WR", "TE", "DEF", "K")
    counts: dict[str, int] = {}
    for p in picks:
        counts[p.position] = counts.get(p.position, 0) + 1
    return [{"pos": p, "n": counts[p]} for p in order if counts.get(p)]


def _grid(state, cfg):
    """Picks arranged as rounds x teams, the way a draft board actually reads.

    Each cell must sit in its OWNING team's column. Laying them out by position
    within the round looks right in round 1 and is wrong in every even round,
    because a snake reverses -- the last pick of round 2 belongs to team 1, not
    team 12, and putting it under the wrong header misreads the whole board.
    """
    by_overall = {p.overall: p for p in state.picks}
    rows = []
    for rnd in range(cfg.rounds):
        row = [None] * cfg.teams
        for i in range(cfg.teams):
            overall = rnd * cfg.teams + i + 1
            slot = state._order[overall - 1]
            pick = by_overall.get(overall)
            row[slot - 1] = {
                "overall": overall, "slot": slot,
                "name": pick.player_name if pick else None,
                "pos": pick.position if pick else None,
                "mine": slot == cfg.my_draft_slot,
            }
        rows.append(row)
    return rows


@synchronized
def snapshot():
    b = board()
    st, cfg = b.state, b.cfg
    keys = b.by_key()
    my_next = st.next_pick_for(cfg.my_draft_slot, after=st.current_pick)
    # Survival everywhere is measured against the same horizon the recommender
    # uses. At the turn your next pick is the very next one, so "will he last?"
    # must look past it or every number on screen reads 100%.
    horizon = _decision_horizon(st, cfg, st.current_pick)
    hazards = positional_hazards(st, b.players)

    avail = sorted(st.available(b.players), key=lambda p: -p.vor)[:180]
    players = [
        _player_json(p, b, survival_prob(p, horizon, st.current_pick, hazards) if horizon else None)
        for p in avail
    ]

    rec_objs = recommend(st, b.players, cfg, limit=8)
    shares = value_share(rec_objs)
    try:
        odds = {o.key: o for o in
                simulate(st, b.players, cfg, [r.player for r in rec_objs],
                         hazards=hazards, seed=_sim_seed(st, cfg))}
    except Exception:  # noqa: BLE001 - the analytic score always stands on its own
        odds = {}

    # Order by the number actually shown. The analytic score and the simulated
    # probability do not always agree, and when they disagree the simulation is
    # the better answer -- it accounts for what comes back to you. Ranking by one
    # while displaying the other put a 46% candidate below a 26% one.
    if odds:
        rec_objs.sort(key=lambda r: -(odds[r.player.key].probability
                                      if r.player.key in odds else 0.0))

    # When the simulation and the value model disagree, say why. The reason is
    # already on screen -- a tier cliff, a run, a player about to disappear --
    # but leaving the reader to connect it is exactly the ambiguity that makes a
    # recommendation feel arbitrary.
    def _disagreement(top_rec) -> str | None:
        if not odds or len(rec_objs) < 2:
            return None
        value_leader = max(rec_objs, key=lambda r: shares.get(r.player.key, 0.0))
        if value_leader.player.key == top_rec.player.key:
            return None
        sc = scarcity.get(top_rec.player.position) or {}
        left, cliff = sc.get("left_in_top_tier"), sc.get("next_cliff") or 0
        vl_sc = scarcity.get(value_leader.player.position) or {}
        vl_left = vl_sc.get("left_in_top_tier")
        bits = []
        if left is not None and cliff >= 8:
            bits.append(
                f"only {left} {top_rec.player.position}"
                f"{'' if left == 1 else 's'} left at this value, then a {cliff:.0f}-point drop"
            )
        if vl_left is not None and vl_left >= 5:
            bits.append(
                f"{value_leader.player.position} is {vl_left} deep, so waiting there costs less"
            )
        if not bits:
            return None
        return (f"Value alone prefers {value_leader.player.name}, but the simulation "
                f"favours {top_rec.player.name}: " + "; ".join(bits) + ".")

    recs = []
    for r in rec_objs:
        o = odds.get(r.player.key)
        recs.append({
            "name": r.player.name, "pos": r.player.position, "team": r.player.team,
            "key": r.player.key, "score": r.score, "vona": r.vona,
            "survival": r.survival_next, "adp": r.player.adp, "tier": r.player.tier,
            "reasons": r.reasons, "warnings": r.warnings,
            "headshot": r.player.headshot, "age": r.player.age,
            "team_logo": r.player.team_logo,
            "value_share": shares.get(r.player.key),
            "pick_prob": round(o.probability, 4) if o else None,
            "prob_low": round(o.low, 4) if o else None,
            "prob_high": round(o.high, 4) if o else None,
            "sims": o.sims if o else 0,
            "tied_with": o.tied_with if o else [],
        })

    my_roster = [keys[p.player_key] for p in st.roster(cfg.my_draft_slot) if p.player_key in keys]
    counts: dict[str, int] = {}
    for p in my_roster:
        counts[p.position] = counts.get(p.position, 0) + 1

    grades = [
        {
            "slot": g.slot, "letter": g.letter, "score": round(g.score, 2),
            "slp": g.slp, "vas": g.vas, "rf": g.rf,
            "confidence": g.confidence, "notes": g.notes,
            "is_me": g.slot == cfg.my_draft_slot,
            "roster": [
                {"name": pk.player_name, "pos": pk.position, "overall": pk.overall}
                for pk in st.roster(g.slot)
            ],
            "shape": _composition(st.roster(g.slot)),
        }
        for g in grade_all(st, b.players, cfg)
    ]

    max_vor = max([p.vor for p in avail], default=1.0) or 1.0
    scarcity = _scarcity(st, b.players, cfg, hazards, horizon)

    return {
        "league": cfg.name,
        "teams": cfg.teams,
        "rounds": cfg.rounds,
        "my_slot": cfg.my_draft_slot,
        "flex_eligible": cfg.flex_eligible,
        "my_picks": cfg.my_pick_numbers(),
        "current_pick": st.current_pick,
        "total_picks": cfg.total_picks,
        "on_clock": st.slot_on_clock(),
        "is_my_turn": st.is_my_turn(),
        "my_next_pick": my_next,
        "horizon_pick": horizon,
        "picks_until_mine": st.picks_until_my_next(),
        "complete": st.is_complete,
        "hazards": {k: round(v, 2) for k, v in hazards.items()},
        "needs": starter_gaps(cfg, counts),
        "players": players,
        "recommendations": recs,
        "grades": grades,
        "recent": [
            {"overall": p.overall, "slot": p.team_slot, "name": p.player_name, "pos": p.position}
            for p in st.picks[-12:]
        ],
        "resolution": board().report.summary(),
        "scarcity": scarcity,
        "disagreement": _disagreement(rec_objs[0]) if rec_objs else None,
        "grid": _grid(st, cfg),
        "max_vor": round(max_vor, 1),
        "round": (st.current_pick - 1) // cfg.teams + 1,
        "round_insight": round_insight(b.round_value, (st.current_pick - 1) // cfg.teams + 1),
        "replacement": {k: round(v, 1) for k, v in b.replacement.items()},
    }


@app.get("/", response_class=HTMLResponse)
def index():
    return (HERE / "templates" / "index.html").read_text()


@app.get("/api/state")
def get_state():
    return snapshot()


@app.get("/api/recap")
@synchronized
def recap():
    """Draft summary: final grade, full roster, and which picks captured the
    most (and least) value against where the market had them. Meaningful at
    any point in the draft, but written for after the last pick.
    """
    b = board()
    st, cfg = b.state, b.cfg
    slot = cfg.my_draft_slot
    by_key = b.by_key()

    picks = pick_values(st, b.players, cfg, slot)
    roster = [by_key[pk.player_key] for pk in st.roster(slot) if pk.player_key in by_key]
    starter_pts, slot_map = optimal_lineup(roster, cfg)
    starter_keys = {p.key for lst in slot_map.values() for p in lst}

    grades = grade_all(st, b.players, cfg)
    mine = next((g for g in grades if g.slot == slot), None)
    league_rank = sorted(grades, key=lambda g: -g.score).index(mine) + 1 if mine else None

    ranked = sorted(picks, key=lambda pk: -pk["value"])
    return {
        "ok": True,
        "complete": st.is_complete,
        "picks_made": len(st.picks),
        "total_picks": cfg.total_picks,
        "grade": ({"letter": mine.letter, "score": round(mine.score, 2), "notes": mine.notes,
                   "league_rank": league_rank, "of": len(grades)} if mine else None),
        "starter_points": starter_pts,
        "roster": [{**pk, "starter": pk["key"] in starter_keys}
                   for pk in sorted(picks, key=lambda pk: pk["overall"])],
        "best_value": ranked[:3],
        "biggest_reaches": list(reversed(ranked[-3:])) if len(ranked) > 3 else [],
    }


@app.get("/api/player/{key:path}")
@synchronized
def player_profile(key: str):
    """Everything known about one player, for the profile panel."""
    b = board()
    p = b.by_key().get(key)
    if not p:
        return {"ok": False, "error": "unknown player"}

    st, cfg = b.state, b.cfg
    horizon = _decision_horizon(st, cfg, st.current_pick)
    hazards = positional_hazards(st, b.players)
    same_pos = [q for q in st.available(b.players)
                if q.position == p.position and q.key != p.key]
    next_up = max(same_pos, key=lambda q: q.vor) if same_pos else None

    return {
        "ok": True,
        "key": p.key, "name": p.name, "pos": p.position, "team": p.team,
        "age": p.age, "bye": p.bye, "adp": p.adp, "tier": p.tier,
        "headshot": p.headshot, "team_logo": p.team_logo, "injury": p.injury_status,
        "depth": p.depth_chart_order, "years_exp": p.years_exp,
        "proj": p.proj_points, "vor": p.vor,
        "proj_market": p.proj_market, "proj_baseline": p.proj_baseline,
        "history_weight": p.history_weight,
        "trajectory": p.trajectory, "adjustments": p.adjustments,
        "seasons": p.seasons,
        "oline_rank": p.oline_rank, "oline_score": p.oline_score,
        "oline_continuity": p.oline_continuity, "oline_departed": p.oline_departed,
        "oline_returning": p.oline_returning, "oline_total": p.oline_total,
        "sos_rank": p.sos_rank, "sos_score": p.sos_score,
        "playoff_sos_rank": p.playoff_sos_rank, "playoff_sos_score": p.playoff_sos_score,
        "vacated_share": p.vacated_share, "vacated_departed": p.vacated_departed,
        "redzone_share": p.redzone_share, "redzone_touches": p.redzone_touches,
        "durability": p.durability, "durability_seasons": p.durability_seasons,
        "handcuff_key": p.handcuff_key, "handcuff_name": p.handcuff_name,
        "drafted": p.key in st.drafted_keys(),
        "survival": (survival_prob(p, horizon, st.current_pick, hazards)
                     if horizon and p.key not in st.drafted_keys() else None),
        "horizon": horizon,
        "replacement": round(b.replacement.get(p.position, 0.0), 1),
        "next_best": ({"name": next_up.name, "vor": next_up.vor, "proj": next_up.proj_points}
                      if next_up else None),
    }


@app.get("/api/search")
@synchronized
def search(q: str, all_players: bool = False):
    b = board()
    return [
        {"key": p.key, "name": p.name, "pos": p.position, "team": p.team,
         "adp": p.adp, "vor": p.vor, "tier": p.tier}
        for p in b.find(q, limit=8, available_only=not all_players)
    ]


@app.post("/api/pick")
@synchronized
def make_pick(payload: dict):
    b = board()
    key = payload.get("key")
    p = b.by_key().get(key)
    if not p:
        return {"ok": False, "error": f"unknown player: {key}"}
    try:
        candidate = copy.deepcopy(b.state)
        pick = candidate.record(p, slot=payload.get("slot"))
    except ValueError as e:
        return {"ok": False, "error": str(e)}
    journal.rewrite(candidate.picks)
    b.state.picks = candidate.picks
    return {"ok": True, "pick": {"overall": pick.overall, "slot": pick.team_slot,
                                 "name": pick.player_name}}


@app.post("/api/slot")
@synchronized
def choose_slot(payload: dict):
    b = board()
    try:
        slot = int(payload.get("slot"))
    except (TypeError, ValueError):
        return {"ok": False, "error": "slot must be a number"}
    if not 1 <= slot <= b.cfg.teams:
        return {"ok": False, "error": f"slot must be between 1 and {b.cfg.teams}"}
    set_draft_slot(b, slot)
    return {"ok": True, "slot": slot, "my_picks": b.cfg.my_pick_numbers()}


@app.post("/api/undo")
@synchronized
def undo():
    st = board().state
    p = st.picks[-1] if st.picks else None
    if p:
        journal.rewrite(st.picks[:-1])
        st.undo()
    return {"ok": p is not None, "undone": p.player_name if p else None}


@app.post("/api/reset")
@synchronized
def reset():
    b = board()
    journal.clear()
    b.state.picks.clear()
    return {"ok": True}


@app.websocket("/ws")
async def ws(sock: WebSocket):
    await sock.accept()
    try:
        await sock.send_text(json.dumps(await run_in_threadpool(snapshot)))
        while True:
            await sock.receive_text()
            await sock.send_text(json.dumps(await run_in_threadpool(snapshot)))
    except WebSocketDisconnect:
        return

