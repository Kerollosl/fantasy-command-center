"""FastAPI app driving the live draft board."""
from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from ..draft.grade import grade_all
from ..draft.needs import starter_gaps
from ..draft.recommend import recommend
from ..draft.survival import positional_hazards, survival_prob
from ..engine import build_board

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


def snapshot():
    b = board()
    st, cfg = b.state, b.cfg
    keys = b.by_key()
    my_next = st.next_pick_for(cfg.my_draft_slot, after=st.current_pick)
    hazards = positional_hazards(st, b.players)

    avail = sorted(st.available(b.players), key=lambda p: -p.vor)[:180]
    players = [
        _player_json(p, b, survival_prob(p, my_next, st.current_pick, hazards) if my_next else None)
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
        }
        for g in grade_all(st, b.players, cfg)
    ]

    return {
        "league": cfg.name,
        "teams": cfg.teams,
        "rounds": cfg.rounds,
        "my_slot": cfg.my_draft_slot,
        "current_pick": st.current_pick,
        "total_picks": cfg.total_picks,
        "on_clock": st.slot_on_clock(),
        "is_my_turn": st.is_my_turn(),
        "my_next_pick": my_next,
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
