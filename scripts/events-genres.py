#!/usr/bin/env python3
"""
Genre Enricher — looks up genres for artists in events-enriched.json
via MusicBrainz API, caches results in events/genre-cache.json.

Designed to run separately from the crawler (after it):
- Max 60 lookups per run to stay within MusicBrainz rate limits
- Skips artists already in cache (including failed lookups)
- On completion, rewrites events-enriched.json with updated genres
  and regenerates docs/index.html

Cron: run at 10am UTC (after crawler at 7am and html-gen at 9am)
"""

import json
import re
import time
import urllib.request
import urllib.parse
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo

WORKSPACE     = Path(__file__).parent.parent
ENRICHED_FILE = WORKSPACE / "events/events-enriched.json"
GENRE_CACHE   = WORKSPACE / "events/genre-cache.json"
ET            = ZoneInfo("America/New_York")

MAX_LOOKUPS_PER_RUN = 60
MB_DELAY = 1.1  # seconds between MusicBrainz requests

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


def load_genre_cache():
    try:
        return json.loads(GENRE_CACHE.read_text())
    except Exception:
        return {}


def save_genre_cache(cache):
    GENRE_CACHE.write_text(json.dumps(cache, indent=2, sort_keys=True))


def lookup_genres(artist_name):
    """Query MusicBrainz for artist genre tags. Returns list of genre strings."""
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

        tags = artists[0].get("tags", [])
        tags = sorted(tags, key=lambda t: t.get("count", 0), reverse=True)
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
        return None  # None = failed (don't cache), [] = genuinely no genres


def main():
    print(f"\n🎸 Genre Enricher — {datetime.now(ET).strftime('%Y-%m-%d %H:%M %Z')}")

    if not ENRICHED_FILE.exists():
        print("  No events-enriched.json found, skipping.")
        return

    data = json.loads(ENRICHED_FILE.read_text())
    cache = load_genre_cache()

    # Collect unique non-theater artist names not yet in cache
    needed = []
    seen = set()
    for city_events in data.get("cities", {}).values():
        for ev in city_events:
            if ev.get("is_theater"):
                continue
            key = ev["name"].lower().strip()
            if key not in cache and key not in seen:
                needed.append(ev["name"])
                seen.add(key)

    print(f"  {len(cache)} artists cached, {len(needed)} need lookup")

    if not needed:
        print("  ✅ All artists already cached.")
        return

    batch = needed[:MAX_LOOKUPS_PER_RUN]
    print(f"  Looking up {len(batch)} artists (max {MAX_LOOKUPS_PER_RUN}/run)...\n")

    looked_up = 0
    for artist in batch:
        key = artist.lower().strip()
        genres = lookup_genres(artist)
        if genres is None:
            # API error — don't cache, will retry next run
            print(f"  ✗ {artist} (error, will retry)")
        else:
            cache[key] = genres
            tag_str = ", ".join(genres) if genres else "—"
            print(f"  ✓ {artist}: {tag_str}")
            looked_up += 1
        time.sleep(MB_DELAY)

    save_genre_cache(cache)
    print(f"\n  Saved {looked_up} new entries to genre cache.")

    # Rewrite events-enriched.json with updated genres
    for city_events in data.get("cities", {}).values():
        for ev in city_events:
            if not ev.get("is_theater"):
                key = ev["name"].lower().strip()
                ev["genres"] = cache.get(key, [])

    ENRICHED_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    print("  Updated events-enriched.json with genres.")

    # Regenerate HTML
    import subprocess
    result = subprocess.run(
        ["python3", str(WORKSPACE / "scripts/events-html-gen.py")],
        capture_output=True, text=True
    )
    if result.returncode == 0:
        print("  " + result.stdout.strip())
    else:
        print(f"  ⚠️  HTML gen error: {result.stderr[:200]}")

    remaining = len(needed) - len(batch)
    if remaining > 0:
        print(f"\n  {remaining} artists still need lookup — will run again tomorrow.")


if __name__ == "__main__":
    main()
