#!/usr/bin/env python3
"""
HTML Generator — reads events/events-enriched.json and produces docs/index.html.
Displays genre tags and neighborhood for each event.
Falls back to events.md if enriched JSON not found.
"""

import json
import re
from datetime import datetime, date
from pathlib import Path
from zoneinfo import ZoneInfo

WORKSPACE     = Path(__file__).parent.parent
ENRICHED_FILE = WORKSPACE / "events/events-enriched.json"
EVENTS_FILE   = WORKSPACE / "events/events.md"
VENUES_FILE   = WORKSPACE / "events/venues.md"
OUTPUT_FILE   = WORKSPACE / "docs/index.html"
ET = ZoneInfo("America/New_York")

CSS = """
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600&family=Playfair+Display:wght@400;700&display=swap');

* { box-sizing: border-box; margin: 0; padding: 0; }

:root {
  --bg: #0d0d0d;
  --surface: #181818;
  --surface2: #222222;
  --border: #2a2a2a;
  --text: #e8e8e8;
  --muted: #888;
  --accent: #c8a96e;
  --accent2: #7eb8a4;
  --nyc: #c8a96e;
  --sf: #7eb8a4;
}

body {
  background: var(--bg);
  color: var(--text);
  font-family: 'Inter', sans-serif;
  font-size: 15px;
  line-height: 1.6;
  min-height: 100vh;
}

header {
  padding: 3rem 2rem 2rem;
  text-align: center;
  border-bottom: 1px solid var(--border);
}
header h1 {
  font-family: 'Playfair Display', serif;
  font-size: 2.8rem;
  font-weight: 700;
  letter-spacing: -0.5px;
}
header p.sub {
  color: var(--muted);
  margin-top: 0.4rem;
  font-size: 0.9rem;
  letter-spacing: 0.05em;
  text-transform: uppercase;
}
header p.updated {
  color: var(--muted);
  font-size: 0.8rem;
  margin-top: 0.5rem;
}

.cities {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 0;
  max-width: 1400px;
  margin: 0 auto;
}
@media (max-width: 768px) {
  .cities { grid-template-columns: 1fr; }
  header h1 { font-size: 2rem; }
}

.city-col {
  padding: 2rem;
  border-right: 1px solid var(--border);
}
.city-col:last-child { border-right: none; }

.city-col h2 {
  font-family: 'Playfair Display', serif;
  font-size: 1.5rem;
  margin-bottom: 1.5rem;
  padding-bottom: 0.75rem;
  border-bottom: 2px solid;
  display: flex;
  align-items: center;
  gap: 0.5rem;
}
.city-col.nyc h2 { border-color: var(--nyc); color: var(--nyc); }
.city-col.sf  h2 { border-color: var(--sf);  color: var(--sf);  }

.date-group { margin-bottom: 1.75rem; }

.date-label {
  font-size: 0.75rem;
  font-weight: 600;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  color: var(--muted);
  margin-bottom: 0.6rem;
}

.event-card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 0.85rem 1rem;
  margin-bottom: 0.6rem;
  transition: border-color 0.15s, background 0.15s;
}
.event-card:hover {
  border-color: #3a3a3a;
  background: var(--surface2);
}

.event-name {
  font-weight: 600;
  font-size: 0.95rem;
  color: var(--text);
  margin-bottom: 0.25rem;
}

.event-meta {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.4rem;
  margin-bottom: 0.45rem;
}

.event-venue {
  font-size: 0.82rem;
  color: var(--muted);
}

.badge {
  display: inline-block;
  font-size: 0.68rem;
  padding: 1px 7px;
  border-radius: 20px;
  font-weight: 500;
  letter-spacing: 0.02em;
  white-space: nowrap;
}

.badge-hood {
  background: #1e2a22;
  color: #7eb8a4;
  border: 1px solid #2a4035;
}

.badge-genre {
  background: #251e12;
  color: #c8a96e;
  border: 1px solid #3d2e0e;
}

.badge-theater {
  background: #1a1a2e;
  color: #8888cc;
  border: 1px solid #2a2a4a;
}

.event-link {
  display: inline-block;
  margin-top: 0.4rem;
  font-size: 0.75rem;
  color: var(--accent);
  text-decoration: none;
  border: 1px solid var(--accent);
  padding: 2px 10px;
  border-radius: 20px;
  opacity: 0.85;
  transition: opacity 0.15s;
}
.city-col.sf .event-link { color: var(--sf); border-color: var(--sf); }
.event-link:hover { opacity: 1; }

.empty {
  color: var(--muted);
  font-style: italic;
  font-size: 0.9rem;
  padding: 1rem 0;
}

.venues-section {
  max-width: 1400px;
  margin: 0 auto;
  padding: 2rem;
  border-top: 1px solid var(--border);
}
.venues-section h2 {
  font-family: 'Playfair Display', serif;
  font-size: 1.3rem;
  color: var(--muted);
  margin-bottom: 1.25rem;
}
.venues-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
  gap: 0.5rem;
}
.venue-tag {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 0.4rem 0.75rem;
  font-size: 0.8rem;
  color: var(--muted);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

footer {
  text-align: center;
  padding: 2rem;
  color: var(--muted);
  font-size: 0.8rem;
  border-top: 1px solid var(--border);
}

/* ── Mobile city nav ── */
.city-nav {
  display: none;
}
@media (max-width: 768px) {
  .city-nav {
    display: flex;
    position: sticky;
    top: 0;
    z-index: 100;
    background: var(--bg);
    border-bottom: 1px solid var(--border);
    padding: 0;
  }
  .city-nav a {
    flex: 1;
    text-align: center;
    padding: 0.85rem 1rem;
    text-decoration: none;
    font-size: 0.9rem;
    font-weight: 600;
    letter-spacing: 0.03em;
    border-bottom: 3px solid transparent;
    transition: border-color 0.15s, color 0.15s;
  }
  .city-nav a.nyc {
    color: var(--nyc);
  }
  .city-nav a.nyc:hover, .city-nav a.nyc:focus {
    border-bottom-color: var(--nyc);
  }
  .city-nav a.sf {
    color: var(--sf);
  }
  .city-nav a.sf:hover, .city-nav a.sf:focus {
    border-bottom-color: var(--sf);
  }
  /* Offset anchor scroll so the sticky nav doesn't cover the heading */
  .city-col {
    scroll-margin-top: 52px;
  }
}
"""


