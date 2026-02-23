#!/usr/bin/env python3
"""
travel-report.py — Generate a dark-theme HTML report for a trip.

Reads venues.json (preferred) or venues.md (fallback) for each trip,
produces report.html locally and publishes to docs/travel/ for GitHub Pages.

Usage:
    python3 travel-report.py [trip-id]
"""

import sys
import json
import re
import datetime
from pathlib import Path

TRIPS_FILE = Path(__file__).parent / "trips.json"
WORKSPACE  = Path(__file__).parent.parent.parent.parent   # repo root
DOCS_TRAVEL = WORKSPACE / "docs" / "travel"

# ---------------------------------------------------------------------------
# HTML template
# ---------------------------------------------------------------------------

CSS = """
  :root {
    --bg: #0f0f13; --surface: #1a1a23; --surface2: #22222e;
    --border: #2e2e3e; --text: #e0e0e8; --muted: #888899;
    --accent: #7c8cf8; --green: #4ade80; --red: #f87171;
    --yellow: #fbbf24; --purple: #c084fc; --orange: #fb923c;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    background: var(--bg); color: var(--text);
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    font-size: 15px; line-height: 1.6; padding: 2rem 1rem;
  }
  .container { max-width: 1200px; margin: 0 auto; }
  h1 { font-size: 2rem; color: var(--accent); margin-bottom: 0.25rem; }
  .meta { color: var(--muted); font-size: 0.9rem; margin-bottom: 2.5rem; }
  .nav { margin-bottom: 1rem; }
  .nav a { color: var(--muted); text-decoration: none; font-size: 0.85rem; }
  .nav a:hover { color: var(--accent); }

  /* City columns */
  .cities { display: grid; grid-template-columns: 1fr 1fr; gap: 2rem; margin-bottom: 2rem; }
  @media (max-width: 800px) { .cities { grid-template-columns: 1fr; } }

  .city-col { }
  .city-heading {
    font-size: 1.4rem; font-weight: 700; color: var(--accent);
    margin-bottom: 1.5rem; padding-bottom: 0.5rem;
    border-bottom: 2px solid var(--border);
  }

  /* Section headers (Bars / Restaurants / Cafes) */
  .section-heading {
    font-size: 0.8rem; font-weight: 700; letter-spacing: 0.1em;
    text-transform: uppercase; color: var(--muted);
    margin: 1.25rem 0 0.75rem;
  }
  .section-heading:first-of-type { margin-top: 0; }

  /* Venue cards */
  .venue-card {
    background: var(--surface); border-radius: 10px; padding: 1rem 1.1rem;
    margin-bottom: 0.65rem; border: 1px solid var(--border);
    position: relative; transition: border-color 0.15s;
  }
  .venue-card:hover { border-color: #44445a; }
  .venue-card.confirmed { border-color: var(--green); }
  .venue-card.confirmed::after {
    content: '✓ Reserved';
    position: absolute; top: 0.8rem; right: 0.8rem;
    font-size: 0.68rem; font-weight: 700; color: var(--green);
    background: rgba(74,222,128,0.1); padding: 2px 7px; border-radius: 4px;
    border: 1px solid rgba(74,222,128,0.25);
  }

  .venue-top { display: flex; align-items: flex-start; gap: 0.5rem; margin-bottom: 0.35rem; }
  .venue-name { font-weight: 600; font-size: 1rem; flex: 1; }
  .venue-name a { color: var(--text); text-decoration: none; }
  .venue-name a:hover { color: var(--accent); }

  .book-btn {
    flex-shrink: 0; font-size: 0.7rem; font-weight: 700;
    color: var(--green); background: rgba(74,222,128,0.1);
    padding: 3px 9px; border-radius: 5px; text-decoration: none;
    border: 1px solid rgba(74,222,128,0.3); white-space: nowrap;
  }
  .book-btn:hover { background: rgba(74,222,128,0.2); }

  /* Tags row */
  .tags { display: flex; flex-wrap: wrap; gap: 0.3rem; margin-bottom: 0.4rem; }
  .tag {
    font-size: 0.68rem; font-weight: 600; padding: 2px 7px;
    border-radius: 4px; letter-spacing: 0.02em;
  }
  .tag-neighbourhood { background: rgba(124,140,248,0.15); color: var(--accent); }
  .tag-cuisine       { background: rgba(251,146,60,0.15);  color: var(--orange); }
  .tag-rating        { background: rgba(250,204,21,0.15);  color: var(--yellow); }
  .tag-type          { background: rgba(192,132,252,0.12); color: var(--purple); }

  .venue-desc {
    font-size: 0.84rem; color: #9999aa; line-height: 1.5;
    display: -webkit-box; -webkit-line-clamp: 2;
    -webkit-box-orient: vertical; overflow: hidden;
  }

  /* Reservations panel */
  .reservations {
    background: var(--surface); border-radius: 12px; padding: 1.5rem;
    border: 1px solid var(--border); margin-top: 0.5rem;
  }
  .reservations h2 {
    font-size: 1.1rem; color: var(--green); margin-bottom: 1rem;
    padding-bottom: 0.5rem; border-bottom: 1px solid var(--border);
  }
  .res-item {
    padding: 0.75rem; background: var(--surface2); border-radius: 8px;
    margin-bottom: 0.6rem; border-left: 3px solid var(--green);
  }
  .res-item.failed { border-left-color: var(--red); }
  .res-name { font-weight: 600; margin-bottom: 0.2rem; }
  .res-detail { font-size: 0.82rem; color: var(--muted); }

  .badge {
    display: inline-block; font-size: 0.68rem; font-weight: 700;
    padding: 2px 7px; border-radius: 4px; margin-right: 0.4rem;
  }
  .badge-green  { background: rgba(74,222,128,0.15); color: var(--green); }
  .badge-red    { background: rgba(248,113,113,0.15); color: var(--red); }

  .empty { color: var(--muted); font-style: italic; padding: 0.5rem 0; font-size: 0.9rem; }
  footer { margin-top: 3rem; text-align: center; color: var(--muted); font-size: 0.78rem; }
"""


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_venues_json(trip_dir: Path) -> dict | None:
    """Load venues.json if it exists."""
    f = trip_dir / "venues.json"
    if f.exists():
        return json.loads(f.read_text(encoding="utf-8"))
    return None


