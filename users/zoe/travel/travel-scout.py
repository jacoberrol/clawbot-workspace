#!/usr/bin/env python3
"""
travel-scout.py — Discover top restaurants, bars, and highlights for upcoming trips.
Reads trips.json, uses Brave Search to find venues, ranks them, writes results.

Usage:
    python3 travel-scout.py [trip-id]
    
    Without trip-id: processes all trips in trips.json
    With trip-id: processes only that trip (e.g. "london-paris-mar2026")

Requires:
    BRAVE_API_KEY environment variable
"""

import os
import sys
import json
import time
import datetime
import urllib.request
import urllib.parse
import urllib.error
from pathlib import Path

WORKSPACE = Path(__file__).parent.parent.parent
TRIPS_FILE = Path(__file__).parent / "trips.json"
BRAVE_API_URL = "https://api.search.brave.com/res/v1/web/search"

SEARCH_QUERIES = [
    "{city} best local restaurants 2025 2026 not touristy",
    "{city} best bars cocktail bars locals favorite",
    "{city} hidden gems restaurants {vibe}",
    "{city} best dinner spots upscale casual",
    "{city} neighborhoods food scene must try",
    "{city} city highlights must see not tourist trap",
]


def brave_search(query: str, api_key: str, count: int = 5) -> list[dict]:
    """Run a Brave Search query and return results."""
    params = urllib.parse.urlencode({
        "q": query,
        "count": count,
        "search_lang": "en",
        "result_filter": "web",
    })
    url = f"{BRAVE_API_URL}?{params}"
    req = urllib.request.Request(url, headers={
        "Accept": "application/json",
        "Accept-Encoding": "gzip",
        "X-Subscription-Token": api_key,
    })
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data.get("web", {}).get("results", [])
    except Exception as e:
        print(f"  [warn] Search failed for '{query}': {e}")
        return []


def score_result(result: dict, preferences: dict) -> int:
    """Score a search result by relevance signals."""
    score = 0
    title = (result.get("title") or "").lower()
    desc = (result.get("description") or "").lower()
    url = (result.get("url") or "").lower()
    text = title + " " + desc

    # Positive signals
    good_words = ["best", "top", "local", "favorite", "hidden", "gem", "award",
                  "michelin", "critically acclaimed", "neighborhood", "authentic"]
    for w in good_words:
        if w in text:
            score += 1

    vibe_words = preferences.get("vibe", "").lower().split(",")
    for v in vibe_words:
        v = v.strip()
        if v and v in text:
            score += 2

    # Penalize tourist traps
    avoid_words = preferences.get("avoid", [])
    for w in avoid_words:
        if w.lower() in text:
            score -= 3

    # Trust quality sources
    trusted_domains = ["eater.com", "theguardian.com", "nytimes.com", "timeout.com",
                       "infatuation.com", "telegraph.co.uk", "independent.co.uk",
                       "tripadvisor.com", "yelp.com", "zagat.com", "michelin"]
    for domain in trusted_domains:
        if domain in url:
            score += 3

    # Recent content bonus
    published = result.get("page_age") or result.get("age") or ""
    if "2025" in published or "2026" in published:
        score += 2

    return score


def extract_venues_from_results(results: list[dict], city: str) -> list[dict]:
    """Parse search results into venue candidates."""
    seen_urls = set()
    venues = []
    for r in results:
        url = r.get("url", "")
        if url in seen_urls:
            continue
        seen_urls.add(url)
        title = r.get("title", "").strip()
        desc = r.get("description", "").strip()
        if not title or not desc:
            continue
        venues.append({
            "title": title,
            "url": url,
            "description": desc,
            "city": city,
            "score": r.get("_score", 0),
        })
    return venues


def scout_city(city: str, trip: dict, api_key: str) -> list[dict]:
    """Run all search queries for a city and return ranked venues."""
    print(f"\n  Scouting {city}...")
    prefs = trip.get("preferences", {})
    vibe = prefs.get("vibe", "upscale-casual local")
    all_results = []

    for q_template in SEARCH_QUERIES:
        query = q_template.format(city=city, vibe=vibe)
        print(f"    → {query}")
        results = brave_search(query, api_key, count=5)
        for r in results:
            r["_score"] = score_result(r, prefs)
        all_results.extend(results)
        time.sleep(0.5)  # Rate limit

    venues = extract_venues_from_results(all_results, city)
    venues.sort(key=lambda v: v["score"], reverse=True)
    return venues


