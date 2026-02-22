#!/usr/bin/env python3
"""
Event Discovery — runs nightly, searches for new venues/events in NYC and SF.
Surfaces candidates to events/candidates.md for Jake's review.
"""

import json
import os
import re
import urllib.request
import urllib.parse
from datetime import datetime, date
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv_loader import load_dotenv
load_dotenv()

WORKSPACE = Path(__file__).parent.parent
VENUES_FILE = WORKSPACE / "events/venues.md"
CANDIDATES_FILE = WORKSPACE / "events/candidates.md"
STATE_FILE = WORKSPACE / "scripts/discovery-state.json"
ET = ZoneInfo("America/New_York")

# Rotating search queries — advances through list each run
SEARCHES = [
    ("NYC", "best small music venues NYC 2026"),
    ("NYC", "indie rock shows NYC upcoming 2026"),
    ("NYC", "jazz concerts New York City upcoming"),
    ("NYC", "new music venue opening NYC 2026"),
    ("NYC", "underground techno NYC"),
    ("NYC", "off-broadway theater NYC 2026"),
    ("NYC", "experimental music show Brooklyn"),
    ("NYC", "new theater production NYC"),
    ("SF",  "best small music venues San Francisco 2026"),
    ("SF",  "indie rock shows San Francisco upcoming"),
    ("SF",  "jazz SF upcoming shows 2026"),
    ("SF",  "new music venue opening San Francisco"),
    ("SF",  "SF fringe theater 2026"),
    ("SF",  "experimental music San Francisco"),
    ("SF",  "hidden gem music venue Bay Area"),
]

BRAVE_API_KEY = os.environ.get("BRAVE_API_KEY", "")


def load_state():
    try:
        return json.loads(STATE_FILE.read_text())
    except Exception:
        return {"search_index": 0, "rejected": []}


def save_state(state):
    STATE_FILE.write_text(json.dumps(state, indent=2))


def load_known_venues():
    """Return set of lowercase venue names already in venues.md."""
    text = VENUES_FILE.read_text().lower()
    names = re.findall(r'\*\*(.+?)\*\*', text)
    return set(names)


def load_rejected():
    """Return set of lowercase rejected venue names from candidates.md."""
    text = CANDIDATES_FILE.read_text()
    rejected_section = False
    rejected = set()
    for line in text.splitlines():
        if "## Rejected" in line:
            rejected_section = True
        elif rejected_section and line.startswith("###"):
            name = line[4:].split("(")[0].strip().lower()
            rejected.add(name)
    return rejected


def search_brave(query):
    """Search using Brave API. Returns list of {title, url, description}."""
    if not BRAVE_API_KEY:
        print(f"  ⚠️  No BRAVE_API_KEY set, skipping search: {query}")
        return []

    params = urllib.parse.urlencode({"q": query, "count": 8, "country": "us"})
    url = f"https://api.search.brave.com/res/v1/web/search?{params}"
    req = urllib.request.Request(url, headers={
        "Accept": "application/json",
        "Accept-Encoding": "gzip",
        "X-Subscription-Token": BRAVE_API_KEY,
    })
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
            results = data.get("web", {}).get("results", [])
            return [{"title": r.get("title", ""), "url": r.get("url", ""), "description": r.get("description", "")}
                    for r in results]
    except Exception as e:
        print(f"  ⚠️  Search error: {e}")
        return []


def looks_like_venue(result, city):
    """Heuristic: does this result look like a venue listing?"""
    title = result["title"].lower()
    desc = result["description"].lower()
    url = result["url"].lower()
    city_lc = city.lower()

    # Must mention the city somewhere
    city_terms = {"nyc": ["nyc", "new york", "brooklyn", "manhattan"],
                  "sf": ["san francisco", "sf", "bay area", "oakland"]}
    city_match = any(t in title + desc for t in city_terms.get(city_lc, [city_lc]))
    if not city_match:
        return False

    # Should mention venue-like terms
    venue_terms = ["venue", "music hall", "theater", "theatre", "club", "ballroom",
                   "lounge", "bar", "pub", "events", "shows", "concert", "performance"]
    return any(t in title + desc + url for t in venue_terms)


def extract_venue_name(result):
    """Try to extract a clean venue name from a search result."""
    title = result["title"]
    # Remove common suffixes
    title = re.sub(r'\s*[|\-–]\s*.+$', '', title).strip()
    title = re.sub(r'\s*(Official Site|Home|Events|Tickets|Calendar).*$', '', title, flags=re.IGNORECASE).strip()
    return title[:60] if title else None


def parse_existing_candidates():
    """Return set of pending candidate names (lowercase)."""
    text = CANDIDATES_FILE.read_text()
    pending = set()
    in_pending = False
    for line in text.splitlines():
        if "## Pending" in line:
            in_pending = True
        elif line.startswith("## "):
            in_pending = False
        elif in_pending and line.startswith("### "):
            name = line[4:].split("(")[0].strip().lower()
            pending.add(name)
    return pending


def append_candidate(name, city, url, query, description):
    """Add a new candidate to candidates.md."""
    today_str = date.today().strftime("%Y-%m-%d")
    text = CANDIDATES_FILE.read_text()

    entry = (
        f"\n### {name} ({city}) — discovered {today_str}\n"
        f"- **Events page:** {url}\n"
        f"- **Why flagged:** Found via search: \"{query}\"\n"
        f"- **Context:** {description[:200]}\n"
    )

    # Insert after "## Pending" line
    text = text.replace(
        "_(none yet — discovery runs nightly)_",
        entry.strip()
    )
    if entry.strip() not in text:
        text = re.sub(r'(## Pending\n)', r'\1' + entry, text)

    CANDIDATES_FILE.write_text(text)


def main():
    print(f"\n🔍 Event Discovery — {datetime.now(ET).strftime('%Y-%m-%d %H:%M %Z')}")

    state = load_state()
    known = load_known_venues()
    rejected = load_rejected()
    existing_candidates = parse_existing_candidates()
    already_known = known | rejected | existing_candidates

    # Run 3 searches from the rotating list
    idx = state.get("search_index", 0)
    searches_this_run = []
    for i in range(3):
        searches_this_run.append(SEARCHES[(idx + i) % len(SEARCHES)])
    state["search_index"] = (idx + 3) % len(SEARCHES)

    new_candidates = []

    for city, query in searches_this_run:
        print(f"\n  🔎 [{city}] {query}")
        results = search_brave(query)
        print(f"     {len(results)} results")

        for r in results:
            if not looks_like_venue(r, city):
                continue
            name = extract_venue_name(r)
            if not name or name.lower() in already_known:
                continue

            print(f"     ✨ New candidate: {name}")
            append_candidate(name, city, r["url"], query, r["description"])
            new_candidates.append(name)
            already_known.add(name.lower())

    save_state(state)

    print(f"\n✅ Discovery done — {len(new_candidates)} new candidate(s) found")
    if new_candidates:
        print("   New: " + ", ".join(new_candidates))
    else:
        print("   Nothing new this run.")


if __name__ == "__main__":
    main()