def parse_venues_md(venues_md: Path) -> dict[str, dict[str, list]]:
    """
    Fallback: parse venues.md into {city: {dining: [...], work: [...]}}
    Handles both old and new table formats.
    """
    if not venues_md.exists():
        return {}

    text = venues_md.read_text()
    result: dict[str, dict] = {}
    current_city = None
    current_section = "dining"

    for line in text.splitlines():
        if line.startswith("## ") and not line.startswith("### "):
            raw = line[3:].strip()
            raw = re.sub(r'^[\U00010000-\U0010ffff\u2600-\u27BF\s]+', '', raw)
            raw = re.sub(r'\s*[—–-].*$', '', raw).strip()
            if raw:
                current_city = raw
                current_section = "dining"
                if current_city not in result:
                    result[current_city] = {"dining": [], "work": []}

        elif line.startswith("### ") and current_city:
            if "work" in line.lower() or "café" in line.lower() or "cafe" in line.lower() or "☕" in line:
                current_section = "work"
            else:
                current_section = "dining"

        elif current_city and line.startswith("| ") and not re.match(r'\|\s*#?\s*\|', line) and not line.startswith("|---"):
            parts = [p.strip() for p in line.strip("|").split("|")]
            if len(parts) < 2:
                continue
            name_cell = parts[1]
            m = re.search(r"\[([^\]]+)\]\(([^)]+)\)", name_cell)
            name, url = (m.group(1), m.group(2)) if m else (name_cell, "")
            if not name or name in ("#", "Venue", "Name / Source"):
                continue
            reservation_url = reservation_platform = ""
            description = ""
            if len(parts) > 2:
                col2 = parts[2]
                rm = re.search(r"\[([^\]]+)\]\(([^)]+)\)", col2)
                if rm:
                    reservation_platform, reservation_url = rm.group(1), rm.group(2)
                elif col2 not in ("—", "-", ""):
                    description = col2
            if len(parts) > 3 and parts[3] not in ("—", "-", ""):
                description = parts[3]

            result[current_city][current_section].append({
                "name": name, "website": url,
                "reservation_url": reservation_url,
                "reservation_platform": reservation_platform,
                "description": description,
                "neighbourhood": "", "cuisine": "", "type": "", "rating": "",
            })

    return result


