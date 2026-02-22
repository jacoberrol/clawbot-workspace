#!/usr/bin/env python3
"""
Gastropub Reservation Monitor
Checks Resy for available slots at Jake's shortlisted spots.
Uses Resy's internal API directly.
"""

import json
import os
import sys
import urllib.request
import urllib.parse
import urllib.error
from datetime import datetime

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
STATE_FILE = os.path.join(SCRIPT_DIR, "reservation-state.json")

RESY_API_KEY = "VbWk7s3L4KiK5fzlO7JD3Q5EYolJI7n5"
RESY_HEADERS = {
    "Authorization": f'ResyAPI api_key="{RESY_API_KEY}"',
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Origin": "https://resy.com",
    "Referer": "https://resy.com/",
    "Content-Type": "application/json",
    "Accept": "application/json, text/plain, */*",
    "Cache-Control": "no-cache",
}

# London coordinates
LONDON_LAT = 51.5074
LONDON_LNG = -0.1278

RESTAURANTS = [
    {
        "name": "The Marksman",
        "area": "Shoreditch",
        "platform": "resy",
        "search_query": "Marksman Public House Shoreditch",
    },
    {
        "name": "The Royal Oak Marylebone",
        "area": "Marylebone",
        "platform": "resy",
        "search_query": "Royal Oak Marylebone",
    },
    {
        "name": "The Princess of Shoreditch",
        "area": "Shoreditch",
        "platform": "opentable",
        "opentable_url": "https://www.opentable.co.uk/the-princess-of-shoreditch",
        "opentable_rid": None,  # will try to find dynamically
    },
]

DATES = [
    "2026-02-28",
    "2026-03-01",
    "2026-03-02",
    "2026-03-04",
    "2026-03-06",
]

PARTY_SIZE = 2


def resy_request(method, path, params=None, body=None):
    """Make a request to Resy's API."""
    url = f"https://api.resy.com{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params)

    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(url, data=data, headers=RESY_HEADERS, method=method)

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        try:
            return json.loads(body)
        except Exception:
            return {"error": str(e), "body": body[:200]}
    except Exception as e:
        return {"error": str(e)}


def search_resy_venue(query):
    """Search Resy for a venue by name, return (venue_id, slug) or None."""
    result = resy_request(
        "POST",
        "/3/venuesearch/search",
        body={
            "availability": True,
            "page": 1,
            "per_page": 10,
            "types": ["venue"],
            "geo": {
                "latitude": LONDON_LAT,
                "longitude": LONDON_LNG,
                "radius": 10000,
            },
            "query": query,
            "slot_filter": {"day": DATES[0], "party_size": PARTY_SIZE},
        },
    )

    if "search" in result and "hits" in result.get("search", {}):
        hits = result["search"]["hits"]
        if hits:
            hit = hits[0]
            venue_id = hit.get("venue", {}).get("id", {}).get("resy") or hit.get("id")
            url_slug = hit.get("url_slug") or hit.get("slug")
            name = hit.get("name", "Unknown")
            return {"venue_id": venue_id, "url_slug": url_slug, "name": name, "raw": hit}
    return None


def get_resy_availability(venue_id, date):
    """Get available time slots for a venue on a given date."""
    result = resy_request(
        "GET",
        "/4/find",
        params={
            "lat": "0",
            "long": "0",
            "day": date,
            "party_size": str(PARTY_SIZE),
            "venue_id": str(venue_id),
        },
    )

    slots = []
    if "results" in result:
        for venue in result["results"].get("venues", []):
            for slot in venue.get("slots", []):
                time_str = slot.get("date", {}).get("start", "")
                if time_str:
                    # Extract just the time part
                    try:
                        t = datetime.fromisoformat(time_str.replace("Z", "+00:00"))
                        slots.append(t.strftime("%H:%M"))
                    except Exception:
                        slots.append(time_str[-8:-3])  # fallback slice
    return slots


