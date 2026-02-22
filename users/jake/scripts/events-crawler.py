#!/usr/bin/env python3
"""
Event Crawler — reads venues.md, fetches events via Songkick (music venues)
or direct scraping (theater venues), writes events-enriched.json + events.md.

Features:
- Cross-venue deduplication by (city, normalized artist name, date)
- Neighborhood data from venues.md
- Genre tags via MusicBrainz API with local cache (events/genre-cache.json)
- Runs nightly. Removes past events automatically.
"""

import json
import re
import time
import unicodedata
import urllib.request
import urllib.error
import urllib.parse
from collections import defaultdict
from datetime import datetime, date
from pathlib import Path
from zoneinfo import ZoneInfo

WORKSPACE = Path(__file__).parent.parent
VENUES_FILE   = WORKSPACE / "events/venues.md"
EVENTS_FILE   = WORKSPACE / "events/events.md"
ENRICHED_FILE = WORKSPACE / "events/events-enriched.json"
GENRE_CACHE   = WORKSPACE / "events/genre-cache.json"

ET = ZoneInfo("America/New_York")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

MB_HEADERS = {
    "User-Agent": "clawbot-events/1.0 (personal event aggregator)",
    "Accept": "application/json",
}

MONTH_MAP = {
    "january": 1, "february": 2, "march": 3, "april": 4,
    "may": 5, "june": 6, "july": 7, "august": 8,
    "september": 9, "october": 10, "november": 11, "december": 12,
}

# Genre tags to skip (too generic or spammy from MusicBrainz)
SKIP_TAGS = {
    "seen live", "male vocalists", "female vocalists", "american", "british",
    "canadian", "australian", "swedish", "norwegian", "german", "dutch",
    "under 2000 listeners", "all",
}

MAX_GENRES = 3


# ─── Venue parsing ───────────────────────────────────────────────────────────

def parse_venues():
    """Parse venues.md → {city: [(name, official_url, songkick_id, neighborhood)]}"""
    venues = defaultdict(list)
    current_city = None
    for line in VENUES_FILE.read_text().splitlines():
        if line.startswith("## "):
            current_city = line[3:].strip()
        elif line.startswith("- **") and " | " in line and current_city:
            parts = [p.strip() for p in line.split("|")]
            name_match = re.match(r'- \*\*(.+?)\*\*', parts[0])
            if not name_match:
                continue
            name = name_match.group(1)
            official_url = parts[1].strip() if len(parts) > 1 else ""
            songkick_id = None
            neighborhood = None
            for part in parts[2:]:
                part = part.strip()
                m = re.match(r'songkick:(\d+)', part)
                if m:
                    songkick_id = m.group(1)
                m = re.match(r'hood:(.+)', part)
                if m:
                    neighborhood = m.group(1)
            venues[current_city].append((name, official_url, songkick_id, neighborhood))
    return venues


# ─── HTTP fetch ──────────────────────────────────────────────────────────────

def fetch(url, headers=None, timeout=15):
    """Fetch URL, return text or None on error."""
    try:
        req = urllib.request.Request(url, headers=headers or HEADERS)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            enc = resp.headers.get_content_charset() or "utf-8"
            return raw.decode(enc, errors="replace")
    except Exception as e:
        print(f"  ⚠️  {e}")
        return None


# ─── Genre cache + MusicBrainz ───────────────────────────────────────────────

def load_genre_cache():
    try:
        return json.loads(GENRE_CACHE.read_text())
    except Exception:
        return {}


def save_genre_cache(cache):
    GENRE_CACHE.write_text(json.dumps(cache, indent=2, sort_keys=True))


def lookup_genres_musicbrainz(artist_name, cache):
    """
    Look up genre tags for an artist via MusicBrainz API.
    Returns list of up to MAX_GENRES genre strings, or [].
    Rate limit: 1 req/sec (enforced by caller).
    """
    key = artist_name.lower().strip()
    if key in cache:
        return cache[key]

    try:
        query = urllib.parse.urlencode({"query": f'artist:"{artist_name}"', "fmt": "json", "limit": "3"})
        url = f"https://musicbrainz.org/ws/2/artist/?{query}"
        data = fetch(url, headers=MB_HEADERS, timeout=10)
        if not data:
            cache[key] = []
            return []

        parsed = json.loads(data)
        artists = parsed.get("artists", [])
        if not artists:
            cache[key] = []
            return []

        # Take the first (best-scored) match
        tags = artists[0].get("tags", [])
        # Sort by count descending, filter junk
        tags = sorted(tags, key=lambda t: t.get("count", 0), reverse=True)
        genres = []
        for t in tags:
            name = t.get("name", "").lower().strip()
            if name and name not in SKIP_TAGS and len(name) > 1:
                genres.append(name)
            if len(genres) >= MAX_GENRES:
                break

        cache[key] = genres
        return genres

    except Exception as e:
        print(f"    [MusicBrainz] error for '{artist_name}': {e}")
        cache[key] = []
        return []


