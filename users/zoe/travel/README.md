# Travel Scout 🌍

Research and reservation system for Jake + Zoe's trips. Finds the best local spots (restaurants, bars, highlights) for any city, ranks them, and books Resy reservations automatically.

---

## How it works

1. **`travel-scout.py`** — searches Brave for top venues per city, scores + ranks them
2. **`travel-reservations.py`** — books Resy reservations for the top spots
3. **`travel-report.py`** — generates a dark-theme HTML report with everything

---

## Adding a new trip

Edit `trips.json` and add an entry:

```json
{
  "id": "tokyo-osaka-jun2026",
  "cities": ["Tokyo", "Osaka"],
  "dates": { "start": "2026-06-10", "end": "2026-06-18" },
  "party_size": 2,
  "preferences": {
    "categories": ["restaurants", "bars", "highlights"],
    "vibe": "upscale-casual, local favorites, not touristy",
    "meal_types": ["dinner", "drinks"],
    "budget": "mid-to-high",
    "avoid": ["tourist traps", "chain restaurants"]
  }
}
```

---

## Running the scripts

### Step 1: Scout venues

```bash
cd users/zoe/travel
BRAVE_API_KEY=your_key python3 travel-scout.py london-paris-mar2026
```

This writes:
- `london-paris-mar2026/venues.md` — all discovered venues with scores
- `london-paris-mar2026/candidates.md` — top 5 per city for manual review

### Step 2: Add Resy URLs (manual)

Review `candidates.md`. For any restaurant you want to book:
1. Go to [resy.com](https://resy.com) and search for the venue
2. Copy the venue URL (looks like `https://resy.com/cities/lon/venues/VENUE-NAME`)
3. Paste it into `candidates.md` on the venue's `Resy URL:` line

### Step 3: Book reservations

```bash
python3 travel-reservations.py london-paris-mar2026
```

This reads Resy URLs from venues.md/candidates.md and books for the trip's `party_size` at 7–9pm. Results go to `london-paris-mar2026/reservations.md`.

### Step 4: Generate report

```bash
python3 travel-report.py london-paris-mar2026
```

Opens a dark-theme HTML page at `london-paris-mar2026/report.html` with all venues + confirmed reservations highlighted.

---

## File structure

```
users/zoe/travel/
├── trips.json                    ← add new trips here
├── travel-scout.py
├── travel-reservations.py
├── travel-report.py
├── README.md
└── london-paris-mar2026/
    ├── venues.md                 ← all discovered venues
    ├── candidates.md             ← top picks + Resy URLs
    ├── reservations.md           ← booking results
    └── report.html               ← visual report
```

---

## Requirements

- `BRAVE_API_KEY` env var for scouting (Jake has this)
- `RESY_API_KEY` — stored in `users/zoe/.env` (already configured)
- Python 3.11+ (stdlib only + requests)

---

## Notes

- Resy covers London and Paris, but not every venue will be on Resy
- Bars and highlights typically need direct contact — reservations.md will list these separately
- Run the scout 2–4 weeks before the trip; book reservations 30 days out (many nice spots open 30 days in advance)
- For future trips: just add to `trips.json` and repeat the steps above