def h(text):
    """HTML-escape a string."""
    return (str(text)
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;"))


def load_enriched():
    """Load events-enriched.json → {city: [event_dict, ...]}"""
    if not ENRICHED_FILE.exists():
        return None
    data = json.loads(ENRICHED_FILE.read_text())
    result = {}
    today = date.today().isoformat()
    for city, events in data.get("cities", {}).items():
        result[city] = [e for e in events if e.get("date", "") >= today]
    return result


def load_events_md_fallback():
    """Fallback: parse events.md into the same shape as load_enriched."""
    text = EVENTS_FILE.read_text()
    result = {}
    current_city = None
    current_date = None
    for line in text.splitlines():
        if line.startswith("## "):
            city = line[3:].strip()
            if city in ("New York City", "San Francisco"):
                current_city = city
                result[current_city] = []
        elif line.startswith("### ") and current_city:
            current_date = line[4:].strip()
        elif line.startswith("- **") and current_city and current_date:
            m = re.match(r'- \*\*(.+?)\*\*\s*@\s*(.+?)\s*—\s*\[.+?\]\((.+?)\)', line)
            if m:
                result[current_city].append({
                    "name": m.group(1),
                    "venue": m.group(2),
                    "neighborhood": "",
                    "date": current_date,
                    "url": m.group(3),
                    "genres": [],
                    "is_theater": False,
                })
    return result


def load_venues_md():
    """Parse venues.md → {city: [name, ...]}"""
    text = VENUES_FILE.read_text()
    venues = {"New York City": [], "San Francisco": []}
    current_city = None
    for line in text.splitlines():
        if line.startswith("## "):
            current_city = line[3:].strip()
        elif line.startswith("- **") and current_city in venues:
            m = re.match(r'- \*\*(.+?)\*\*', line)
            if m:
                venues[current_city].append(m.group(1))
    return venues


def render_event_card(ev, css_class):
    name = h(ev["name"])
    venue = h(ev["venue"])
    url = ev["url"]
    neighborhood = ev.get("neighborhood", "")
    genres = ev.get("genres", [])
    is_theater = ev.get("is_theater", False)

    # Meta row: venue + neighborhood badge + genre badges
    meta_parts = [f'<span class="event-venue">{venue}</span>']
    if neighborhood:
        meta_parts.append(f'<span class="badge badge-hood">{h(neighborhood)}</span>')
    if is_theater:
        meta_parts.append('<span class="badge badge-theater">theater</span>')
    for genre in genres[:3]:
        meta_parts.append(f'<span class="badge badge-genre">{h(genre)}</span>')

    meta_html = "\n    ".join(meta_parts)

    return f'''<div class="event-card">
  <div class="event-name">{name}</div>
  <div class="event-meta">
    {meta_html}
  </div>
  <a class="event-link" href="{url}" target="_blank" rel="noopener">Info / Tickets ↗</a>
</div>'''


def render_city_column(events_list, css_class):
    if not events_list:
        return '<p class="empty">No upcoming events yet — check back soon.</p>'

    # Group by date
    groups = {}
    for ev in sorted(events_list, key=lambda e: e["date"]):
        d = ev["date"]
        groups.setdefault(d, []).append(ev)

    parts = []
    for d, evs in groups.items():
        try:
            label = datetime.fromisoformat(d).strftime("%b %-d, %Y")
        except Exception:
            label = d
        cards = "\n".join(render_event_card(ev, css_class) for ev in evs)
        parts.append(f'<div class="date-group">\n<div class="date-label">{label}</div>\n{cards}\n</div>')

    return "\n".join(parts)


def render_venue_tags(names):
    tags = "".join(f'<div class="venue-tag">{h(n)}</div>' for n in names)
    return f'<div class="venues-grid">{tags}</div>'


def generate():
    now_et = datetime.now(ET)
    updated = now_et.strftime("%B %-d, %Y at %-I:%M %p %Z")

    events = load_enriched()
    source = "enriched"
    if events is None:
        events = load_events_md_fallback()
        source = "events.md fallback"
    print(f"  Source: {source}")

    venues = load_venues_md()

    nyc_html = render_city_column(events.get("New York City", []), "nyc")
    sf_html  = render_city_column(events.get("San Francisco", []), "sf")
    nyc_venues_html = render_venue_tags(venues.get("New York City", []))
    sf_venues_html  = render_venue_tags(venues.get("San Francisco", []))

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Jake's Event Feed — NYC & SF</title>
  <style>{CSS}</style>
</head>
<body>

<header>
  <h1>Jake's Event Feed</h1>
  <p class="sub">New York City &amp; San Francisco</p>
  <p class="updated">Updated {updated}</p>
</header>

<nav class="city-nav">
  <a class="nyc" href="#nyc">🗽 New York City</a>
  <a class="sf"  href="#sf">🌉 San Francisco</a>
</nav>

<div class="cities">
  <div class="city-col nyc" id="nyc">
    <h2>🗽 New York City</h2>
    {nyc_html}
  </div>
  <div class="city-col sf" id="sf">
    <h2>🌉 San Francisco</h2>
    {sf_html}
  </div>
</div>

<div class="venues-section">
  <h2>Tracked Venues</h2>
  <div class="cities" style="border:none;gap:2rem;">
    <div>
      <div class="date-label" style="margin-bottom:0.75rem">New York City</div>
      {nyc_venues_html}
    </div>
    <div>
      <div class="date-label" style="margin-bottom:0.75rem">San Francisco</div>
      {sf_venues_html}
    </div>
  </div>
</div>

<footer>
  Curated by Bot 🤖 · Updated nightly · <a href="https://github.com/jacoberrol/clawbot-workspace" style="color:inherit;opacity:0.5">Source</a>
</footer>

</body>
</html>"""

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_FILE.write_text(html)
    print(f"✅ Generated docs/index.html ({len(html):,} bytes)")


if __name__ == "__main__":
    generate()