# ─── Songkick parser ─────────────────────────────────────────────────────────

def parse_songkick(html, venue_name, venue_url):
    if not html:
        return []

    today = date.today()
    events = []
    seen = set()

    # Primary: JSON-LD structured data embedded by Songkick
    json_ld_re = re.compile(
        r'"startDate"\s*:\s*"(\d{4}-\d{2}-\d{2})[^"]*".*?"name"\s*:\s*"([^"]{3,80})"',
        re.DOTALL
    )
    for m in json_ld_re.finditer(html):
        date_str = m.group(1)
        try:
            artist = json.loads(f'"{m.group(2)}"')
        except Exception:
            artist = m.group(2)
        try:
            event_date = date.fromisoformat(date_str)
        except ValueError:
            continue
        if event_date < today:
            continue

        # Try to find a per-event URL nearby
        idx = m.start()
        nearby = html[max(0, idx - 500):idx + 500]
        event_url = venue_url
        u = re.search(r'"url"\s*:\s*"(https?://[^"]{10,120})"', nearby)
        if u:
            event_url = u.group(1)

        key = (event_date, artist[:30])
        if key in seen:
            continue
        seen.add(key)
        events.append({"name": artist, "date": event_date, "url": event_url, "venue": venue_name})

    if events:
        return events

    # Fallback: text pattern "Day DD Month YYYY\nArtist\n..."
    text = re.sub(r'<[^>]+>', '\n', html)
    text = re.sub(r'&amp;', '&', text)
    text = re.sub(r'&#\d+;', '', text)
    text = re.sub(r'\n{3,}', '\n\n', text)

    date_re = re.compile(
        r'(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\s+'
        r'(\d{1,2})\s+(January|February|March|April|May|June|July|August|'
        r'September|October|November|December)\s+(\d{4})',
        re.IGNORECASE
    )
    lines = text.splitlines()
    for i, line in enumerate(lines):
        m = date_re.search(line)
        if not m:
            continue
        day, month_str, year = int(m.group(1)), m.group(2).lower(), int(m.group(3))
        month = MONTH_MAP.get(month_str)
        if not month:
            continue
        try:
            event_date = date(year, month, day)
        except ValueError:
            continue
        if event_date < today:
            continue

        artist = ""
        for j in range(i + 1, min(i + 5, len(lines))):
            candidate = lines[j].strip()
            skip_words = ["buy ticket", "save this", "don't miss", "new york",
                          "brooklyn", "san francisco", "6 delancey", "1805 geary"]
            if candidate and not date_re.search(candidate) and len(candidate) > 2:
                if not any(s in candidate.lower() for s in skip_words):
                    artist = candidate
                    break

        if not artist:
            continue

        key = (event_date, artist[:30])
        if key in seen:
            continue
        seen.add(key)
        events.append({"name": artist, "date": event_date, "url": venue_url, "venue": venue_name})

    return events


# ─── Theater parser ──────────────────────────────────────────────────────────

def parse_theater(html, venue_name, venue_url):
    if not html:
        return []

    today = date.today()
    events = []
    seen = set()

    json_ld_re = re.compile(
        r'"@type"\s*:\s*"(?:Event|TheaterEvent|MusicEvent|VisualArtsEvent)"'
        r'.*?"name"\s*:\s*"([^"]{3,100})"'
        r'(?:.*?"startDate"\s*:\s*"(\d{4}-\d{2}-\d{2})[^"]*")?',
        re.DOTALL
    )
    for m in json_ld_re.finditer(html):
        name = m.group(1).strip()
        date_str = m.group(2)
        if not date_str:
            continue
        try:
            event_date = date.fromisoformat(date_str)
        except ValueError:
            continue
        if event_date < today:
            continue
        key = (event_date, name[:30])
        if key in seen:
            continue
        seen.add(key)
        events.append({"name": name, "date": event_date, "url": venue_url, "venue": venue_name})

    return events


# ─── Deduplication ───────────────────────────────────────────────────────────

def normalize_name(name):
    """Normalize artist name for dedup comparison."""
    name = name.lower().strip()
    # Unicode normalize
    name = unicodedata.normalize("NFKD", name)
    name = name.encode("ascii", "ignore").decode()
    # Strip common prefixes
    name = re.sub(r'^the\s+', '', name)
    # Remove punctuation
    name = re.sub(r'[^\w\s]', '', name)
    # Collapse whitespace
    name = re.sub(r'\s+', ' ', name).strip()
    return name


def dedup_events(events):
    """
    Dedup a list of events by (date, normalized_name).
    When duplicates exist, prefer the record with the most specific URL
    (event-specific URL > venue listing page).
    """
    best = {}  # key → event dict
    for ev in events:
        key = (ev["date"], normalize_name(ev["name"]))
        if key not in best:
            best[key] = ev
        else:
            # Prefer event-specific URL (longer, more specific path)
            existing_url = best[key]["url"]
            new_url = ev["url"]
            if len(new_url) > len(existing_url):
                # Keep everything else from the existing record, just update URL
                best[key] = {**best[key], "url": new_url}
    return list(best.values())


