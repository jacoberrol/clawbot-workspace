#!/usr/bin/env python3
"""
travel-scout.py — Discover top restaurants, bars, and highlights for upcoming trips.

Two-pass approach:
  Pass 1: Brave Search → curated listicle articles (Eater, Infatuation, Michelin, Timeout, etc.)
  Pass 2: Fetch those articles → extract actual venue names → search each venue for
          its direct website + reservation link (Resy, OpenTable, Tock, etc.)

Usage:
    python3 travel-scout.py [trip-id]

Requires:
    BRAVE_API_KEY environment variable
"""

import os
import sys
import re
import json
import time
import gzip
import datetime
import urllib.request
import urllib.parse
import urllib.error
from pathlib import Path

TRIPS_FILE = Path(__file__).parent / "trips.json"
BRAVE_API_URL = "https://api.search.brave.com/res/v1/web/search"

# --- Search query templates (Pass 1) ---
DINING_QUERIES = [
    "{city} best local restaurants 2025 2026 not touristy",
    "{city} best cocktail bars locals favorite hidden gems",
    "{city} best dinner restaurants {vibe} 2025",
    "{city} city highlights must visit not tourist trap",
]
WORK_QUERIES = [
    "{city} best cafes laptop wifi outlets work friendly 2025",
    "{city} best specialty coffee third wave cafe",
]

# Article domains we trust for listicle parsing
LISTICLE_DOMAINS = [
    "eater.com", "infatuation.com", "timeout.com", "theguardian.com",
    "nytimes.com", "telegraph.co.uk", "independent.co.uk", "michelin.com",
    "cntraveler.com", "thetravelista.net", "timeout.com", "misstourist.com",
    "lifeinthefastjane.com", "pariseater.com", "travelsonpoint.com",
]

# Domains we know are reservation platforms
RESERVATION_DOMAINS = {
    "resy.com": "Resy",
    "opentable.com": "OpenTable",
    "tock.com": "Tock",
    "sevenrooms.com": "SevenRooms",
    "yelp.com/reservations": "Yelp",
    "quandoo.co.uk": "Quandoo",
    "thefork.com": "TheFork",
    "lafourchette.com": "TheFork",
}

# Generic article/review domains — NOT official venue sites
NON_VENUE_DOMAINS = [
    "eater.com", "infatuation.com", "timeout.com", "theguardian.com",
    "nytimes.com", "telegraph.co.uk", "independent.co.uk", "michelin.com",
    "cntraveler.com", "yelp.com", "tripadvisor.com", "google.com",
    "thetravelista.net", "misstourist.com", "lifeinthefastjane.com",
    "pariseater.com", "travelsonpoint.com", "wikipedia.org", "timeout.co.uk",
    "booking.com", "expedia.com", "airbnb.com", "instagram.com", "facebook.com",
    "twitter.com", "trustpilot.com", "foursquare.com",
]


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

def brave_search(query: str, api_key: str, count: int = 5) -> list[dict]:
    """Run a Brave Search query, return web results."""
    params = urllib.parse.urlencode({
        "q": query,
        "count": count,
        "search_lang": "en",
        "result_filter": "web",
    })
    req = urllib.request.Request(
        f"{BRAVE_API_URL}?{params}",
        headers={"Accept": "application/json", "X-Subscription-Token": api_key},
    )
    try:
        with urllib.request.urlopen(req, timeout=12) as resp:
            return json.loads(resp.read().decode("utf-8")).get("web", {}).get("results", [])
    except Exception as e:
        print(f"    [warn] Search failed '{query[:60]}': {e}")
        return []


def fetch_page(url: str) -> str:
    """Fetch a web page and return decoded text. Handles gzip."""
    req = urllib.request.Request(url, headers={
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/122.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    })
    try:
        with urllib.request.urlopen(req, timeout=12) as resp:
            raw = resp.read()
            if raw[:2] == b'\x1f\x8b':
                raw = gzip.decompress(raw)
            ct = resp.headers.get("Content-Type", "utf-8")
            charset = "utf-8"
            if "charset=" in ct:
                charset = ct.split("charset=")[-1].strip().split(";")[0]
            return raw.decode(charset, errors="replace")
    except Exception as e:
        print(f"    [warn] Fetch failed {url[:60]}: {e}")
        return ""


def strip_tags(html: str) -> str:
    """Remove HTML tags and decode common entities."""
    text = re.sub(r'<[^>]+>', ' ', html)
    text = re.sub(r'&amp;', '&', text)
    text = re.sub(r'&nbsp;', ' ', text)
    text = re.sub(r'&#x27;|&apos;', "'", text)
    text = re.sub(r'&quot;', '"', text)
    text = re.sub(r'&#\d+;', '', text)
    text = re.sub(r'&[a-z]+;', '', text)
    return re.sub(r'\s+', ' ', text).strip()


