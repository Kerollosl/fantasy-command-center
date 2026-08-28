"""Disk cache with TTL.

A live draft must never block on a network call. Every source reads through
this cache; if the network is down or slow, we serve the last good copy and
say so rather than hanging or crashing mid-draft.
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path

import httpx

from ..config import CACHE_DIR

log = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 30.0
USER_AGENT = "fantasy-command-center/0.1 (personal single-league use)"


def _slot(key: str) -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in key)
    return CACHE_DIR / safe


def age_seconds(key: str) -> float | None:
    p = _slot(key)
    return None if not p.exists() else time.time() - p.stat().st_mtime


def read_cached(key: str) -> bytes | None:
    p = _slot(key)
    return p.read_bytes() if p.exists() else None


def fetch(
    url: str,
    key: str,
    ttl: float = 6 * 3600,
    headers: dict[str, str] | None = None,
    timeout: float = DEFAULT_TIMEOUT,
) -> bytes:
    """Return URL bytes, using cache when fresh.

    On network failure a stale cache entry is returned rather than raising —
    stale data mid-draft beats no data mid-draft. Raises only when there is
    nothing cached at all.
    """
    p = _slot(key)
    a = age_seconds(key)
    if a is not None and a < ttl:
        return p.read_bytes()

    hdrs = {"User-Agent": USER_AGENT, **(headers or {})}
    try:
        with httpx.Client(follow_redirects=True, timeout=timeout) as c:
            r = c.get(url, headers=hdrs)
            r.raise_for_status()
            p.write_bytes(r.content)
            return r.content
    except Exception as exc:  # noqa: BLE001 - degrade, never crash a draft
        if p.exists():
            log.warning("fetch failed for %s (%s); serving cache aged %.0fs", key, exc, a or 0)
            return p.read_bytes()
        raise RuntimeError(f"fetch failed for {url} and no cached copy exists: {exc}") from exc


def fetch_json(url: str, key: str, ttl: float = 6 * 3600, **kw):
    return json.loads(fetch(url, key, ttl=ttl, **kw))