# ─── Genre enrichment ────────────────────────────────────────────────────────

def enrich_genres(events, genre_cache):
    """
    Add genre tags to each event in place.
    Only queries MusicBrainz for new artists not in cache.
    Skips theater events (no meaningful genre tagging).
    """
    mb_calls = 0
    for ev in events:
        if ev.get("is_theater"):
            ev["genres"] = []
            continue
        key = ev["name"].lower().strip()
        if key not in genre_cache:
            genres = lookup_genres_musicbrainz(ev["name"], genre_cache)
            mb_calls += 1
            time.sleep(1.1)  # MusicBrainz rate limit: 1 req/sec
        ev["genres"] = genre_cache.get(key, [])
    if mb_calls:
        print(f"  [MusicBrainz] {mb_calls} new artist lookups")
    return events


# ─── Output writers ──────────────────────────────────────────────────────────

def write_enriched_json(all_events_by_city):
    """Write events-enriched.json — primary data store for HTML generator."""
    now_str = datetime.now(ET).isoformat()
    output = {
        "generated_at": now_str,
        "cities": {}
    }
    for city in ["New York City", "San Francisco"]:
        evs = sorted(all_events_by_city.get(city, []), key=lambda e: e["date"])
        output["cities"][city] = [
            {
                "name": ev["name"],
                "venue": ev["venue"],
                "neighborhood": ev.get("neighborhood", ""),
                "date": ev["date"].isoformat(),
                "url": ev["url"],
                "genres": ev.get("genres", []),
                "is_theater": ev.get("is_theater", False),
            }
            for ev in evs
        ]
    ENRICHED_FILE.write_text(json.dumps(output, indent=2, ensure_ascii=False))


def write_events_md(all_events_by_city):
    """Write human-readable events.md (simple format, no enrichment fields)."""
    now = datetime.now(ET).strftime("%Y-%m-%d %H:%M %Z")
    lines = ["# Upcoming Events", f"_Last updated: {now}_", ""]
    for city in ["New York City", "San Francisco"]:
        lines.append(f"## {city}")
        events = sorted(all_events_by_city.get(city, []), key=lambda e: e["date"])
        if not events:
            lines.append("_No upcoming events found._")
            lines.append("")
            continue
        current_date = None
        for ev in events:
            if ev["date"] != current_date:
                lines.append(f"### {ev['date'].strftime('%b %-d, %Y')}")
                current_date = ev["date"]
            name = ev["name"].replace("&", "&amp;")
            lines.append(f"- **{name}** @ {ev['venue']} — [Info / Tickets]({ev['url']})")
        lines.append("")
    EVENTS_FILE.write_text("\n".join(lines))


# ─── Main ────────────────────────────────────────────────────────────────────

def main():
    print(f"\n🎵 Event Crawler — {datetime.now(ET).strftime('%Y-%m-%d %H:%M %Z')}")
    venues_by_city = parse_venues()
    total = sum(len(v) for v in venues_by_city.values())
    print(f"Loaded {total} venues across {len(venues_by_city)} cities\n")

    genre_cache = load_genre_cache()
    all_events = defaultdict(list)
    today = date.today()

    for city, venues in venues_by_city.items():
        print(f"📍 {city}")
        for name, official_url, songkick_id, neighborhood in venues:
            if songkick_id:
                crawl_url = f"https://www.songkick.com/venues/{songkick_id}/calendar"
                print(f"  [Songkick] {name}...")
                html = fetch(crawl_url)
                events = parse_songkick(html, name, official_url)
                is_theater = False
            else:
                print(f"  [Direct]   {name}...")
                html = fetch(official_url)
                events = parse_theater(html, name, official_url)
                is_theater = True

            future = [e for e in events if e["date"] >= today]
            # Tag each event with neighborhood + is_theater
            for ev in future:
                ev["neighborhood"] = neighborhood or ""
                ev["is_theater"] = is_theater
            print(f"  → {len(future)} upcoming events")
            all_events[city].extend(future)
            time.sleep(1)

    # Dedup per city
    total_before = sum(len(v) for v in all_events.values())
    for city in all_events:
        all_events[city] = dedup_events(all_events[city])
    total_after = sum(len(v) for v in all_events.values())
    print(f"\n🔁 Dedup: {total_before} → {total_after} events ({total_before - total_after} removed)")

    # Attach cached genres (don't do live lookups here — see events-genres.py)
    for city, events in all_events.items():
        for ev in events:
            if ev.get("is_theater"):
                ev["genres"] = []
            else:
                key = ev["name"].lower().strip()
                ev["genres"] = genre_cache.get(key, [])

    # Write outputs
    write_enriched_json(all_events)
    write_events_md(all_events)

    total_events = sum(len(e) for e in all_events.values())
    print(f"\n✅ Done — {total_events} upcoming events")
    for city, evs in all_events.items():
        print(f"   {city}: {len(evs)} events")


if __name__ == "__main__":
    main()
