#!/usr/bin/env python3
"""
travel-reservations.py — Book Resy reservations for top venues from the scout run.

Reads venues.md for each trip (with Resy URLs filled in), attempts bookings,
writes results to reservations.md.

Usage:
    python3 travel-reservations.py [trip-id]

Requires:
    RESY_API_KEY environment variable (or set in users/zoe/.env)

IMPORTANT: Fill in Resy URLs in candidates.md / venues.md before running this script.
The scout script finds sources and articles; you need to look up the actual Resy slugs.
Resy venue URLs look like: https://resy.com/cities/lon/venues/VENUE-SLUG
"""

import os
import sys
import json
import re
import time
import datetime
import urllib.request
import urllib.parse
import urllib.error
from pathlib import Path

WORKSPACE = Path(__file__).parent.parent.parent
TRIPS_FILE = Path(__file__).parent / "trips.json"
RESY_API = "https://api.resy.com"


def load_env(env_file: Path):
    """Load key=value pairs from a .env file into os.environ."""
    if not env_file.exists():
        return
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, val = line.partition("=")
            os.environ.setdefault(key.strip(), val.strip())


def resy_request(path: str, api_key: str, params: dict = None, method: str = "GET", body: dict = None) -> dict:
    """Make a Resy API request."""
    url = f"{RESY_API}{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params)

    data = json.dumps(body).encode("utf-8") if body else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", f"ResyAPI api_key=\"{api_key}\"")
    req.add_header("Content-Type", "application/json")
    req.add_header("Accept", "application/json")
    req.add_header("X-Origin", "https://resy.com")
    req.add_header("User-Agent", "Mozilla/5.0 (compatible; travel-scout/1.0)")

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        return {"error": f"HTTP {e.code}", "body": body}
    except Exception as e:
        return {"error": str(e)}


def slug_from_url(resy_url: str) -> str | None:
    """Extract venue slug from a Resy URL."""
    # https://resy.com/cities/lon/venues/SLUG or /cities/nyc/SLUG
    m = re.search(r"/venues/([^/?#]+)", resy_url)
    if m:
        return m.group(1)
    m = re.search(r"resy\.com/cities/[^/]+/([^/?#]+)", resy_url)
    return m.group(1) if m else None


def city_code_for(city: str) -> str:
    """Map city name to Resy city code."""
    mapping = {
        "london": "lon",
        "paris": "par",
        "new york": "nyc",
        "new york city": "nyc",
        "los angeles": "la",
        "chicago": "chi",
        "miami": "mia",
        "san francisco": "sf",
        "boston": "bos",
        "washington": "dc",
    }
    return mapping.get(city.lower(), city.lower()[:3])


def find_venue_id(slug: str, city_code: str, api_key: str) -> int | None:
    """Look up Resy venue_id from slug."""
    result = resy_request("/3/venue", api_key, params={"url_slug": slug, "location": city_code})
    if "error" in result:
        return None
    return result.get("id", {}).get("resy") if isinstance(result.get("id"), dict) else result.get("id")


def find_available_slot(venue_id: int, date: str, party_size: int, api_key: str) -> dict | None:
    """Find an available slot, preferring 7-9pm."""
    result = resy_request("/4/find", api_key, params={
        "lat": 0,
        "long": 0,
        "day": date,
        "party_size": party_size,
        "venue_id": venue_id,
    })

    if "error" in result or not result.get("results"):
        return None

    venues = result["results"].get("venues", [])
    if not venues:
        return None

    slots = venues[0].get("slots", [])
    if not slots:
        return None

    # Prefer 7pm-9pm window
    preferred = []
    fallback = []
    for slot in slots:
        start = slot.get("date", {}).get("start", "")
        hour = int(start[11:13]) if len(start) >= 13 else 0
        if 19 <= hour <= 21:
            preferred.append(slot)
        else:
            fallback.append(slot)

    return (preferred or fallback)[0] if (preferred or fallback) else None


def book_slot(slot: dict, party_size: int, api_key: str) -> dict:
    """Attempt to book a reservation slot."""
    config_id = slot.get("config", {}).get("id")
    token = slot.get("config", {}).get("token")
    date = slot.get("date", {}).get("start", "")[:10]

    if not config_id or not token:
        return {"ok": False, "error": "Missing config_id or token in slot"}

    # Step 1: Get booking token
    details = resy_request("/3/details", api_key, params={
        "config_id": config_id,
        "day": date,
        "party_size": party_size,
    })

    if "error" in details:
        return {"ok": False, "error": details["error"]}

    book_token = details.get("book_token", {}).get("value")
    if not book_token:
        return {"ok": False, "error": "No book_token returned"}

    # Step 2: Book
    result = resy_request("/3/book", api_key, method="POST", body={
        "book_token": book_token,
        "struct_payment_method": json.dumps({"id": 0}),
        "source_id": "resy.com-venue-details",
    })

    if "error" in result:
        return {"ok": False, "error": result["error"]}

    return {
        "ok": True,
        "reservation_id": result.get("resy_token"),
        "confirmation": result.get("reservation_id"),
        "time": slot.get("date", {}).get("start", ""),
    }


def parse_resy_urls_from_md(venues_md: Path) -> list[dict]:
    """Pull venues with Resy URLs from venues.md or candidates.md."""
    if not venues_md.exists():
        return []

    venues = []
    text = venues_md.read_text()
    # Look for lines with resy.com links
    for line in text.splitlines():
        resy_match = re.search(r"https://resy\.com[^\s\)]+", line)
        if resy_match:
            url = resy_match.group(0)
            # Try to get venue name from markdown link or surrounding context
            name_match = re.search(r"\[([^\]]+)\]", line)
            name = name_match.group(1) if name_match else url
            city_match = re.search(r"/cities/([^/]+)/", url)
            city_code = city_match.group(1) if city_match else "unknown"
            venues.append({"name": name, "resy_url": url, "city_code": city_code})

    return venues


