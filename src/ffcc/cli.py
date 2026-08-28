"""Command line entry points."""
from __future__ import annotations

import argparse
import logging
import sys


def cmd_serve(args):
    import uvicorn
    from .engine import build_board
    from .web import app as webapp

    print("Building board (first run pulls and caches ~25MB)...")
    webapp.BOARD = build_board()
    print(webapp.BOARD.report.summary())
    print(f"\n  →  http://127.0.0.1:{args.port}\n")
    uvicorn.run(webapp.app, host=args.host, port=args.port, log_level="warning")


def cmd_snapshot(args):
    """Pull and cache everything, so draft day never touches the network."""
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

    s = sub.add_parser("board", help="print the draft board")
    s.add_argument("--pos", default="ALL")
    s.add_argument("--limit", type=int, default=40)
    s.set_defaults(fn=cmd_board)

    args = ap.parse_args(argv)
    return args.fn(args) or 0


if __name__ == "__main__":
    sys.exit(main())
