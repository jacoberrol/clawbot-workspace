#!/usr/bin/env python3
"""
Genre Enricher — looks up genres for artists in events-enriched.json
via MusicBrainz API, caches results in events/genre-cache.json.

Cache design:
- Each entry: {"genres": [...], "cached_at": <unix_ts>, "expires_at": <unix_ts>}
- Base TTL: 90 days
- Jitter: 0–29 days derived from hash(artist_name) — so different artists
  expire on different days, preventing thundering-herd cache eviction.
- Expired entries are dropped and re-queued for lookup on the next run.
- Migration: old flat-list entries (["genre"]) are upgraded on first read.

Cron: 0 10 * * * (after crawler at 7am, html-gen at 9am)
"""

import hashlib
import json
import time
import urllib.request
import urllib.parse
import subprocess
from pathlib import Path
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

WORKSPACE     = Path(__file__).parent.parent
ENRICHED_FILE = WORKSPACE / "events/events-enriched.json"
GENRE_CACHE   = WORKSPACE / "events/genre-cache.json"
ET            = ZoneInfo("America/New_York")

MAX_LOOKUPS_PER_RUN = 60
MB_DELAY   = 1.1   # seconds between MusicBrainz requests
TTL_BASE   = 90    # days before a cached entry expires
TTL_JITTER = 29    # max extra days added per-artist to spread evictions

MB_HEADERS = {
    "User-Agent": "clawbot-events/1.0 (personal event aggregator)",
    "Accept": "application/json",
}

SKIP_TAGS = {
    "seen live", "male vocalists", "female vocalists", "american", "british",
    "canadian", "australian", "swedish", "norwegian", "german", "dutch",
    "under 2000 listeners", "all",
}
MAX_GENRES = 3


# ─── Cache helpers ───────────────────────────────────────────────────────────

def _jitter_days(artist_key: str) -> int:
    """Deterministic 0–TTL_JITTER day jitter based on artist name hash."""
    digest = int(hashlib.sha256(artist_key.encode()).hexdigest(), 16)
    return digest % (TTL_JITTER + 1)


def _expires_at(artist_key: str) -> float:
    """Compute expiry unix timestamp for a given artist key."""
    days = TTL_BASE + _jitter_days(artist_key)
    return time.time() + days * 86400


def load_genre_cache() -> dict:
    """
    Load cache from disk. Migrates old flat-list format to new dict format.
    Drops expired entries so they get re-queued.
    """
    try:
        raw = json.loads(GENRE_CACHE.read_text())
    except Exception:
        return {}

    now = time.time()
    migrated = {}
    expired_count = 0

    for key, val in raw.items():
        # Migrate old format: {"artist": ["genre1", "genre2"]}
        if isinstance(val, list):
            migrated[key] = {
                "genres": val,
                "cached_at": now,
                "expires_at": _expires_at(key),
            }
            continue

        # New format: check expiry
        if isinstance(val, dict):
            if now > val.get("expires_at", float("inf")):
                expired_count += 1
                continue  # drop expired entry
            migrated[key] = val

    if expired_count:
        print(f"  ♻️  Dropped {expired_count} expired cache entries")

    return migrated


def save_genre_cache(cache: dict):
    GENRE_CACHE.write_text(json.dumps(cache, indent=2, sort_keys=True))


def cache_get_genres(cache: dict, artist_key: str):
    """Return genres list if cached and fresh, else None."""
    entry = cache.get(artist_key)
    if entry is None:
        return None
    return entry.get("genres", [])


def cache_set(cache: dict, artist_key: str, genres: list):
    """Store a lookup result with expiry timestamp."""
    cache[artist_key] = {
        "genres": genres,
        "cached_at": time.time(),
        "expires_at": _expires_at(artist_key),
    }


# ─── MusicBrainz lookup ──────────────────────────────────────────────────────

def lookup_genres(artist_name: str):
    """
    Query MusicBrainz for artist genre tags.
    Returns list of genre strings, or None on network error (don't cache).
    """
    try:
        q = urllib.parse.urlencode({
            "query": f'artist:"{artist_name}"',
            "fmt": "json",
            "limit": "3",
        })
        url = f"https://musicbrainz.org/ws/2/artist/?{q}"
        req = urllib.request.Request(url, headers=MB_HEADERS)
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read())

        artists = data.get("artists", [])
        if not artists:
            return []

        tags = sorted(
            artists[0].get("tags", []),
            key=lambda t: t.get("count", 0),
            reverse=True,
        )
        genres = []
        for t in tags:
            name = t.get("name", "").lower().strip()
            if name and name not in SKIP_TAGS and len(name) > 1:
                genres.append(name)
            if len(genres) >= MAX_GENRES:
                break
        return genres

    except Exception as e:
        print(f"  ⚠️  MusicBrainz error for '{artist_name}': {e}")
        return None  # None = transient error, don't cache


# ─── Main ────────────────────────────────────────────────────────────────────

def main():
    print(f"\n🎸 Genre Enricher — {datetime.now(ET).strftime('%Y-%m-%d %H:%M %Z')}")

    if not ENRICHED_FILE.exists():
        print("  No events-enriched.json found, skipping.")
        return

    data = json.loads(ENRICHED_FILE.read_text())
    cache = load_genre_cache()

    # Collect unique non-theater artists not yet cached
    needed = []
    seen = set()
    for city_events in data.get("cities", {}).values():
        for ev in city_events:
            if ev.get("is_theater"):
                continue
            key = ev["name"].lower().strip()
            cached = cache_get_genres(cache, key)
            if cached is None and key not in seen:
                needed.append(ev["name"])
                seen.add(key)

    total_cached = len(cache)
    print(f"  {total_cached} artists in cache, {len(needed)} need lookup")

    if not needed:
        print("  ✅ Cache fully warm — nothing to fetch.")
    else:
        batch = needed[:MAX_LOOKUPS_PER_RUN]
        print(f"  Looking up {len(batch)} artists (max {MAX_LOOKUPS_PER_RUN}/run)...\n")

        looked_up = 0
        for artist in batch:
            key = artist.lower().strip()
            genres = lookup_genres(artist)
            if genres is None:
                print(f"  ✗ {artist} (error, will retry next run)")
            else:
                cache_set(cache, key, genres)
                tag_str = ", ".join(genres) if genres else "—"
                print(f"  ✓ {artist}: {tag_str}")
                looked_up += 1
            time.sleep(MB_DELAY)

        print(f"\n  Saved {looked_up} new entries to genre cache.")

        remaining = len(needed) - len(batch)
        if remaining > 0:
            print(f"  {remaining} artists still pending — will continue tomorrow.")

    # Always save cache (persists migrations + new lookups)
    save_genre_cache(cache)

    # Rewrite events-enriched.json with current cached genres
    for city_events in data.get("cities", {}).values():
        for ev in city_events:
            if not ev.get("is_theater"):
                key = ev["name"].lower().strip()
                ev["genres"] = cache_get_genres(cache, key) or []

    ENRICHED_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False))

    # Regenerate HTML
    result = subprocess.run(
        ["python3", str(WORKSPACE / "scripts/events-html-gen.py")],
        capture_output=True, text=True,
    )
    if result.returncode == 0:
        print("  " + result.stdout.strip())
    else:
        print(f"  ⚠️  HTML gen error: {result.stderr[:200]}")


if __name__ == "__main__":
    main()