def load_city_venues(trip: dict, trip_dir: Path) -> dict[str, dict[str, list]]:
    """Load venue data: prefer venues.json, fall back to venues.md."""
    jdata = load_venues_json(trip_dir)
    if jdata:
        result = {}
        for city in trip["cities"]:
            city_data = jdata.get("venues", {}).get(city, {})
            result[city] = {
                "dining": city_data.get("dining", []),
                "work": city_data.get("work", []),
            }
        return result
    # Fallback
    return parse_venues_md(trip_dir / "venues.md")


def parse_reservations_md(reservations_md: Path) -> tuple[list[dict], list[dict]]:
    if not reservations_md.exists():
        return [], []
    text = reservations_md.read_text()
    confirmed, failed = [], []
    current = None
    in_confirmed = in_failed = False
    for line in text.splitlines():
        if "✅ Confirmed" in line:
            in_confirmed, in_failed = True, False
        elif "❌ Failed" in line:
            in_confirmed, in_failed = False, True
        elif line.startswith("### "):
            current = {"name": line[4:].strip(), "time": None, "confirmation": None, "error": None}
            (confirmed if in_confirmed else failed if in_failed else []).append(current)
        elif current:
            if "**Time:**" in line:
                current["time"] = line.split("**Time:**", 1)[-1].strip()
            elif "**Confirmation:**" in line:
                current["confirmation"] = line.split("**Confirmation:**", 1)[-1].strip()
            elif "**Error:**" in line:
                current["error"] = line.split("**Error:**", 1)[-1].strip()
    return confirmed, failed


# ---------------------------------------------------------------------------
# HTML builders
# ---------------------------------------------------------------------------

def _tags_html(v: dict) -> str:
    tags = []
    if v.get("neighbourhood"):
        tags.append(f'<span class="tag tag-neighbourhood">📍 {v["neighbourhood"]}</span>')
    if v.get("cuisine"):
        tags.append(f'<span class="tag tag-cuisine">{v["cuisine"]}</span>')
    if v.get("rating"):
        tags.append(f'<span class="tag tag-rating">{v["rating"]}</span>')
    return f'<div class="tags">{"".join(tags)}</div>' if tags else ""


def _venue_card_html(v: dict, confirmed_names: set[str]) -> str:
    name = v["name"]
    website = v.get("website", "")
    res_url = v.get("reservation_url", "")
    res_platform = v.get("reservation_platform", "Book")
    desc_raw = re.sub(r'<[^>]+>', '', v.get("description") or "")
    desc = desc_raw[:160] + ("…" if len(desc_raw) > 160 else "")

    is_confirmed = any(c.lower() in name.lower() or name.lower() in c.lower()
                       for c in confirmed_names)
    confirmed_class = " confirmed" if is_confirmed else ""

    name_html = f'<a href="{website}" target="_blank">{name}</a>' if website else name
    book_html = f'<a class="book-btn" href="{res_url}" target="_blank">🗓 {res_platform}</a>' if res_url else ""

    return f"""<div class="venue-card{confirmed_class}">
  <div class="venue-top">
    <div class="venue-name">{name_html}</div>
    {book_html}
  </div>
  {_tags_html(v)}
  {f'<div class="venue-desc">{desc}</div>' if desc else ''}
</div>"""


