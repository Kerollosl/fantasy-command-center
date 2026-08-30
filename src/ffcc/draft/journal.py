"""Crash recovery for a live draft.

`DraftState` itself stays a pure in-memory dataclass -- easy to construct and
test with no side effects. This module is the disk-facing wrapper the web
layer calls at each mutation, so a crash or restart of `ffcc serve` mid-draft
doesn't lose picks that were already recorded. One draft is at most a few
hundred lines, so a plain JSON-lines file is enough; no database needed.
"""
from __future__ import annotations

import json

from ..config import DATA_DIR
from .state import Pick

JOURNAL = DATA_DIR / "draft_journal.jsonl"


def append(pick: Pick) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with JOURNAL.open("a") as f:
        f.write(json.dumps(pick.__dict__) + "\n")


def rewrite(picks: list[Pick]) -> None:
    """Used after undo, which removes exactly one pick. A full rewrite of a
    single draft's worth of lines is cheap and sidesteps the edge cases of
    truncating a text file to "all but the last line".
    """
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with JOURNAL.open("w") as f:
        for p in picks:
            f.write(json.dumps(p.__dict__) + "\n")


def load() -> list[Pick]:
    if not JOURNAL.exists():
        return []
    picks = []
    for line in JOURNAL.read_text().splitlines():
        line = line.strip()
        if line:
            picks.append(Pick(**json.loads(line)))
    return picks


def clear() -> None:
    if JOURNAL.exists():
        JOURNAL.unlink()
