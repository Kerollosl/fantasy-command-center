"""Command line entry points."""
from __future__ import annotations

import argparse
import logging
import sys


def cmd_serve(args):
    import uvicorn
    from .web import app as webapp

    print("Building board (first run pulls and caches ~25MB)...")
    # Go through board(), not build_board(): assigning BOARD directly skips the
    # journal replay, so a restart mid-draft came up with an empty board and
    # every pick already entered was lost from the UI.
    print(webapp.board().report.summary())
    print(f"\n  →  http://127.0.0.1:{args.port}\n")
    uvicorn.run(webapp.app, host=args.host, port=args.port, log_level="warning")


def cmd_snapshot(args):
    """Pull and cache everything, so draft day never touches the network."""
    from .context.signals import load_or_build as load_context
    from .engine import build_board, cache_media
    from .history.production import load_or_build as load_production
    from .projections.aging import load_or_fit as load_aging

    b = build_board()
    print(b.report.summary())

    print("Fitting aging curves...")
    curves = load_aging(b.cfg, refresh=args.refresh)
    print(f"  {sum(len(v) for v in curves.values())} fitted age steps")

    print("Building production history...")
    prod = load_production(b.cfg, refresh=args.refresh)
    print(f"  {len(prod)} player histories")

    print("Building team context (O-line, schedule, vacated opportunity)...")
    try:
        ctx = load_context(b.cfg, refresh=args.refresh)
        print(f"  {len(ctx.get('teams', {}))} teams covered")
    except Exception as exc:  # noqa: BLE001
        print(f"  skipped ({exc})")

    print("Caching headshots and team logos...")
    n_faces, n_logos = cache_media(b)
    print(f"  {n_faces} headshots, {n_logos} team logos cached locally")

    if b.round_value:
        print(f"  round-value table over {len(b.round_value.get('seasons', []))} seasons")
    if b.report.unmatched_gsis:
        print(f"\nUNRESOLVED ({len(b.report.unmatched_gsis)}):")
        for n in b.report.unmatched_gsis:
            print("  -", n)
        print("\nAdd these to config/overrides.yaml.")
        return 1
    print("All draftable players resolved. Snapshot cached — safe to draft offline.")
    return 0


def cmd_rehearse(args):
    """Run one full mock draft end-to-end against a fresh, isolated board --
    a pre-draft-day dry run to catch edge cases (K/DEF exhaustion, the last
    overall pick, a thinned-out board late) before they matter for real.
    Never touches the live journal, `data/context.json`, or league.yaml --
    this builds its own board and DraftState in-process.
    """
    import time

    from .config import load_league
    from .draft.grade import grade_all, pick_values
    from .draft.montecarlo import simulate
    from .draft.recommend import _decision_horizon, recommend
    from .draft.survival import positional_hazards
    from .engine import build_board

    cfg = load_league()
    b = build_board(cfg)
    st, players = b.state, b.players
    print(f"Rehearsing a {cfg.teams}-team, {cfg.rounds}-round draft ({cfg.total_picks} picks)...")

    errors: list[str] = []
    checkpoints = {1, cfg.teams, cfg.total_picks // 2,
                   max(cfg.total_picks - cfg.teams, 1), cfg.total_picks}
    t0 = time.perf_counter()

    while not st.is_complete:
        overall = st.current_pick
        slot = st.slot_on_clock()
        avail = st.available(players)
        if not avail:
            errors.append(f"pick {overall}: no players left on the board")
            break

        # Naive bot: best VOR available, skipping a position this team has
        # already stocked past a reasonable bench allowance -- realistic
        # enough to exercise every code path a real draft would hit,
        # including K/DEF eventually coming off the board late.
        counts = st.position_counts(slot)
        pool = sorted(avail, key=lambda p: -p.vor)
        choice = next(
            (p for p in pool if counts.get(p.position, 0) < cfg.roster.get(p.position, 1) + 3),
            pool[0],
        )
        try:
            st.record(choice, slot=slot)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"pick {overall}: record() raised {exc!r}")
            break

        if overall in checkpoints:
            try:
                positional_hazards(st, players)
                horizon = _decision_horizon(st, cfg, st.current_pick)
                recs = recommend(st, players, cfg, limit=6)
                if recs and horizon:
                    simulate(st, players, cfg, [r.player for r in recs[:4]], sims=80)
                grade_all(st, players, cfg)
            except Exception as exc:  # noqa: BLE001
                errors.append(f"pick {overall}: live-pipeline check raised {exc!r}")

    dt = time.perf_counter() - t0
    print(f"Completed {len(st.picks)}/{cfg.total_picks} picks in {dt:.1f}s.")

    if not errors:
        try:
            pick_values(st, players, cfg, cfg.my_draft_slot)
            grade_all(st, players, cfg)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"end-of-draft recap: raised {exc!r}")

    if errors:
        print(f"\n{len(errors)} issue(s) found:")
        for e in errors:
            print("  -", e)
        return 1
    print("No issues found. Safe to draft.")
    return 0


def cmd_board(args):
    from .config import load_league
    from .engine import build_board

    cfg = load_league()
    b = build_board(cfg)
    players = [p for p in b.players if args.pos in ("ALL", p.position)]
    players.sort(key=lambda p: -p.vor)
    print(f"{'#':>3} {'player':24s} {'pos':4s} {'tier':>4s} {'VOR':>7s} {'proj':>7s} {'ADP':>6s}")
    for i, p in enumerate(players[: args.limit], 1):
        print(f"{i:3d} {p.name[:24]:24s} {p.position:4s} {p.tier:4d} "
              f"{p.vor:7.1f} {p.proj_points:7.1f} {p.adp if p.adp else 0:6.1f}")
    return 0


def main(argv=None):
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")
    ap = argparse.ArgumentParser(prog="ffcc", description="Fantasy Command Center")
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("serve", help="run the live draft board")
    s.add_argument("--port", type=int, default=8000)
    s.add_argument("--host", default="127.0.0.1")
    s.set_defaults(fn=cmd_serve)

    s = sub.add_parser("snapshot", help="cache all data and verify resolution")
    s.add_argument("--refresh", action="store_true",
                   help="refit aging curves and rebuild history from source")
    s.set_defaults(fn=cmd_snapshot)

    s = sub.add_parser("rehearse", help="run a full mock draft end-to-end to catch edge cases before draft day")
    s.set_defaults(fn=cmd_rehearse)

    s = sub.add_parser("board", help="print the draft board")
    s.add_argument("--pos", default="ALL")
    s.add_argument("--limit", type=int, default=40)
    s.set_defaults(fn=cmd_board)

    args = ap.parse_args(argv)
    return args.fn(args) or 0


if __name__ == "__main__":
    sys.exit(main())