# ---------------------------------------------------------------------------
# Pass 1: find curated articles
# ---------------------------------------------------------------------------

def search_articles(city: str, prefs: dict, api_key: str, work: bool = False) -> list[dict]:
    """Run search queries, return top article results from trusted domains."""
    vibe = prefs.get("vibe", "upscale-casual local")
    queries = WORK_QUERIES if work else DINING_QUERIES
    seen_urls: set[str] = set()
    articles = []

    for q_tmpl in queries:
        q = q_tmpl.format(city=city, vibe=vibe)
        print(f"    → {q}")
        for r in brave_search(q, api_key, count=7):
            url = r.get("url", "")
            if url in seen_urls:
                continue
            seen_urls.add(url)
            domain_match = any(d in url for d in LISTICLE_DOMAINS)
            articles.append({
                "url": url,
                "title": r.get("title", ""),
                "description": r.get("description", ""),
                "trusted": domain_match,
            })
        time.sleep(0.4)

    # Sort: trusted sources first
    articles.sort(key=lambda a: (not a["trusted"], -len(a["description"])))
    return articles


# ---------------------------------------------------------------------------
# Pass 2: extract venue names from article HTML
# ---------------------------------------------------------------------------

def extract_names_from_html(html: str) -> list[str]:
    """
    Pull venue names out of listicle HTML.
    Tries multiple patterns: numbered headings, bold names, anchor text.
    """
    # Remove scripts/styles/nav
    html = re.sub(r'<script[^>]*>.*?</script>', ' ', html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r'<style[^>]*>.*?</style>', ' ', html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r'<nav[^>]*>.*?</nav>', ' ', html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r'<header[^>]*>.*?</header>', ' ', html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r'<footer[^>]*>.*?</footer>', ' ', html, flags=re.DOTALL | re.IGNORECASE)
    # Convert arrow entities/icons to nothing before stripping
    html = re.sub(r'(?:&#x2192;|&#8594;|→|Arrow|»|›)', '', html)

    names: list[str] = []

    # Pattern A: <h2> or <h3> headings, optionally preceded by a number
    for m in re.finditer(r'<h[2-4][^>]*>(.*?)</h[2-4]>', html, re.DOTALL | re.IGNORECASE):
        raw = strip_tags(m.group(1))
        raw = re.sub(r'^\d+[\.\):\-]\s*', '', raw).strip()
        if 3 < len(raw) < 65:
            names.append(raw)

    # Pattern B: <strong> in list items (Eater, Infatuation style)
    for m in re.finditer(r'<(?:li|p)[^>]*>.*?<strong>(.*?)</strong>', html, re.DOTALL | re.IGNORECASE):
        raw = strip_tags(m.group(1)).strip()
        if 3 < len(raw) < 65:
            names.append(raw)

    # Pattern C: anchor text inside list items
    for m in re.finditer(r'<li[^>]*>\s*(?:<[^>]+>)*\s*<a[^>]*>(.*?)</a>', html, re.DOTALL | re.IGNORECASE):
        raw = strip_tags(m.group(1)).strip()
        if 3 < len(raw) < 55 and re.match(r'^[A-Z\u00C0-\u017E]', raw):
            names.append(raw)

    # Deduplicate and filter noise
    NOISE_EXACT = {
        "best", "top", "home", "menu", "about", "contact", "read more",
        "learn more", "see more", "reservations", "book now", "click here",
        "visit website", "get directions", "view on map", "instagram",
        "twitter", "facebook", "share", "newsletter", "sign up", "login",
        "search", "london", "paris", "new york", "the spots", "central",
        "north", "south", "east", "west", "map", "back to top",
        "choose a city", "choose a time out city", "choose a time out market",
    }
    NOISE_PATTERNS = [
        r'^\d{4}',              # Starts with year like "2025:"
        r'[?!]$',              # Ends with question/exclamation
        r'^(what|why|how|where|when|who)\b',  # Question words
        r'^\s*:',              # Starts with colon
        r'^(top|best|the best|our|we|i)\s+\d',  # "Top 10..." type headers
        r'\bcocktail bars\b',  # Generic category labels
        r'\brestaurants in\b',
        r'\bbars in\b',
    ]

    seen: set[str] = set()
    clean: list[str] = []
    for n in names:
        n = n.strip()
        key = n.lower().strip()
        if key in seen or len(key) <= 3:
            continue
        if key in NOISE_EXACT:
            continue
        if any(re.search(p, key, re.IGNORECASE) for p in NOISE_PATTERNS):
            continue
        # Skip all-caps words that aren't acronyms (likely UI labels like "THE SPOTS")
        if n.isupper() and len(n) > 5:
            continue
        seen.add(key)
        clean.append(n)

    return clean[:25]


