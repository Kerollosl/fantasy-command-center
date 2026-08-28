"""FantasyPros expert consensus rankings, via DynastyProcess's free mirror.

A second, independent market signal with its own dispersion (sd/best/worst),
and it reaches ~518 players where FFC ADP stops at 267 — which is what keeps
the deep board from going blank in the late rounds.

It is a weekly snapshot, so it can lag ADP by a few days. ADP stays the
fresher signal; ECR contributes depth and a disagreement check.
"""
from __future__ import annotations

import csv
import io
from dataclasses import dataclass

from .cache import fetch

URL = "https://github.com/dynastyprocess/data/raw/master/files/db_fpecr_latest.csv"

# redraft-overall for 1QB leagues; redraft-op is the superflex/2QB board.
PAGE_REDRAFT = "redraft-overall"
PAGE_SUPERFLEX = "redraft-op"


@dataclass(frozen=True)
class EcrEntry:
    name: str
    position: str
    team: str
    ecr: float
    sd: float
    best: int
    worst: int


def fetch_ecr(page_type: str = PAGE_REDRAFT, ttl: float = 12 * 3600) -> list[EcrEntry]:
    raw = fetch(URL, key="dp_fpecr_latest.csv", ttl=ttl)
    rows = csv.DictReader(io.StringIO(raw.decode("utf-8", errors="replace")))

    out: list[EcrEntry] = []
    for r in rows:
        if r.get("page_type") != page_type or not r.get("ecr"):
            continue
        try:
            out.append(
                EcrEntry(
                    name=r.get("player") or "",
                    position=(r.get("pos") or "").upper(),
                    team=(r.get("team") or "").upper(),
                    ecr=float(r["ecr"]),
                    sd=float(r["sd"]) if r.get("sd") else 0.0,
                    best=int(float(r["best"])) if r.get("best") else 1,
                    worst=int(float(r["worst"])) if r.get("worst") else 400,
                )
            )
        except (ValueError, TypeError):
            continue
    return sorted(out, key=lambda e: e.ecr)
