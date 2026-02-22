#!/usr/bin/env python3
"""
Event Crawler — reads venues.md, fetches each venue's event page,
extracts upcoming events, and writes to events.md organized by city/date.
Runs nightly. Cleans up past events automatically.
"""

import re
import time
import urllib.request
import urllib.error
from collections import defaultdict
from datetime import datetime, date
from pathlib import Path
from zoneinfo import ZoneInfo

WORKSPACE = Path("/home/exedev/.openclaw/workspace")
VENUES_FILE = WORKSPACE / "events/venues.md"
EVENTS_FILE = WORKSPACE / "events/events.md"
ET = ZoneInfo("America/New_York")

# Date patterns to look for in HTML
DATE_PATTERNS = [
    r'\b(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|'
    r'Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)'
    r'\s+(\d{1,2})(?:st|nd|rd|th)?,?\s*(\d{4})?',
    r'\b(\d{1,2})[/\-](\d{1,2})(?:[/\-](\d{2,4}))?',
    r'\b(20\d{2})[/\-](\d{2})[/\-](\d{2})',
]

MONTH_MAP = {
    'jan': 1, 'feb': 2, 'mar': 3, 'apr': 4, 'may': 5, 'jun': 6,
    'jul': 7, 'aug': 8, 'sep': 9, 'oct': 10, 'nov': 11, 'dec': 12,
    'january': 1, 'february': 2, 'march': 3, 'april': 4, 'june': 6,
    'july': 7, 'august': 8, 'september': 9, 'october': 10, 'november': 11, 'december': 12,
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "en-US,en;q=0.9",
}


def parse_venues():
    """Parse venues.md into {city: [(name, url)]}"""
    venues = defaultdict(list)
    current_city = None
    text = VENUES_FILE.read_text()

    for line in text.splitlines():
        if line.startswith("## "):
            current_city = line[3:].strip()
        elif line.startswith("- **") and " | " in line and current_city:
            match = re.match(r'- \*\*(.+?)\*\*\s*\|\s*(https?://\S+)', line)
            if match:
                name, url = match.group(1), match.group(2)
                venues[current_city].append((name, url.rstrip("/")))

    return venues


def fetch_page(url, timeout=15):
    """Fetch a URL, return text or None."""
    try:
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            encoding = resp.headers.get_content_charset() or "utf-8"
            return raw.decode(encoding, errors="replace")
    except Exception as e:
        print(f"  ⚠️  Fetch error: {e}")
        return None


def strip_tags(html):
    """Very basic HTML tag stripper."""
    return re.sub(r'<[^>]+>', ' ', html)


def extract_events(html, venue_name, venue_url, city):
    """
    Best-effort extraction of event names and dates from HTML.
    Returns list of dicts: {name, date, url, venue, city}
    """
    if not html:
        return []

    today = date.today()
    events = []
    text = strip_tags(html)
    # Collapse whitespace
    text = re.sub(r'\s+', ' ', text)

    # Look for structured date blocks — find dates and nearby text
    date_re = re.compile(
        r'\b(January|February|March|April|May|June|July|August|September|October|November|December)'
        r'\s+(\d{1,2})(?:,?\s*(\d{4}))?',
        re.IGNORECASE
    )

    # Also look for links in original HTML that might be event pages
    link_re = re.compile(r'href=["\']([^"\']+)["\'][^>]*>([^<]{5,80})<', re.IGNORECASE)
    links = link_re.findall(html)

    # Find all date matches and try to pair with nearby text
    for m in date_re.finditer(text):
        month_str = m.group(1).lower()[:3]
        month = MONTH_MAP.get(month_str)
        if not month:
            continue
        day = int(m.group(2))
        year = int(m.group(3)) if m.group(3) else today.year

        # If the date seems past for this year, try next year
        try:
            event_date = date(year, month, day)
        except ValueError:
            continue

        if event_date < today:
            if event_date.replace(year=year + 1) >= today:
                event_date = event_date.replace(year=year + 1)
            else:
                continue  # genuinely past

        # Grab surrounding text as event name candidate
        start = max(0, m.start() - 120)
        end = min(len(text), m.end() + 120)
        context = text[start:end].strip()

        # Find the most title-like chunk near the date
        # Look for capitalized phrases
        title_re = re.compile(r'[A-Z][A-Za-z0-9\s\'\-\&\:\,\.]{3,60}')
        titles = title_re.findall(context)
        name = titles[0].strip() if titles else venue_name + " Event"

        # Skip obvious non-event strings
        skip = ["Buy Ticket", "Get Ticket", "More Info", "Learn More",
                "View All", "See All", "Load More", "Subscribe"]
        if any(s.lower() in name.lower() for s in skip):
            continue

        # Try to find a matching link
        event_url = venue_url
        for href, link_text in links:
            if any(word.lower() in link_text.lower() for word in name.split()[:3] if len(word) > 3):
                if href.startswith("http"):
                    event_url = href
                elif href.startswith("/"):
                    from urllib.parse import urlparse
                    parsed = urlparse(venue_url)
                    event_url = f"{parsed.scheme}://{parsed.netloc}{href}"
                break

        events.append({
            "name": name[:80],
            "date": event_date,
            "url": event_url,
            "venue": venue_name,
            "city": city,
        })

    # Deduplicate by (date, name[:20])
    seen = set()
    unique = []
    for e in events:
        key = (e["date"], e["name"][:20])
        if key not in seen:
            seen.add(key)
            unique.append(e)

    return unique[:20]  # cap per venue


def write_events_md(all_events_by_city):
    """Write events.md sorted by city then date."""
    now = datetime.now(ET).strftime("%Y-%m-%d %H:%M %Z")
    lines = [f"# Upcoming Events", f"_Last updated: {now}_", ""]

    city_order = ["New York City", "San Francisco"]
    for city in city_order:
        lines.append(f"## {city}")
        events = all_events_by_city.get(city, [])
        if not events:
            lines.append("_No upcoming events found — check back after the next crawl._")
            lines.append("")
            continue

        # Sort by date
        events.sort(key=lambda e: e["date"])

        current_date = None
        for ev in events:
            date_str = ev["date"].strftime("%b %-d, %Y")
            if ev["date"] != current_date:
                lines.append(f"### {date_str}")
                current_date = ev["date"]
            lines.append(f"- **{ev['name']}** @ {ev['venue']} — [Info / Tickets]({ev['url']})")

        lines.append("")

    EVENTS_FILE.write_text("\n".join(lines))


def main():
    print(f"\n🎵 Event Crawler — {datetime.now(ET).strftime('%Y-%m-%d %H:%M %Z')}")
    venues_by_city = parse_venues()
    total_venues = sum(len(v) for v in venues_by_city.values())
    print(f"Loaded {total_venues} venues across {len(venues_by_city)} cities\n")

    all_events_by_city = defaultdict(list)
    today = date.today()

    for city, venues in venues_by_city.items():
        print(f"📍 {city}")
        for venue_name, url in venues:
            print(f"  Fetching {venue_name}...")
            html = fetch_page(url)
            events = extract_events(html, venue_name, url, city)
            future = [e for e in events if e["date"] >= today]
            print(f"  → {len(future)} upcoming events found")
            all_events_by_city[city].extend(future)
            time.sleep(2)

    write_events_md(all_events_by_city)

    total = sum(len(e) for e in all_events_by_city.values())
    print(f"\n✅ Done — {total} upcoming events written to events.md")
    for city, evs in all_events_by_city.items():
        print(f"   {city}: {len(evs)} events")


if __name__ == "__main__":
    main()