def write_reservations_md(trip: dict, bookings: list[dict]) -> Path:
    """Write reservation results to reservations.md."""
    trip_id = trip["id"]
    out_dir = Path(__file__).parent / trip_id
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / "reservations.md"

    confirmed = [b for b in bookings if b.get("ok")]
    failed = [b for b in bookings if not b.get("ok")]

    lines = [
        f"# Reservations — {trip_id}",
        f"",
        f"**Generated:** {datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}",
        f"**Confirmed:** {len(confirmed)} / {len(bookings)}",
        f"",
        f"---",
        f"",
        f"## ✅ Confirmed Reservations",
        f"",
    ]

    if confirmed:
        for b in confirmed:
            lines.append(f"### {b['name']}")
            lines.append(f"- **Time:** {b.get('time', 'N/A')}")
            lines.append(f"- **Confirmation:** {b.get('confirmation', 'N/A')}")
            lines.append(f"- **Resy token:** {b.get('reservation_id', 'N/A')}")
            lines.append(f"- **Resy URL:** {b.get('resy_url', '')}")
            lines.append("")
    else:
        lines.append("_No confirmed reservations._")
        lines.append("")

    lines += [
        f"## ❌ Failed / Not Bookable Online",
        f"",
    ]

    if failed:
        for b in failed:
            lines.append(f"### {b['name']}")
            lines.append(f"- **Error:** {b.get('error', 'Unknown')}")
            lines.append(f"- **Resy URL:** {b.get('resy_url', 'N/A')}")
            lines.append(f"- **Action:** Call or book directly via website")
            lines.append("")
    else:
        lines.append("_All bookings succeeded._")
        lines.append("")

    out_file.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n→ Wrote {out_file}")
    return out_file


def main():
    # Load .env if present
    env_file = Path(__file__).parent.parent / ".env"
    load_env(env_file)

    api_key = os.environ.get("RESY_API_KEY")
    if not api_key:
        print("ERROR: RESY_API_KEY not set. Add it to users/zoe/.env")
        sys.exit(1)

    trips_data = json.loads(TRIPS_FILE.read_text())
    trips = trips_data.get("trips", [])

    filter_id = sys.argv[1] if len(sys.argv) > 1 else None
    if filter_id:
        trips = [t for t in trips if t["id"] == filter_id]
        if not trips:
            print(f"ERROR: No trip with id '{filter_id}' found.")
            sys.exit(1)

    print(f"Travel Reservations — {len(trips)} trip(s)")

    for trip in trips:
        trip_id = trip["id"]
        trip_dir = Path(__file__).parent / trip_id
        party_size = trip.get("party_size", 2)
        start_date = trip["dates"]["start"]

        print(f"\n{'='*60}")
        print(f"Trip: {trip_id} | {start_date} | Party of {party_size}")

        # Look for Resy URLs in venues.md or candidates.md
        venues_md = trip_dir / "venues.md"
        candidates_md = trip_dir / "candidates.md"

        all_venues = []
        for md_file in [venues_md, candidates_md]:
            all_venues.extend(parse_resy_urls_from_md(md_file))

        if not all_venues:
            print(f"\n  ⚠ No Resy URLs found in venues.md or candidates.md for {trip_id}.")
            print("  Steps:")
            print("  1. Run travel-scout.py first to populate candidates.md")
            print("  2. Find Resy URLs for the venues (resy.com → search venue name)")
            print("  3. Add the URLs to candidates.md or venues.md")
            print("  4. Re-run this script")
            bookings = []
        else:
            print(f"\n  Found {len(all_venues)} venue(s) with Resy URLs")
            bookings = []

            for venue in all_venues:
                name = venue["name"]
                resy_url = venue["resy_url"]
                city_code = venue["city_code"]
                print(f"\n  Booking: {name}")
                print(f"    URL: {resy_url}")

                slug = slug_from_url(resy_url)
                if not slug:
                    print("    ✗ Could not extract slug from URL")
                    bookings.append({"name": name, "resy_url": resy_url, "ok": False, "error": "Invalid Resy URL"})
                    continue

                venue_id = find_venue_id(slug, city_code, api_key)
                if not venue_id:
                    print("    ✗ Venue not found on Resy")
                    bookings.append({"name": name, "resy_url": resy_url, "ok": False, "error": "Venue not found on Resy"})
                    continue

                slot = find_available_slot(venue_id, start_date, party_size, api_key)
                if not slot:
                    print(f"    ✗ No availability on {start_date}")
                    bookings.append({"name": name, "resy_url": resy_url, "ok": False,
                                     "error": f"No availability on {start_date}"})
                    continue

                slot_time = slot.get("date", {}).get("start", "")
                print(f"    → Available slot: {slot_time}")
                result = book_slot(slot, party_size, api_key)
                result["name"] = name
                result["resy_url"] = resy_url

                if result["ok"]:
                    print(f"    ✓ Booked! Confirmation: {result.get('confirmation')}")
                else:
                    print(f"    ✗ Booking failed: {result.get('error')}")

                bookings.append(result)
                time.sleep(1)  # Rate limit

        write_reservations_md(trip, bookings)
        print(f"\n✓ Done: {trip_id}")

    print("\nAll trips processed. Check reservations.md for each trip.")
    print("Next: run travel-report.py to generate the HTML report.")


if __name__ == "__main__":
    main()
