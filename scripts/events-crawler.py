#!/usr/bin/env python3
"""
Event Crawler — reads venues.md, fetches events via Songkick (music venues)
or direct scraping (theater venues), writes clean events.md.
Runs nightly. Removes past events automatically.
"""

import re
import time
import urllib.request
import urllib.error
import urllib.parse
from collections import defaultdict
from datetime import datetime, date
from pathlib import Path
from zoneinfo import ZoneInfo

WORKSPACE = Path("/home/exedev/.openclaw/workspace")
VENUES_FILE = WORKSPACE / "events/venues.md"
EVENTS_FILE = WORKSPACE / "events/events.md"
ET = ZoneInfo("America/New_York")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

MONTH_MAP = {
    "january": 1, "february": 2, "march": 3, "april": 4,
    "may": 5, "june": 6, "july": 7, "august": 8,
    "september": 9, "october": 10, "november": 11, "december": 12,
}


def parse_venues():
    """Parse venues.md → {city: [(name, official_url, songkick_id_or_None)]}"""
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
            for part in parts[2:]:
                m = re.match(r'songkick:(\d+)', part.strip())
                if m:
                    songkick_id = m.group(1)
            venues[current_city].append((name, official_url, songkick_id))
    return venues


def fetch(url, timeout=15):
    """Fetch URL text, return None on error."""
    try:
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            enc = resp.headers.get_content_charset() or "utf-8"
            return raw.decode(enc, errors="replace")
    except Exception as e:
        print(f"  ⚠️  {e}")
        return None


# ─── Songkick parser ────────────────────────────────────────────────────────

def parse_songkick(html, venue_name, venue_url):
    """
    Parse Songkick calendar page. Format in rendered text:
      'Thursday 26 February 2026\nArtist Name\nVenue, City...'
    """
    if not html:
        return []

    today = date.today()
    events = []
    seen = set()

    # Songkick embeds structured data as JSON-LD
    json_ld_re = re.compile(
        r'"startDate"\s*:\s*"(\d{4}-\d{2}-\d{2})[^"]*".*?"name"\s*:\s*"([^"]{3,80})"',
        re.DOTALL
    )
    import json as _json
    for m in json_ld_re.finditer(html):
        date_str = m.group(1)
        # Decode JSON unicode escapes (e.g. \u0026 → &)
        try:
            artist = _json.loads(f'"{m.group(2)}"')
        except Exception:
            artist = m.group(2)
        try:
            event_date = date.fromisoformat(date_str)
        except ValueError:
            continue
        if event_date < today:
            continue
        key = (event_date, artist[:25])
        if key in seen:
            continue
        seen.add(key)
        events.append({"name": artist, "date": event_date, "url": venue_url, "venue": venue_name})

    if events:
        return events

    # Fallback: parse text pattern "Day DD Month YYYY\nArtist\n..."
    # Strip HTML tags first
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

        # Next non-empty line is typically artist name
        artist = ""
        for j in range(i + 1, min(i + 5, len(lines))):
            candidate = lines[j].strip()
            if candidate and not date_re.search(candidate) and len(candidate) > 2:
                # Skip venue/city lines
                if not any(skip in candidate.lower() for skip in ["buy ticket", "save this", "don't miss", "new york", "brooklyn", "san francisco", "6 delancey", "1805 geary"]):
                    artist = candidate
                    break

        if not artist:
            continue

        # Clean up artist names with openers: "Artist and Opener" → "Artist (+ Opener)"
        artist = re.sub(r'\s+and\s+', ' + ', artist, flags=re.IGNORECASE)

        key = (event_date, artist[:25])
        if key in seen:
            continue
        seen.add(key)
        events.append({"name": artist, "date": event_date, "url": venue_url, "venue": venue_name})

    return events


# ─── Theater parser (direct scraping) ───────────────────────────────────────

def parse_theater(html, venue_name, venue_url):
    """Best-effort theater event extraction using schema.org JSON-LD."""
    if not html:
        return []

    today = date.today()
    events = []
    seen = set()

    # Try JSON-LD schema.org Event
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
        key = (event_date, name[:25])
        if key in seen:
            continue
        seen.add(key)

        # Try to find a specific event URL
        url_re = re.compile(r'"url"\s*:\s*"(https?://[^"]{10,100})"')
        event_url = venue_url
        # Look for url near the event block
        idx = m.start()
        nearby = html[max(0, idx-500):idx+500]
        u = url_re.search(nearby)
        if u:
            event_url = u.group(1)

        events.append({"name": name, "date": event_date, "url": event_url, "venue": venue_name})

    if events:
        return events

    # Fallback: date pattern scraping (same as before)
    text = re.sub(r'<[^>]+>', ' ', html)
    text = re.sub(r'\s+', ' ', text)
    date_re = re.compile(
        r'\b(January|February|March|April|May|June|July|August|September|'
        r'October|November|December)\s+(\d{1,2})(?:,?\s*(\d{4}))?',
        re.IGNORECASE
    )
    title_re = re.compile(r'[A-Z][A-Za-z0-9\s\'\-\&\:]{4,60}')
    for m in date_re.finditer(text):
        month = MONTH_MAP.get(m.group(1).lower())
        if not month:
            continue
        day = int(m.group(2))
        year = int(m.group(3)) if m.group(3) else today.year
        try:
            event_date = date(year, month, day)
        except ValueError:
            continue
        if event_date < today:
            continue

        ctx = text[max(0, m.start()-150):m.end()+150]
        titles = title_re.findall(ctx)
        skip = {"Buy Ticket", "Get Ticket", "More Info", "Learn More", "View All", "See All"}
        name = next((t.strip() for t in titles if t.strip() not in skip and len(t) > 5), None)
        if not name:
            continue

        key = (event_date, name[:25])
        if key in seen:
            continue
        seen.add(key)
        events.append({"name": name, "date": event_date, "url": venue_url, "venue": venue_name})

    return events[:15]


# ─── Main ────────────────────────────────────────────────────────────────────

def write_events_md(all_events_by_city):
    now = datetime.now(ET).strftime("%Y-%m-%d %H:%M %Z")
    lines = [f"# Upcoming Events", f"_Last updated: {now}_", ""]

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


def main():
    print(f"\n🎵 Event Crawler — {datetime.now(ET).strftime('%Y-%m-%d %H:%M %Z')}")
    venues_by_city = parse_venues()
    total = sum(len(v) for v in venues_by_city.values())
    print(f"Loaded {total} venues across {len(venues_by_city)} cities\n")

    all_events = defaultdict(list)
    today = date.today()

    for city, venues in venues_by_city.items():
        print(f"📍 {city}")
        for name, official_url, songkick_id in venues:
            if songkick_id:
                crawl_url = f"https://www.songkick.com/venues/{songkick_id}/calendar"
                print(f"  [Songkick] {name}...")
                html = fetch(crawl_url)
                events = parse_songkick(html, name, official_url)
            else:
                print(f"  [Direct]   {name}...")
                html = fetch(official_url)
                events = parse_theater(html, name, official_url)

            future = [e for e in events if e["date"] >= today]
            print(f"  → {len(future)} upcoming events")
            all_events[city].extend(future)
            time.sleep(1)

    write_events_md(all_events)

    total_events = sum(len(e) for e in all_events.values())
    print(f"\n✅ Done — {total_events} upcoming events written to events.md")
    for city, evs in all_events.items():
        print(f"   {city}: {len(evs)} events")


if __name__ == "__main__":
    main()
