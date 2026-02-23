#!/usr/bin/env python3
"""
travel-report.py — Generate a dark-theme HTML report for a trip.

Reads venues.md and reservations.md for each trip, produces report.html.

Usage:
    python3 travel-report.py [trip-id]
"""

import sys
import json
import re
import datetime
from pathlib import Path

TRIPS_FILE = Path(__file__).parent / "trips.json"
WORKSPACE = Path(__file__).parent.parent.parent.parent
DOCS_TRAVEL = WORKSPACE / "docs" / "travel"

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title}</title>
<style>
  :root {{
    --bg: #0f0f13;
    --surface: #1a1a23;
    --surface2: #22222e;
    --border: #2e2e3e;
    --text: #e0e0e8;
    --muted: #888899;
    --accent: #7c8cf8;
    --green: #4ade80;
    --red: #f87171;
    --yellow: #fbbf24;
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    background: var(--bg);
    color: var(--text);
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    font-size: 15px;
    line-height: 1.6;
    padding: 2rem 1rem;
  }}
  .container {{ max-width: 1100px; margin: 0 auto; }}
  h1 {{ font-size: 2rem; color: var(--accent); margin-bottom: 0.25rem; }}
  .meta {{ color: var(--muted); font-size: 0.9rem; margin-bottom: 2rem; }}
  .cols {{ display: grid; grid-template-columns: 1fr 1fr; gap: 2rem; }}
  @media (max-width: 700px) {{ .cols {{ grid-template-columns: 1fr; }} }}
  .city-section {{ background: var(--surface); border-radius: 12px; padding: 1.5rem;
                   border: 1px solid var(--border); }}
  .city-section h2 {{ font-size: 1.25rem; color: var(--accent); margin-bottom: 1rem;
                      padding-bottom: 0.5rem; border-bottom: 1px solid var(--border); }}
  .venue-card {{ background: var(--surface2); border-radius: 8px; padding: 1rem;
                 margin-bottom: 0.75rem; border: 1px solid var(--border);
                 position: relative; }}
  .venue-card.confirmed {{ border-color: var(--green); }}
  .venue-card.confirmed::before {{
    content: '✓ RESERVED';
    position: absolute; top: 0.75rem; right: 0.75rem;
    font-size: 0.7rem; font-weight: 700; color: var(--green);
    background: rgba(74,222,128,0.1); padding: 2px 6px; border-radius: 4px;
  }}
  .venue-name {{ font-weight: 600; font-size: 1rem; margin-bottom: 0.25rem; }}
  .venue-name a {{ color: var(--text); text-decoration: none; }}
  .venue-name a:hover {{ color: var(--accent); }}
  .venue-meta {{ color: var(--muted); font-size: 0.82rem; margin-bottom: 0.5rem; }}
  .venue-desc {{ font-size: 0.88rem; color: #aaabb8; line-height: 1.5; }}
  .venue-booking {{ margin-top: 0.5rem; font-size: 0.82rem; }}
  .booking-time {{ color: var(--green); font-weight: 600; }}
  .booking-conf {{ color: var(--muted); }}
  .no-booking {{ color: var(--yellow); }}
  .reservations-section {{ margin-top: 2rem; background: var(--surface);
                            border-radius: 12px; padding: 1.5rem;
                            border: 1px solid var(--border); }}
  .reservations-section h2 {{ font-size: 1.25rem; color: var(--green);
                               margin-bottom: 1rem; padding-bottom: 0.5rem;
                               border-bottom: 1px solid var(--border); }}
  .res-item {{ padding: 0.75rem; background: var(--surface2); border-radius: 8px;
               margin-bottom: 0.75rem; border-left: 3px solid var(--green); }}
  .res-item.failed {{ border-left-color: var(--red); }}
  .res-name {{ font-weight: 600; margin-bottom: 0.25rem; }}
  .res-detail {{ font-size: 0.85rem; color: var(--muted); }}
  .badge {{ display: inline-block; font-size: 0.7rem; font-weight: 700;
            padding: 2px 7px; border-radius: 4px; margin-right: 0.5rem; }}
  .badge-green {{ background: rgba(74,222,128,0.15); color: var(--green); }}
  .badge-red {{ background: rgba(248,113,113,0.15); color: var(--red); }}
  .badge-yellow {{ background: rgba(251,191,36,0.15); color: var(--yellow); }}
  .empty {{ color: var(--muted); font-style: italic; padding: 1rem 0; }}
  footer {{ margin-top: 3rem; text-align: center; color: var(--muted); font-size: 0.8rem; }}
</style>
</head>
<body>
<div class="container">
  <h1>✈️ {trip_id}</h1>
  <p class="meta">{cities} &nbsp;·&nbsp; {dates} &nbsp;·&nbsp; Party of {party_size} &nbsp;·&nbsp; Generated {generated}</p>

  <div class="cols">
    {city_sections}
  </div>

  {reservations_section}

  <footer>Built by Bot &nbsp;·&nbsp; travel-report.py</footer>
</div>
</body>
</html>"""


def parse_venues_md(venues_md: Path) -> dict[str, list[dict]]:
    """Parse venues.md into per-city lists."""
    if not venues_md.exists():
        return {}

    text = venues_md.read_text()
    city_venues: dict[str, list[dict]] = {}
    current_city = None

    for line in text.splitlines():
        if line.startswith("## ") and not line.startswith("### "):
            current_city = line[3:].strip()
            city_venues[current_city] = []
        elif current_city and line.startswith("| ") and not line.startswith("| #") and not line.startswith("|---"):
            parts = [p.strip() for p in line.strip("|").split("|")]
            if len(parts) >= 3:
                name_cell = parts[1]
                desc = parts[2]
                # Extract link if present
                m = re.search(r"\[([^\]]+)\]\(([^)]+)\)", name_cell)
                if m:
                    name, url = m.group(1), m.group(2)
                else:
                    name, url = name_cell, ""
                score = int(parts[3]) if len(parts) > 3 and parts[3].lstrip("-").isdigit() else 0
                city_venues[current_city].append({
                    "name": name, "url": url, "description": desc, "score": score,
                    "confirmed": False, "booking_time": None, "confirmation": None
                })

    return city_venues


def parse_reservations_md(reservations_md: Path) -> tuple[list[dict], list[dict]]:
    """Parse reservations.md into confirmed and failed lists."""
    if not reservations_md.exists():
        return [], []

    text = reservations_md.read_text()
    confirmed, failed = [], []
    current = None
    in_confirmed = False
    in_failed = False

    for line in text.splitlines():
        if "✅ Confirmed" in line:
            in_confirmed, in_failed = True, False
        elif "❌ Failed" in line:
            in_confirmed, in_failed = False, True
        elif line.startswith("### "):
            current = {"name": line[4:].strip(), "time": None, "confirmation": None,
                       "resy_url": None, "error": None}
            if in_confirmed:
                confirmed.append(current)
            elif in_failed:
                failed.append(current)
        elif current:
            if "**Time:**" in line:
                current["time"] = line.split("**Time:**", 1)[-1].strip()
            elif "**Confirmation:**" in line:
                current["confirmation"] = line.split("**Confirmation:**", 1)[-1].strip()
            elif "**Resy URL:**" in line:
                current["resy_url"] = line.split("**Resy URL:**", 1)[-1].strip()
            elif "**Error:**" in line:
                current["error"] = line.split("**Error:**", 1)[-1].strip()

    return confirmed, failed


def build_city_section(city: str, venues: list[dict], confirmed_names: set[str]) -> str:
    if not venues:
        return f"""<div class="city-section">
  <h2>📍 {city}</h2>
  <p class="empty">No venues found. Run travel-scout.py first.</p>
</div>"""

    cards = []
    for v in venues[:10]:
        is_confirmed = any(c.lower() in v["name"].lower() or v["name"].lower() in c.lower()
                           for c in confirmed_names)
        confirmed_class = " confirmed" if is_confirmed else ""
        name_html = f'<a href="{v["url"]}" target="_blank">{v["name"]}</a>' if v["url"] else v["name"]
        desc = v["description"][:120] + ("…" if len(v["description"]) > 120 else "")
        score_badge = f'<span class="badge badge-yellow">score {v["score"]}</span>' if v["score"] else ""
        cards.append(f"""<div class="venue-card{confirmed_class}">
  <div class="venue-name">{name_html}</div>
  <div class="venue-meta">{score_badge}</div>
  <div class="venue-desc">{desc}</div>
</div>""")

    return f"""<div class="city-section">
  <h2>📍 {city}</h2>
  {''.join(cards)}
</div>"""


def build_reservations_section(confirmed: list[dict], failed: list[dict]) -> str:
    if not confirmed and not failed:
        return """<div class="reservations-section">
  <h2>🗓 Reservations</h2>
  <p class="empty">No reservations yet. Run travel-reservations.py after adding Resy URLs to venues.md.</p>
</div>"""

    items = []
    for r in confirmed:
        time_str = r.get("time") or "Time TBD"
        conf_str = r.get("confirmation") or "N/A"
        items.append(f"""<div class="res-item">
  <div class="res-name">{r["name"]} <span class="badge badge-green">CONFIRMED</span></div>
  <div class="res-detail"><span class="booking-time">{time_str}</span> &nbsp;·&nbsp;
  <span class="booking-conf">Conf: {conf_str}</span></div>
</div>""")

    for r in failed:
        err = r.get("error") or "Could not book online"
        items.append(f"""<div class="res-item failed">
  <div class="res-name">{r["name"]} <span class="badge badge-red">NOT BOOKED</span></div>
  <div class="res-detail">{err} — book directly or call ahead</div>
</div>""")

    return f"""<div class="reservations-section">
  <h2>🗓 Reservations ({len(confirmed)} confirmed)</h2>
  {''.join(items)}
</div>"""


def generate_landing_page(trips: list[dict]):
    """Generate docs/travel/index.html listing all trips."""
    DOCS_TRAVEL.mkdir(parents=True, exist_ok=True)

    cards = []
    for trip in trips:
        trip_id = trip["id"]
        cities = ", ".join(trip["cities"])
        dates = trip.get("dates", {})
        start = dates.get("start", "")
        end = dates.get("end", "")
        party = trip.get("party_size", 2)
        pub_dir = DOCS_TRAVEL / trip_id
        has_report = (pub_dir / "index.html").exists()
        link = f"./{trip_id}/" if has_report else "#"
        status_badge = '<span class="badge badge-green">Report Ready</span>' if has_report else '<span class="badge badge-yellow">Pending</span>'
        cards.append(f"""<a class="trip-card" href="{link}">
  <div class="trip-header">
    <span class="trip-cities">✈️ {cities}</span>
    {status_badge}
  </div>
  <div class="trip-dates">{start} → {end}</div>
  <div class="trip-meta">Party of {party}</div>
  <div class="trip-id">{trip_id}</div>
</a>""")

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Travel — Zoe & Jake</title>
<style>
  :root {{
    --bg: #0f0f13; --surface: #1a1a23; --border: #2e2e3e;
    --text: #e0e0e8; --muted: #888899; --accent: #7c8cf8;
    --green: #4ade80; --yellow: #fbbf24;
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ background: var(--bg); color: var(--text);
         font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
         padding: 2rem 1rem; }}
  .container {{ max-width: 800px; margin: 0 auto; }}
  h1 {{ font-size: 2rem; color: var(--accent); margin-bottom: 0.25rem; }}
  .subtitle {{ color: var(--muted); margin-bottom: 2.5rem; font-size: 0.9rem; }}
  .nav {{ margin-bottom: 1.5rem; }}
  .nav a {{ color: var(--muted); text-decoration: none; font-size: 0.85rem; }}
  .nav a:hover {{ color: var(--accent); }}
  .grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 1rem; }}
  .trip-card {{ background: var(--surface); border: 1px solid var(--border); border-radius: 12px;
                padding: 1.25rem; text-decoration: none; color: var(--text);
                transition: border-color 0.15s; display: block; }}
  .trip-card:hover {{ border-color: var(--accent); }}
  .trip-header {{ display: flex; justify-content: space-between; align-items: center;
                  margin-bottom: 0.5rem; }}
  .trip-cities {{ font-weight: 600; font-size: 1.05rem; }}
  .trip-dates {{ color: var(--muted); font-size: 0.88rem; margin-bottom: 0.25rem; }}
  .trip-meta {{ color: var(--muted); font-size: 0.82rem; margin-bottom: 0.5rem; }}
  .trip-id {{ font-size: 0.75rem; color: #555566; font-family: monospace; }}
  .badge {{ font-size: 0.7rem; font-weight: 700; padding: 2px 7px; border-radius: 4px; }}
  .badge-green {{ background: rgba(74,222,128,0.15); color: var(--green); }}
  .badge-yellow {{ background: rgba(251,191,36,0.15); color: var(--yellow); }}
  footer {{ margin-top: 3rem; text-align: center; color: var(--muted); font-size: 0.8rem; }}
</style>
</head>
<body>
<div class="container">
  <div class="nav"><a href="../">← Events</a></div>
  <h1>✈️ Trips</h1>
  <p class="subtitle">Zoe & Jake · Generated {datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}</p>
  <div class="grid">
    {''.join(cards) if cards else '<p style="color:var(--muted)">No trips yet. Add one to trips.json.</p>'}
  </div>
  <footer>Built by Bot · travel-report.py</footer>
</div>
</body>
</html>"""

    out = DOCS_TRAVEL / "index.html"
    out.write_text(html, encoding="utf-8")
    print(f"  → Landing page: {out}")


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

        venues_md = trip_dir / "venues.md"
        reservations_md = trip_dir / "reservations.md"

        city_venues = parse_venues_md(venues_md)
        confirmed, failed = parse_reservations_md(reservations_md)
        confirmed_names = {r["name"] for r in confirmed}

        city_sections = []
        for city in trip["cities"]:
            venues = city_venues.get(city, [])
            city_sections.append(build_city_section(city, venues, confirmed_names))

        dates = trip.get("dates", {})
        html = HTML_TEMPLATE.format(
            title=f"Trip: {trip_id}",
            trip_id=trip_id,
            cities=", ".join(trip["cities"]),
            dates=f"{dates.get('start')} → {dates.get('end')}",
            party_size=trip.get("party_size", 2),
            generated=datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
            city_sections="\n".join(city_sections),
            reservations_section=build_reservations_section(confirmed, failed),
        )

        # Write local copy
        out_file = trip_dir / "report.html"
        out_file.write_text(html, encoding="utf-8")
        print(f"  → Wrote {out_file}")

        # Publish to GitHub Pages docs/travel/TRIP_ID/index.html
        pub_dir = DOCS_TRAVEL / trip_id
        pub_dir.mkdir(parents=True, exist_ok=True)
        pub_file = pub_dir / "index.html"
        pub_file.write_text(html, encoding="utf-8")
        print(f"  → Published {pub_file}")

    # Regenerate the travel landing page
    generate_landing_page(trips)
    print("\nAll reports generated.")
    print(f"Published to: https://jacoberrol.github.io/clawbot-workspace/travel/")


if __name__ == "__main__":
    main()