def write_venues_md(trip: dict, city_venues: dict[str, list]) -> Path:
    """Write venues.md for this trip."""
    trip_id = trip["id"]
    out_dir = Path(__file__).parent / trip_id
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / "venues.md"

    dates = trip.get("dates", {})
    lines = [
        f"# Venues — {trip_id}",
        f"",
        f"**Cities:** {', '.join(trip['cities'])}  ",
        f"**Dates:** {dates.get('start')} → {dates.get('end')}  ",
        f"**Party size:** {trip.get('party_size', 2)}  ",
        f"**Generated:** {datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}",
        f"",
        f"---",
        f"",
    ]

    for city in trip["cities"]:
        venues = city_venues.get(city, [])
        lines.append(f"## {city}")
        lines.append(f"")
        if not venues:
            lines.append("_No results found._")
            lines.append("")
            continue

        lines.append("| # | Name / Source | Description | Score |")
        lines.append("|---|---------------|-------------|-------|")
        for i, v in enumerate(venues[:15], 1):
            title = v["title"].replace("|", "-")[:60]
            desc = v["description"].replace("|", "-")[:80]
            url = v["url"]
            lines.append(f"| {i} | [{title}]({url}) | {desc} | {v['score']} |")
        lines.append("")

    out_file.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n  → Wrote {out_file}")
    return out_file


def write_candidates_md(trip: dict, city_venues: dict[str, list]) -> Path:
    """Write top candidates for reservation consideration."""
    trip_id = trip["id"]
    out_dir = Path(__file__).parent / trip_id
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / "candidates.md"

    lines = [
        f"# Top Candidates — {trip_id}",
        f"",
        f"These are the highest-scoring venues from the scout run.",
        f"Review and update with: actual restaurant name, Resy URL, and type.",
        f"",
        f"Generated: {datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}",
        f"",
        f"---",
        f"",
    ]

    for city in trip["cities"]:
        venues = city_venues.get(city, [])
        lines.append(f"## {city} — Top 5")
        lines.append("")
        for v in venues[:5]:
            lines.append(f"- **[{v['title'][:70]}]({v['url']})**")
            lines.append(f"  {v['description'][:120]}")
            lines.append(f"  Score: {v['score']}")
            lines.append(f"  Resy URL: _(fill in if available)_")
            lines.append(f"  Type: _(restaurant / bar / highlight)_")
            lines.append("")

    out_file.write_text("\n".join(lines), encoding="utf-8")
    print(f"  → Wrote {out_file}")
    return out_file


def main():
    api_key = os.environ.get("BRAVE_API_KEY")
    if not api_key:
        print("ERROR: BRAVE_API_KEY environment variable not set.")
        sys.exit(1)

    trips_data = json.loads(TRIPS_FILE.read_text())
    trips = trips_data.get("trips", [])

    filter_id = sys.argv[1] if len(sys.argv) > 1 else None
    if filter_id:
        trips = [t for t in trips if t["id"] == filter_id]
        if not trips:
            print(f"ERROR: No trip with id '{filter_id}' found.")
            sys.exit(1)

    print(f"Travel Scout — {len(trips)} trip(s) to process")

    for trip in trips:
        print(f"\n{'='*60}")
        print(f"Trip: {trip['id']}")
        print(f"Cities: {', '.join(trip['cities'])}")
        print(f"Dates: {trip['dates']['start']} → {trip['dates']['end']}")

        city_venues = {}
        for city in trip["cities"]:
            venues = scout_city(city, trip, api_key)
            city_venues[city] = venues
            print(f"  Found {len(venues)} results for {city}")

        write_venues_md(trip, city_venues)
        write_candidates_md(trip, city_venues)
        print(f"\n✓ Done: {trip['id']}")

    print("\n\nAll trips processed. Review candidates.md for each trip.")
    print("Next step: run travel-reservations.py to book top spots.")


if __name__ == "__main__":
    main()