# ---------------------------------------------------------------------------
# Pass 2b: for each venue name, find its direct website + reservation link
# ---------------------------------------------------------------------------

def find_venue_links(name: str, city: str, api_key: str) -> dict:
    """
    Brave-search for the venue by name+city to find:
      - official website
      - reservation platform (Resy, OpenTable, Tock, etc.)
    """
    query = f'"{name}" {city}'
    results = brave_search(query, api_key, count=6)
    time.sleep(0.3)

    website = None
    reservation_url = None
    reservation_platform = None
    description = ""

    for r in results:
        url = r.get("url", "").rstrip("/")
        desc = r.get("description", "")

        if not description and desc:
            description = desc

        # Check reservation platforms first
        for domain, platform in RESERVATION_DOMAINS.items():
            if domain in url and not reservation_url:
                reservation_url = url
                reservation_platform = platform
                break

        # Check for official venue website
        is_noise = any(d in url for d in NON_VENUE_DOMAINS)
        if not is_noise and not website:
            # Sanity check: domain should plausibly relate to venue name
            try:
                domain = urllib.parse.urlparse(url).netloc.lower().lstrip("www.")
            except Exception:
                domain = ""
            slug = re.sub(r'[^a-z0-9]', '', name.lower())
            # Accept if venue name words appear in domain OR it's a short, specific domain
            name_words = [w for w in re.split(r'\W+', name.lower()) if len(w) > 2]
            domain_match = any(w in domain for w in name_words) or any(w in slug[:8] for w in [domain[:8]])
            if domain_match or (len(name_words) >= 2 and any(w in domain for w in name_words)):
                website = url

    return {
        "name": name,
        "website": website,
        "reservation_url": reservation_url,
        "reservation_platform": reservation_platform,
        "description": description[:200] if description else "",
    }


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

def scout_city(city: str, trip: dict, api_key: str) -> tuple[list[dict], list[dict]]:
    """
    Full two-pass scout for a city.
    Returns (dining_venues, work_venues), each a list of enriched dicts.
    """
    prefs = trip.get("preferences", {})
    categories = prefs.get("categories", [])

    print(f"\n  ── {city}: dining & bars ──")
    dining = _scout_category(city, prefs, api_key, work=False)

    work: list[dict] = []
    if "work-friendly" in categories:
        print(f"\n  ── {city}: work-friendly cafes ──")
        work = _scout_category(city, prefs, api_key, work=True)

    return dining, work


def _scout_category(city: str, prefs: dict, api_key: str, work: bool) -> list[dict]:
    """
    One category (dining OR work) for a city.
    Pass 1 → articles. Pass 2 → extract names → lookup links.
    """
    label = "work cafes" if work else "dining"

    # Pass 1: find listicle articles
    articles = search_articles(city, prefs, api_key, work=work)
    print(f"    Found {len(articles)} articles for {city} {label}")

    # Pass 2: fetch top articles and extract venue names
    all_names: list[str] = []
    for article in articles[:5]:  # fetch top 5 articles
        url = article["url"]
        print(f"    Fetching {url[:70]}...")
        html = fetch_page(url)
        if not html:
            continue
        names = extract_names_from_html(html)
        print(f"      Extracted {len(names)} names")
        all_names.extend(names)
        time.sleep(0.3)

    # Deduplicate names across articles
    seen: set[str] = set()
    unique_names: list[str] = []
    for n in all_names:
        key = n.lower().strip()
        if key not in seen:
            seen.add(key)
            unique_names.append(n)

    print(f"    {len(unique_names)} unique venue names — looking up links...")

    # Pass 2b: find each venue's website + reservation link
    venues: list[dict] = []
    for name in unique_names[:20]:  # cap at 20 to save API quota
        print(f"      → {name}")
        details = find_venue_links(name, city, api_key)
        details["city"] = city
        venues.append(details)

    return venues


# ---------------------------------------------------------------------------
# Output writers
# ---------------------------------------------------------------------------

def _venue_row(v: dict, i: int) -> str:
    name = v["name"]
    website = v.get("website")
    res_url = v.get("reservation_url")
    res_platform = v.get("reservation_platform", "Book")
    desc = (v.get("description") or "").replace("|", "-")[:100]

    name_cell = f"[{name}]({website})" if website else name
    book_cell = f"[{res_platform}]({res_url})" if res_url else "—"
    return f"| {i} | {name_cell} | {book_cell} | {desc} |"