def build_city_column(city: str, data: dict, confirmed_names: set[str]) -> str:
    dining = data.get("dining", [])
    work = data.get("work", [])

    restaurants = [v for v in dining if v.get("type") in ("restaurant", "") or v.get("type") == "restaurant"]
    bars = [v for v in dining if v.get("type") == "bar"]
    # If type isn't set, split heuristically: anything with bar/cocktail in cuisine goes to bars
    if not bars:
        bars = [v for v in restaurants if "bar" in (v.get("cuisine") or "").lower()]
        restaurants = [v for v in restaurants if v not in bars]

    sections = []

    if bars:
        cards = "".join(_venue_card_html(v, confirmed_names) for v in bars)
        sections.append(f'<div class="section-heading">🍸 Bars</div>{cards}')

    if restaurants:
        cards = "".join(_venue_card_html(v, confirmed_names) for v in restaurants)
        sections.append(f'<div class="section-heading">🍽 Restaurants</div>{cards}')

    if not bars and not restaurants:
        sections.append('<p class="empty">No dining venues found. Run travel-scout.py first.</p>')

    if work:
        cards = "".join(_venue_card_html(v, confirmed_names) for v in work)
        sections.append(f'<div class="section-heading">☕ Work Cafes</div>{cards}')

    return f"""<div class="city-col">
  <div class="city-heading">📍 {city}</div>
  {"".join(sections)}
</div>"""


def build_reservations_section(confirmed: list[dict], failed: list[dict]) -> str:
    if not confirmed and not failed:
        return """<div class="reservations">
  <h2>🗓 Reservations</h2>
  <p class="empty">No reservations yet. Add Resy URLs to venues and run travel-reservations.py.</p>
</div>"""

    items = []
    for r in confirmed:
        items.append(f"""<div class="res-item">
  <div class="res-name">{r["name"]} <span class="badge badge-green">CONFIRMED</span></div>
  <div class="res-detail">{r.get("time") or "Time TBD"} · Conf: {r.get("confirmation") or "N/A"}</div>
</div>""")
    for r in failed:
        items.append(f"""<div class="res-item failed">
  <div class="res-name">{r["name"]} <span class="badge badge-red">NOT BOOKED</span></div>
  <div class="res-detail">{r.get("error") or "Could not book online"} — book directly</div>
</div>""")

    return f"""<div class="reservations">
  <h2>🗓 Reservations ({len(confirmed)} confirmed)</h2>
  {"".join(items)}
</div>"""


