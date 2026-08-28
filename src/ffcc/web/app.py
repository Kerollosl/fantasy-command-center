"""FastAPI app driving the live draft board."""
from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from ..draft.grade import grade_all
from ..draft.needs import starter_gaps
from ..draft.recommend import _decision_horizon, recommend
from ..draft.survival import positional_hazards, survival_prob
from ..engine import build_board, set_draft_slot

HERE = Path(__file__).parent
app = FastAPI(title="Fantasy Command Center")
app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")

BOARD = None


def board():
    global BOARD
    if BOARD is None:
        BOARD = build_board()
    return BOARD


def _player_json(p, b, surv=None):
    return {
        "key": p.key, "name": p.name, "pos": p.position, "team": p.team,
        "adp": p.adp, "bye": p.bye, "proj": p.proj_points, "vor": p.vor,
        "tier": p.tier, "injury": p.injury_status,
        "depth": p.depth_chart_order, "survival": surv,
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
            if len(tiers[-1]["names"]) < 3:
                tiers[-1]["names"].append(p.name)
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

    recs = [
        {
            "name": r.player.name, "pos": r.player.position, "team": r.player.team,
            "key": r.player.key, "score": r.score, "vona": r.vona,
            "survival": r.survival_next, "adp": r.player.adp, "tier": r.player.tier,
            "reasons": r.reasons, "warnings": r.warnings,
        }
        for r in recommend(st, b.players, cfg, limit=8)
    ]

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

    return {
        "league": cfg.name,
        "teams": cfg.teams,
        "rounds": cfg.rounds,
        "my_slot": cfg.my_draft_slot,
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
        "scarcity": _scarcity(st, b.players, cfg, hazards, horizon),
        "grid": _grid(st, cfg),
        "max_vor": round(max_vor, 1),
        "round": (st.current_pick - 1) // cfg.teams + 1,
    }


@app.get("/", response_class=HTMLResponse)
def index():
    return (HERE / "templates" / "index.html").read_text()


@app.get("/api/state")
def get_state():
    return snapshot()


@app.get("/api/search")
def search(q: str, all_players: bool = False):
    b = board()
    return [
        {"key": p.key, "name": p.name, "pos": p.position, "team": p.team,
         "adp": p.adp, "vor": p.vor, "tier": p.tier}
        for p in b.find(q, limit=8, available_only=not all_players)
    ]


@app.post("/api/pick")
def make_pick(payload: dict):
    b = board()
    key = payload.get("key")
    p = b.by_key().get(key)
    if not p:
        return {"ok": False, "error": f"unknown player: {key}"}
    try:
        pick = b.state.record(p, slot=payload.get("slot"))
    except ValueError as e:
        return {"ok": False, "error": str(e)}
    return {"ok": True, "pick": {"overall": pick.overall, "slot": pick.team_slot,
                                 "name": pick.player_name}}


@app.post("/api/slot")
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
def undo():
    p = board().state.undo()
    return {"ok": p is not None, "undone": p.player_name if p else None}


@app.post("/api/reset")
def reset():
    b = board()
    b.state.picks.clear()
    return {"ok": True}


@app.websocket("/ws")
async def ws(sock: WebSocket):
    await sock.accept()
    try:
        await sock.send_text(json.dumps(snapshot()))
        while True:
            await sock.receive_text()
            await sock.send_text(json.dumps(snapshot()))
    except WebSocketDisconnect:
        return