def write_venues_md(trip: dict, city_dining: dict[str, list], city_work: dict[str, list]) -> Path:
    trip_id = trip["id"]
    out_dir = Path(__file__).parent / trip_id
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / "venues.md"
    dates = trip.get("dates", {})

    lines = [
        f"# Venues — {trip_id}",
        f"",
        f"**Cities:** {', '.join(trip['cities'])}",
        f"**Dates:** {dates.get('start')} → {dates.get('end')}",
        f"**Party size:** {trip.get('party_size', 2)}",
        f"**Generated:** {datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
        f"",
        f"---",
        f"",
    ]

    for city in trip["cities"]:
        lines += [f"## 🍽 {city} — Dining & Bars", ""]
        dining = city_dining.get(city, [])
        if dining:
            lines += ["| # | Venue | Reserve | Notes |", "|---|-------|---------|-------|"]
            for i, v in enumerate(dining, 1):
                lines.append(_venue_row(v, i))
        else:
            lines.append("_No venues found._")
        lines.append("")

        work = city_work.get(city, [])
        if work:
            lines += [f"### ☕ {city} — Work-Friendly Cafes", ""]
            lines += ["| # | Venue | Reserve / Book | Notes |", "|---|-------|----------------|-------|"]
            for i, v in enumerate(work, 1):
                lines.append(_venue_row(v, i))
            lines.append("")

    out_file.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n  → Wrote {out_file}")
    return out_file


def write_candidates_md(trip: dict, city_dining: dict[str, list], city_work: dict[str, list]) -> Path:
    trip_id = trip["id"]
    out_dir = Path(__file__).parent / trip_id
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / "candidates.md"
    lines = [
        f"# Top Candidates — {trip_id}",
        f"",
        f"Generated: {datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
        f"",
        f"---",
        f"",
    ]

    for city in trip["cities"]:
        dining = city_dining.get(city, [])
        lines += [f"## {city} — Top Dining & Bars", ""]
        for v in dining[:8]:
            name = v["name"]
            website = v.get("website")
            res_url = v.get("reservation_url")
            res_platform = v.get("reservation_platform", "Book")
            desc = (v.get("description") or "")[:150]
            lines.append(f"### {name}")
            if website:
                lines.append(f"- **Website:** [{website}]({website})")
            if res_url:
                lines.append(f"- **Reservation ({res_platform}):** [{res_url}]({res_url})")
            else:
                lines.append(f"- **Reservation:** _(not found — check Resy/OpenTable manually)_")
            lines.append(f"- **Notes:** {desc}")
            lines.append("")

        work = city_work.get(city, [])
        if work:
            lines += [f"## {city} — ☕ Work Cafes", ""]
            for v in work[:5]:
                name = v["name"]
                website = v.get("website")
                res_url = v.get("reservation_url")
                desc = (v.get("description") or "")[:150]
                lines.append(f"### {name}")
                if website:
                    lines.append(f"- **Website:** [{website}]({website})")
                if res_url:
                    lines.append(f"- **Book:** [{res_url}]({res_url})")
                lines.append(f"- **Notes:** {desc}")
                lines.append(f"- **WiFi/Outlets:** _(confirm on visit)_")
                lines.append("")

    out_file.write_text("\n".join(lines), encoding="utf-8")
    print(f"  → Wrote {out_file}")
    return out_file


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    api_key = os.environ.get("BRAVE_API_KEY")
    if not api_key:
        print("ERROR: BRAVE_API_KEY not set.")
        sys.exit(1)

    trips_data = json.loads(TRIPS_FILE.read_text())
    trips = trips_data.get("trips", [])

    filter_id = sys.argv[1] if len(sys.argv) > 1 else None
    if filter_id:
        trips = [t for t in trips if t["id"] == filter_id]
        if not trips:
            print(f"ERROR: No trip '{filter_id}'.")
            sys.exit(1)

    print(f"Travel Scout v2 (two-pass) — {len(trips)} trip(s)")

    for trip in trips:
        print(f"\n{'='*60}")
        print(f"Trip: {trip['id']}  |  {', '.join(trip['cities'])}  |  {trip['dates']['start']} → {trip['dates']['end']}")

        city_dining: dict[str, list] = {}
        city_work: dict[str, list] = {}

        for city in trip["cities"]:
            dining, work = scout_city(city, trip, api_key)
            city_dining[city] = dining
            city_work[city] = work
            print(f"\n  {city}: {len(dining)} dining venues, {len(work)} work cafes extracted")

        write_venues_md(trip, city_dining, city_work)
        write_candidates_md(trip, city_dining, city_work)
        print(f"\n✓ Done: {trip['id']}")

    print("\nAll trips processed.")
    print("Next: review candidates.md, then run travel-reservations.py.")


if __name__ == "__main__":
    main()
