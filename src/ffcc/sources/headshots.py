"""Local headshot cache.

The NFL CDN serves these at full size -- 4.3MB each, which for a draftable
board would be over a gigabyte. The same URL accepts a resize transform, so we
fetch a 140px face crop at roughly 7.5KB instead: about 2MB for the whole
board. Cached to disk at snapshot time so draft day needs no network.
"""
from __future__ import annotations

import hashlib
import logging
from concurrent.futures import ThreadPoolExecutor

import httpx

from ..config import DATA_DIR

log = logging.getLogger(__name__)

DIR = DATA_DIR / "headshots"
SIZE = 140
# Cloudinary transform segment. Without it each image is ~4.3MB.
TRANSFORM = f"f_auto,q_auto,w_{SIZE},h_{SIZE},c_fill,g_face"


def _filename(url: str) -> str:
    return hashlib.sha1(url.encode()).hexdigest()[:16] + ".png"


def local_name(url: str | None) -> str | None:
    """Cached filename for a headshot URL, if it has been downloaded."""
    if not url:
        return None
    name = _filename(url)
    return name if (DIR / name).exists() else None


def _thumb_url(url: str) -> str:
    return url.replace("/f_auto,q_auto/", f"/{TRANSFORM}/", 1) if "/f_auto,q_auto/" in url else url


def thumb_url(url: str | None) -> str | None:
    """The CDN URL for a face thumbnail, safe to hand the browser directly.

    nflverse rotates a player's headshot URL every time his photo is reshot
    (a trade, a new uniform), so the disk cache goes stale between snapshots.
    The board still renders the local file when it has one; this is what the
    frontend falls back to when it doesn't and the machine is online.
    """
    return _thumb_url(url) if url else None


def cache_all(urls, workers: int = 8) -> dict[str, str]:
    """Download any missing headshots. Returns url -> local filename."""
    DIR.mkdir(parents=True, exist_ok=True)
    wanted = [u for u in dict.fromkeys(u for u in urls if u)]
    out: dict[str, str] = {}
    todo: list[str] = []

    for u in wanted:
        name = _filename(u)
        if (DIR / name).exists():
            out[u] = name
        else:
            todo.append(u)

    if not todo:
        return out

    def grab(u: str):
        try:
            with httpx.Client(timeout=20, follow_redirects=True) as c:
                r = c.get(_thumb_url(u))
                r.raise_for_status()
                # Guard against an error page being written as a .png.
                if not r.content[:8].hex().startswith(("89504e47", "ffd8")):
                    return None
                name = _filename(u)
                (DIR / name).write_bytes(r.content)
                return u, name
        except Exception:  # noqa: BLE001 - a missing face must never break a draft
            return None

    with ThreadPoolExecutor(max_workers=workers) as pool:
        for res in pool.map(grab, todo):
            if res:
                out[res[0]] = res[1]

    log.info("headshots: %d cached, %d unavailable", len(out), len(wanted) - len(out))
    return out
