"""Local team-logo cache.

Team logos are trademarked league imagery, same category as the player
headshots -- fetched and cached locally for personal use rather than shipped
in the repo. ESPN's CDN serves them at 500px; we downsize to a small icon
ourselves (no Cloudinary-style URL transform available here, unlike the NFL
headshot CDN), so a 32-team fetch stays a few hundred KB rather than ~1.8MB.
"""
from __future__ import annotations

import csv
import io
import logging
from concurrent.futures import ThreadPoolExecutor

import httpx
from PIL import Image

from ..config import DATA_DIR

log = logging.getLogger(__name__)

DIR = DATA_DIR / "logos"
SIZE = 44          # 2x a ~22px display size, for retina
TEAMS_CSV = (
    "https://github.com/nflverse/nflverse-data/releases/download/teams/teams_colors_logos.csv"
)
# Some current abbreviations aren't the CSV's own key for that franchise
# (its Rams row is "LA", not our canonical "LAR"); fall back through the
# franchise's prior names rather than fail silently.
ABBR_FALLBACK = {"LAR": ["LAR", "LA", "STL"], "LV": ["LV", "OAK"], "LAC": ["LAC", "SD"]}


def local_name(abbr: str | None) -> str | None:
    if not abbr:
        return None
    name = f"{abbr}.png"
    return name if (DIR / name).exists() else None


def _logo_urls() -> dict[str, str]:
    with httpx.Client(timeout=20, follow_redirects=True) as c:
        r = c.get(TEAMS_CSV)
        r.raise_for_status()
    rows = list(csv.DictReader(io.StringIO(r.text)))
    return {row["team_abbr"]: row["team_logo_espn"] for row in rows if row.get("team_logo_espn")}


def cache_all(abbrs, workers: int = 8) -> dict[str, str]:
    """Download and downsize any missing team logos. Returns abbr -> filename."""
    DIR.mkdir(parents=True, exist_ok=True)
    wanted = sorted(set(a for a in abbrs if a))
    out: dict[str, str] = {}
    todo: list[str] = []
    for a in wanted:
        if (DIR / f"{a}.png").exists():
            out[a] = f"{a}.png"
        else:
            todo.append(a)
    if not todo:
        return out

    try:
        urls = _logo_urls()
    except Exception as exc:  # noqa: BLE001 - never break a draft over logos
        log.warning("team logo index unavailable: %s", exc)
        return out

    def grab(abbr: str):
        candidates = ABBR_FALLBACK.get(abbr, [abbr])
        url = next((urls[c] for c in candidates if c in urls), None)
        if not url:
            return None
        try:
            with httpx.Client(timeout=20, follow_redirects=True) as c:
                resp = c.get(url)
                resp.raise_for_status()
            img = Image.open(io.BytesIO(resp.content)).convert("RGBA")
            img.thumbnail((SIZE, SIZE), Image.LANCZOS)
            buf = io.BytesIO()
            img.save(buf, format="PNG", optimize=True)
            (DIR / f"{abbr}.png").write_bytes(buf.getvalue())
            return abbr, f"{abbr}.png"
        except Exception:  # noqa: BLE001 - one bad logo must never break a draft
            return None

    with ThreadPoolExecutor(max_workers=workers) as pool:
        for res in pool.map(grab, todo):
            if res:
                out[res[0]] = res[1]

    log.info("team logos: %d cached, %d unavailable", len(out), len(wanted) - len(out))
    return out