def check_opentable_availability(restaurant, date):
    """
    Try to check OpenTable availability via their widget API.
    Returns list of available time strings.
    """
    # OpenTable is heavily JS-rendered; this is best-effort via their
    # widget loader which is lighter weight
    # We'll try to get the restaurant ID first via their suggest API
    try:
        query = urllib.parse.quote(restaurant["name"])
        url = f"https://www.opentable.co.uk/restaurant/profile/search?q={query}&lang=en-GB&covers={PARTY_SIZE}&dateTime={date}T19%3A00"
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
                "Accept": "application/json",
                "Referer": "https://www.opentable.co.uk/",
            },
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
            print(f"  [OpenTable debug] Response: {str(data)[:200]}")
    except Exception as e:
        print(f"  [OpenTable] Could not reach API: {e}")
    return []  # placeholder — OpenTable needs browser automation


def load_state():
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except Exception:
        return {"found": {}, "venue_ids": {}, "lastRun": None}


def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def main():
    state = load_state()
    new_findings = []

    print(f"\n🍺 Gastropub Reservation Check — {datetime.utcnow().isoformat()}")
    print(f"Checking {len(RESTAURANTS)} restaurants × {len(DATES)} dates...\n")

    for restaurant in RESTAURANTS:
        name = restaurant["name"]
        platform = restaurant["platform"]

        if platform == "resy":
            # Look up venue ID (cache it)
            if name not in state.get("venue_ids", {}):
                print(f"  🔍 Searching Resy for '{name}'...")
                venue_info = search_resy_venue(restaurant["search_query"])
                if venue_info:
                    print(f"     Found: {venue_info['name']} (ID: {venue_info['venue_id']}, slug: {venue_info['url_slug']})")
                    state.setdefault("venue_ids", {})[name] = venue_info
                else:
                    print(f"     ❌ Not found on Resy")
                    state.setdefault("venue_ids", {})[name] = None
                save_state(state)

            venue_info = state["venue_ids"].get(name)
            if not venue_info or not venue_info.get("venue_id"):
                print(f"  ⚠️  Skipping {name} — not found on Resy\n")
                continue

            venue_id = venue_info["venue_id"]
            print(f"\n  📍 {name} ({restaurant['area']}) — Resy ID: {venue_id}")

            for date in DATES:
                date_label = datetime.strptime(date, "%Y-%m-%d").strftime("%a %d %b")
                sys.stdout.write(f"     {date_label}... ")
                sys.stdout.flush()

                slots = get_resy_availability(venue_id, date)

                if slots:
                    key = f"{name}|resy|{date}"
                    existing = state.get("found", {}).get(key, [])
                    new_slots = [s for s in slots if s not in existing]

                    if new_slots:
                        new_findings.append({
                            "restaurant": name,
                            "area": restaurant["area"],
                            "platform": "resy",
                            "date": date,
                            "date_label": date_label,
                            "slots": slots,
                        })
                    state.setdefault("found", {})[key] = slots
                    print(f"✅ {len(slots)} slot(s): {', '.join(slots)}")
                else:
                    print("❌ None")

        elif platform == "opentable":
            print(f"\n  📍 {name} ({restaurant['area']}) — OpenTable (limited)")
            for date in DATES:
                date_label = datetime.strptime(date, "%Y-%m-%d").strftime("%a %d %b")
                sys.stdout.write(f"     {date_label}... ")
                sys.stdout.flush()
                slots = check_opentable_availability(restaurant, date)
                print(f"⚠️  OpenTable requires browser (manual check needed)")
                break  # Only need to say this once

    state["lastRun"] = datetime.utcnow().isoformat()
    save_state(state)

    print()
    if new_findings:
        print("🎉 NEW AVAILABILITY FOUND:\n")
        notify_parts = []
        for f in new_findings:
            print(f"  🍽️  {f['restaurant']} ({f['area']}) — {f['date_label']}")
            print(f"     Times: {', '.join(f['slots'])}")
            print()
            notify_parts.append(f"{f['restaurant']} on {f['date_label']} at {'/'.join(f['slots'][:3])}")
        print(f"NOTIFY:{'; '.join(notify_parts)}")
    else:
        print("No new availability found.")
        print("NOTIFY:none")


if __name__ == "__main__":
    main()