def generate_landing_page(trips: list[dict]):
    """Generate docs/travel/index.html listing all trips."""
    DOCS_TRAVEL.mkdir(parents=True, exist_ok=True)
    cards = []
    for trip in trips:
        trip_id = trip["id"]
        cities = ", ".join(trip["cities"])
        dates = trip.get("dates", {})
        start, end = dates.get("start", ""), dates.get("end", "")
        party = trip.get("party_size", 2)
        has_report = (DOCS_TRAVEL / trip_id / "index.html").exists()
        link = f"./{trip_id}/" if has_report else "#"
        badge = ('<span class="badge badge-green">Ready</span>' if has_report
                 else '<span class="badge badge-yellow">Pending</span>')
        cards.append(f"""<a class="trip-card" href="{link}">
  <div class="trip-header"><span class="trip-cities">✈️ {cities}</span>{badge}</div>
  <div class="trip-dates">{start} → {end}</div>
  <div class="trip-meta">Party of {party} · {trip_id}</div>
</a>""")

    html = f"""<!DOCTYPE html>
<html lang="en"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Travel — Zoe & Jake</title>
<style>
  :root{{--bg:#0f0f13;--surface:#1a1a23;--border:#2e2e3e;--text:#e0e0e8;--muted:#888899;--accent:#7c8cf8;--green:#4ade80;--yellow:#fbbf24;}}
  *{{box-sizing:border-box;margin:0;padding:0;}}
  body{{background:var(--bg);color:var(--text);font-family:-apple-system,sans-serif;padding:2rem 1rem;}}
  .container{{max-width:800px;margin:0 auto;}}
  h1{{font-size:2rem;color:var(--accent);margin-bottom:.25rem;}}
  .sub{{color:var(--muted);margin-bottom:2rem;font-size:.9rem;}}
  .nav{{margin-bottom:1rem;}}.nav a{{color:var(--muted);text-decoration:none;font-size:.85rem;}}
  .nav a:hover{{color:var(--accent);}}
  .grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:1rem;}}
  .trip-card{{background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:1.25rem;text-decoration:none;color:var(--text);display:block;transition:border-color .15s;}}
  .trip-card:hover{{border-color:var(--accent);}}
  .trip-header{{display:flex;justify-content:space-between;align-items:center;margin-bottom:.5rem;}}
  .trip-cities{{font-weight:600;font-size:1.05rem;}}
  .trip-dates,.trip-meta{{color:var(--muted);font-size:.85rem;margin-top:.2rem;}}
  .badge{{font-size:.68rem;font-weight:700;padding:2px 7px;border-radius:4px;}}
  .badge-green{{background:rgba(74,222,128,.15);color:var(--green);}}
  .badge-yellow{{background:rgba(251,191,36,.15);color:var(--yellow);}}
  footer{{margin-top:3rem;text-align:center;color:var(--muted);font-size:.78rem;}}
</style></head>
<body><div class="container">
  <div class="nav"><a href="../">← Events</a></div>
  <h1>✈️ Trips</h1>
  <p class="sub">Zoe & Jake · {datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}</p>
  <div class="grid">{"".join(cards) if cards else '<p style="color:var(--muted)">No trips yet.</p>'}</div>
  <footer>Built by Bot · travel-report.py</footer>
</div></body></html>"""

    (DOCS_TRAVEL / "index.html").write_text(html, encoding="utf-8")
    print(f"  → Landing page: {DOCS_TRAVEL / 'index.html'}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    trips_data = json.loads(TRIPS_FILE.read_text())
    trips = trips_data.get("trips", [])

    filter_id = sys.argv[1] if len(sys.argv) > 1 else None
    if filter_id:
        trips = [t for t in trips if t["id"] == filter_id]

    print(f"Travel Report — {len(trips)} trip(s)")

    for trip in trips:
        trip_id = trip["id"]
        trip_dir = Path(__file__).parent / trip_id
        trip_dir.mkdir(parents=True, exist_ok=True)

        print(f"\nGenerating report for {trip_id}...")

        city_data = load_city_venues(trip, trip_dir)
        confirmed, failed = parse_reservations_md(trip_dir / "reservations.md")
        confirmed_names = {r["name"] for r in confirmed}

        # Build city columns
        city_cols = "\n".join(
            build_city_column(city, city_data.get(city, {}), confirmed_names)
            for city in trip["cities"]
        )
        reservations_html = build_reservations_section(confirmed, failed)

        dates = trip.get("dates", {})
        title = f"Trip: {trip_id}"
        generated = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title}</title>
<style>{CSS}</style>
</head>
<body>
<div class="container">
  <div class="nav"><a href="../">← All Trips</a></div>
  <h1>✈️ {trip_id}</h1>
  <p class="meta">{', '.join(trip['cities'])} &nbsp;·&nbsp; {dates.get('start')} → {dates.get('end')} &nbsp;·&nbsp; Party of {trip.get('party_size', 2)} &nbsp;·&nbsp; {generated}</p>
  <div class="cities">
    {city_cols}
  </div>
  {reservations_html}
  <footer>Built by Bot &nbsp;·&nbsp; travel-report.py</footer>
</div>
</body>
</html>"""

        # Write local copy
        local_file = trip_dir / "report.html"
        local_file.write_text(html, encoding="utf-8")
        print(f"  → Wrote {local_file}")

        # Publish to GitHub Pages
        pub_dir = DOCS_TRAVEL / trip_id
        pub_dir.mkdir(parents=True, exist_ok=True)
        (pub_dir / "index.html").write_text(html, encoding="utf-8")
        print(f"  → Published {pub_dir / 'index.html'}")

    generate_landing_page(trips)
    print(f"\nDone. https://jacoberrol.github.io/clawbot-workspace/travel/")


if __name__ == "__main__":
    main()
