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

# ---------------------------------------------------------------------------
# Enrichment data: neighborhoods, cuisines, venue types, ratings
# ---------------------------------------------------------------------------

LONDON_NEIGHBOURHOODS = [
    "Shoreditch", "Soho", "Mayfair", "Notting Hill", "Brixton", "Hackney",
    "Covent Garden", "Hoxton", "Dalston", "Islington", "Borough", "Chelsea",
    "Bermondsey", "Peckham", "Bethnal Green", "King's Cross", "Fitzrovia",
    "Marylebone", "Clerkenwell", "Vauxhall", "Canary Wharf", "Whitechapel",
    "Spitalfields", "Aldgate", "Holborn", "Bloomsbury", "Pimlico", "Battersea",
    "Clapham", "Balham", "Tooting", "Waterloo", "Southwark", "London Bridge",
    "Liverpool Street", "Angel", "Camden", "Primrose Hill", "Stoke Newington",
]

PARIS_NEIGHBOURHOODS = [
    "Le Marais", "Montmartre", "Saint-Germain", "Pigalle", "Bastille",
    "Belleville", "Oberkampf", "Canal Saint-Martin", "République",
    "Châtelet", "Latin Quarter", "Quartier Latin", "Palais Royal",
    "Batignolles", "South Pigalle", "SoPi", "Opéra", "Grands Boulevards",
    "Nation", "Ménilmontant", "Butte aux Cailles", "Montparnasse",
    "Saint-Paul", "Abbesses", "Blanche", "Concorde", "Trocadéro",
    "Sciences Po", "Rue de Rivoli", "Place de la Bastille", "Île de la Cité",
    "Beaubourg", "Temple", "Réaumur", "Arts et Métiers",
]

SF_NEIGHBOURHOODS = [
    "Mission", "Castro", "Hayes Valley", "SoMa", "North Beach", "Nob Hill",
    "Tenderloin", "Lower Haight", "Upper Haight", "Haight-Ashbury", "Noe Valley",
    "Potrero Hill", "Dogpatch", "Bernal Heights", "Excelsior", "Outer Sunset",
    "Inner Sunset", "Richmond", "Inner Richmond", "Outer Richmond", "Marina",
    "Cow Hollow", "Pac Heights", "Pacific Heights", "Russian Hill", "Telegraph Hill",
    "Chinatown", "Financial District", "FiDi", "Union Square", "Civic Center",
    "Japantown", "Western Addition", "Fillmore", "Glen Park", "Bayview",
    "Embarcadero", "Ferry Building", "Fisherman's Wharf",
]

# Used to infer city from venue name lookup (for neighbourhood extraction)
CITY_NEIGHBOURHOODS = {
    "london": LONDON_NEIGHBOURHOODS,
    "paris": PARIS_NEIGHBOURHOODS,
    "san francisco": SF_NEIGHBOURHOODS,
}

CUISINE_KEYWORDS = {
    # Bar types
    "cocktail bar": "Cocktail Bar", "wine bar": "Wine Bar", "champagne bar": "Champagne Bar",
    "whisky bar": "Whisky Bar", "natural wine": "Natural Wine Bar", "sake bar": "Sake Bar",
    "beer bar": "Beer Bar", "craft beer": "Craft Beer", "pub": "Pub",
    # Restaurant cuisines
    "french": "French", "italian": "Italian", "japanese": "Japanese",
    "chinese": "Chinese", "mexican": "Mexican", "spanish": "Spanish",
    "greek": "Greek", "thai": "Thai", "indian": "Indian", "korean": "Korean",
    "vietnamese": "Vietnamese", "peruvian": "Peruvian", "middle eastern": "Middle Eastern",
    "mediterranean": "Mediterranean", "british": "British", "american": "American",
    "seafood": "Seafood", "steakhouse": "Steakhouse", "sushi": "Sushi",
    "ramen": "Ramen", "pizza": "Pizza", "taqueria": "Mexican",
    "bistro": "Bistro", "brasserie": "Brasserie", "gastropub": "Gastropub",
    "farm-to-table": "Farm-to-Table", "seasonal": "Seasonal",
    "small plates": "Small Plates", "tapas": "Tapas",
    # Cafe types
    "specialty coffee": "Specialty Coffee", "third wave": "Specialty Coffee",
    "espresso bar": "Espresso Bar", "brunch": "Brunch Café",
    "bakery": "Bakery", "patisserie": "Patisserie",
}

VENUE_TYPE_SIGNALS = {
    "bar": ["cocktail bar", "wine bar", "bar ", " bar", "drinks", "cocktails",
            "whisky", "speakeasy", "pub ", " pub", "tavern", "taproom"],
    "restaurant": ["restaurant", "dining", "cuisine", "bistro", "brasserie",
                   "eatery", "kitchen", "grill", "tasting menu", "michelin",
                   "reservations required", "dinner", "lunch menu"],
    "cafe": ["coffee", "café", "cafe", "espresso", "latte", "laptop", "wifi",
             "co-working", "coworking", "pastry", "bakery", "brunch spot"],
}


# --- Search query templates (Pass 1) ---
DINING_QUERIES = [
    "{city} best local restaurants 2025 2026 not touristy",
    "{city} best cocktail bars locals favorite hidden gems",
    "{city} best dinner restaurants {vibe} 2025",
    "{city} city highlights must visit not tourist trap",
    "{city} best new restaurants chef driven 2025",
    "{city} best bars drinks scene 2025",
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

def search_articles(city: str, prefs: dict, api_key: str, work: bool = False,
                    hint_type: str = "") -> list[dict]:
    """
    Run search queries, return top article results from trusted domains.
    hint_type: "restaurant" | "bar" | "" — propagated to articles for type tagging.
    """
    vibe = prefs.get("vibe", "upscale-casual local")
    queries = WORK_QUERIES if work else (
        RESTAURANT_QUERIES if hint_type == "restaurant" else
        BAR_QUERIES if hint_type == "bar" else DINING_QUERIES
    )
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
                "hint_type": hint_type,
            })
        time.sleep(0.4)

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
        "search", "london", "paris", "new york", "san francisco", "the spots",
        "central", "north", "south", "east", "west", "map", "back to top",
        "choose a city", "choose a time out city", "choose a time out market",
        # Michelin / structured page labels
        "address", "opening hours", "opening times", "expect to pay",
        "telephone", "website", "email", "cuisine", "price range", "facilities",
        "link visit website", "book a table", "booking book a table",
        "more in dining out in sf", "more maps in eater sf",
        "nicola parisi dining out in sf", "dining out in sf", "the latest",
        "youtube", "more maps", "visit website", "link", "booking",
        # Footer / legal / nav links
        "editorial guidelines", "accessibility statement", "terms of use",
        "modern slavery statement", "privacy policy", "cookie policy",
        "advertise with us", "contact us", "about us", "our team",
        "advertising", "sitemap", "newsletter signup", "press",
        "investor relations", "our awards", "work for time out",
        "privacy notice", "do not sell my information", "manage cookies",
        "get listed", "claim your listing", "time out offers faq",
        "time out offers", "time out market", "time out worldwide",
        "press office", "stay in the loop", "movies", "restaurants",
        "bars", "music", "film", "theatre", "art", "travel",
        "things to do", "nightlife", "shopping", "hotels",
    }
    NOISE_PATTERNS = [
        r'^\d{4}',                          # Starts with year like "2025:"
        r'[?!]$',                           # Ends with question/exclamation
        r'^(what|why|how|where|when|who)\b', # Question words
        r'^\s*:',                           # Starts with colon
        r'^(top|best|the best|our|we|i)\s+\d', # "Top 10..." headers
        r'\bcocktail bars\b',
        r'\brestaurants in\b',
        r'\bbars in\b',
        r'^\+?\d[\d\s\(\)\-]{6,}',           # Phone numbers
        r'^phone\b',                         # "Phone ..."
        r'^(more\s+(in|maps)\b)',            # "More in..." / "More maps..."
        r'\bvisit website\b',
        r'^link\b',
        r'@',                               # Email addresses
        r'^\w+\.com\b',                     # Bare domain names
        r'^\d+\s+comment',                  # "1 Comment"
        r'^📍',                             # Emoji nav items
        r'^🏡',
        r'ready to book',
        r'ultimate guide to',
        r'\brestaurants$',           # "Fine Dining Restaurants", "Asian & African Restaurants"
        r'^(fine dining|casual dining)',
        r'food in (paris|london|san francisco)',
        r'^hit list\b',
        r'^new openings\b',
        r'^the new spots\b',
        r'^the new restaurants\b',
        r'sign up to our',
        r'\btime out\b',
        r'^\d+ comment',
        r'^sign up\b',
        # Infatuation "stats card" patterns (descriptive review metrics, not venue names)
        r'\baverage bill\b',
        r'\bteam visits\b',
        r'\bseats at\b',
        r'\bwait time\b',
        r'\bwalk-?in\b.*\bchance\b',
        r'\bthat made us\b',
        r'\bmid-sentence\b',
        r'\bdelivered by\b',
        r'\bdramatically presented\b',
        r'\bnumber of bites\b',
        r'\bbefore you realise\b',
        r'\bworth ordering\b',
        r'\bworth the\b',
        r'\bdistance between\b',
        r'\bblowtorch\b',
        r'^guide to (the|our|a|an)\b',
        r'^french style\b',
        r'^(latest|subscribe|newsletter)\b',
        r'\btravel guide',
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

def extract_neighbourhood(text: str, city: str) -> str:
    """Find a neighbourhood mention in text for the given city."""
    city_key = city.lower()
    neighbourhoods = CITY_NEIGHBOURHOODS.get(city_key, [])
    text_lower = text.lower()
    for n in neighbourhoods:
        if n.lower() in text_lower:
            return n
    return ""


def extract_cuisine(text: str) -> str:
    """Infer cuisine/bar type from description text."""
    text_lower = text.lower()
    for keyword, label in CUISINE_KEYWORDS.items():
        if keyword in text_lower:
            return label
    return ""


def infer_venue_type(text: str, is_work: bool = False) -> str:
    """Classify venue as bar / restaurant / cafe from description text."""
    if is_work:
        return "cafe"
    text_lower = text.lower()
    scores = {vtype: 0 for vtype in VENUE_TYPE_SIGNALS}
    for vtype, signals in VENUE_TYPE_SIGNALS.items():
        for s in signals:
            if s in text_lower:
                scores[vtype] += 1
    best = max(scores, key=lambda t: scores[t])
    return best if scores[best] > 0 else "restaurant"


def extract_rating(text: str) -> str:
    """Pull a rating from description text (stars, scores, Michelin)."""
    text_lower = text.lower()
    # Michelin stars
    if "three michelin" in text_lower or "3 michelin" in text_lower:
        return "⭐⭐⭐ Michelin"
    if "two michelin" in text_lower or "2 michelin" in text_lower:
        return "⭐⭐ Michelin"
    if "one michelin" in text_lower or "1 michelin" in text_lower or "michelin star" in text_lower:
        return "⭐ Michelin"
    if "michelin" in text_lower and "bib gourmand" in text_lower:
        return "Michelin Bib Gourmand"
    # World's 50 Best
    if "world's 50 best" in text_lower or "worlds 50 best" in text_lower:
        return "World's 50 Best"
    # Numeric ratings: 4.8/5, 4.8 stars, 9.2/10
    m = re.search(r'(\d+\.?\d*)\s*/\s*5\b', text)
    if m and float(m.group(1)) >= 4.0:
        return f"{m.group(1)}/5"
    m = re.search(r'(\d+\.?\d*)\s*(?:star|★)', text, re.IGNORECASE)
    if m and float(m.group(1)) >= 4.0:
        return f"★ {m.group(1)}"
    m = re.search(r'(\d+\.?\d*)\s*/\s*10\b', text)
    if m and float(m.group(1)) >= 8.0:
        return f"{m.group(1)}/10"
    return ""


def find_venue_links(name: str, city: str, api_key: str, is_work: bool = False) -> dict:
    """
    Brave-search for the venue to find:
      - official website
      - reservation platform (Resy, OpenTable, Tock, etc.)
      - neighbourhood, cuisine, type, rating (enrichment)
    """
    query = f'"{name}" {city}'
    results = brave_search(query, api_key, count=6)
    time.sleep(0.3)

    website = None
    reservation_url = None
    reservation_platform = None
    all_desc: list[str] = []

    for r in results:
        url = r.get("url", "").rstrip("/")
        desc = r.get("description", "")
        title = r.get("title", "")
        if desc:
            all_desc.append(desc)

        # Check reservation platforms
        for domain, platform in RESERVATION_DOMAINS.items():
            if domain in url and not reservation_url:
                reservation_url = url
                reservation_platform = platform
                break

        # Official venue website check
        is_noise = any(d in url for d in NON_VENUE_DOMAINS)
        if not is_noise and not website:
            try:
                domain = urllib.parse.urlparse(url).netloc.lower().lstrip("www.")
            except Exception:
                domain = ""
            name_words = [w for w in re.split(r'\W+', name.lower()) if len(w) > 2]
            domain_match = any(w in domain for w in name_words)
            if domain_match:
                website = url

    combined = " ".join(all_desc)
    neighbourhood = extract_neighbourhood(combined, city)
    cuisine = extract_cuisine(combined)
    venue_type = infer_venue_type(combined, is_work=is_work)
    rating = extract_rating(combined)

    return {
        "name": name,
        "website": website,
        "reservation_url": reservation_url,
        "reservation_platform": reservation_platform,
        "description": combined[:250] if combined else "",
        "neighbourhood": neighbourhood,
        "cuisine": cuisine,
        "type": venue_type,
        "rating": rating,
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


def _article_type_hint(url: str) -> str:
    """Infer restaurant/bar/general from article URL."""
    u = url.lower()
    if any(k in u for k in ["restaurant", "dining", "eat", "food", "where-to-eat"]):
        return "restaurant"
    if any(k in u for k in ["bar", "cocktail", "drink", "pub", "speakeasy"]):
        return "bar"
    return ""


def _scout_category(city: str, prefs: dict, api_key: str, work: bool) -> list[dict]:
    """
    One category (dining OR work) for a city.
    Pass 1 → articles. Pass 2 → extract names → lookup links + enrich.
    """
    articles = search_articles(city, prefs, api_key, work=work)
    label = "work cafes" if work else "dining"
    print(f"    Found {len(articles)} {label} articles for {city}")

    all_pairs: list[tuple[str, str]] = []   # (name, source_type_hint)

    if not work:
        # Explicitly balance: fetch 3 best restaurant articles + 3 best bar articles
        rest_articles = [a for a in articles if _article_type_hint(a["url"]) == "restaurant"]
        bar_articles  = [a for a in articles if _article_type_hint(a["url"]) == "bar"]
        general_articles = [a for a in articles if _article_type_hint(a["url"]) == ""]
        fetch_list = rest_articles[:3] + bar_articles[:3] + general_articles[:2]
        print(f"    Article mix: {len(rest_articles[:3])} restaurant, {len(bar_articles[:3])} bar, {len(general_articles[:2])} general")
    else:
        fetch_list = articles[:5]

    for article in fetch_list:
        url = article["url"]
        hint = _article_type_hint(url)
        print(f"    Fetching [{hint or 'general'}] {url[:65]}...")
        html = fetch_page(url)
        if not html:
            continue
        names = extract_names_from_html(html)
        print(f"      Extracted {len(names)} names")
        all_pairs.extend((n, hint) for n in names)
        time.sleep(0.3)

    def _clean_venue_name(n: str) -> str:
        """Strip appended location suffixes like ', Kentish Town' or ' - South Kensington'."""
        n = re.sub(r'\s*[,\-–]\s*[A-Z][a-zA-Z\s]{3,25}$', '', n).strip()
        return n

    seen: set[str] = set()
    unique: list[tuple[str, str]] = []
    for raw_n, hint in all_pairs:
        n = _clean_venue_name(raw_n)
        key = n.lower().strip()
        if key not in seen and len(key) > 3:
            seen.add(key)
            unique.append((n, hint))

    print(f"    {len(unique)} unique names — looking up links...")

    venues: list[dict] = []
    for name, source_hint in unique[:30]:
        print(f"      → {name}")
        details = find_venue_links(name, city, api_key, is_work=work)
        details["city"] = city
        # Drop obvious noise: no description and no website means the search found nothing real
        if not details.get("description") and not details.get("website"):
            continue
        # Apply source hint if type inference was ambiguous
        if source_hint and details.get("type") not in ("bar", "restaurant", "cafe"):
            details["type"] = source_hint
        elif source_hint == "restaurant" and details.get("type") == "bar":
            desc = details.get("description", "").lower()
            if any(w in desc for w in ["restaurant", "cuisine", "chef", "dinner", "dining", "menu", "kitchen"]):
                details["type"] = "restaurant"
        venues.append(details)
        if len(venues) >= 20:  # Cap clean results at 20
            break

    return venues


# ---------------------------------------------------------------------------
# Output writers
# ---------------------------------------------------------------------------

def _venue_row(v: dict, i: int) -> str:
    name = v["name"]
    website = v.get("website")
    res_url = v.get("reservation_url")
    res_platform = v.get("reservation_platform", "Book")
    neighbourhood = v.get("neighbourhood", "")
    cuisine = v.get("cuisine", "")
    rating = v.get("rating", "")
    tags = " · ".join(t for t in [neighbourhood, cuisine, rating] if t)
    desc = (v.get("description") or "").replace("|", "-")[:80]
    notes = f"{tags} | {desc}" if tags else desc

    name_cell = f"[{name}]({website})" if website else name
    book_cell = f"[{res_platform}]({res_url})" if res_url else "—"
    return f"| {i} | {name_cell} | {book_cell} | {notes[:120]} |"


def write_venues_json(trip: dict, city_dining: dict[str, list], city_work: dict[str, list]) -> Path:
    """Write structured venues.json for use by the report generator."""
    trip_id = trip["id"]
    out_dir = Path(__file__).parent / trip_id
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / "venues.json"

    data = {
        "trip_id": trip_id,
        "cities": trip["cities"],
        "dates": trip.get("dates", {}),
        "party_size": trip.get("party_size", 2),
        "generated": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "venues": {},
    }
    for city in trip["cities"]:
        data["venues"][city] = {
            "dining": city_dining.get(city, []),
            "work": city_work.get(city, []),
        }

    out_file.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"  → Wrote {out_file}")
    return out_file


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
        # Split dining into bars vs restaurants
        dining = city_dining.get(city, [])
        restaurants = [v for v in dining if v.get("type") == "restaurant"]
        bars = [v for v in dining if v.get("type") == "bar"]
        other = [v for v in dining if v.get("type") not in ("restaurant", "bar")]

        for label, subset in [("🍽 Restaurants", restaurants), ("🍸 Bars", bars), ("✨ Other", other)]:
            if not subset:
                continue
            lines += [f"## {city} — {label}", ""]
            lines += ["| # | Venue | Reserve | Tags & Notes |", "|---|-------|---------|-------------|"]
            for i, v in enumerate(subset, 1):
                lines.append(_venue_row(v, i))
            lines.append("")

        work = city_work.get(city, [])
        if work:
            lines += [f"### ☕ {city} — Work Cafes", ""]
            lines += ["| # | Venue | Book | Tags & Notes |", "|---|-------|------|-------------|"]
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

        write_venues_json(trip, city_dining, city_work)
        write_venues_md(trip, city_dining, city_work)
        write_candidates_md(trip, city_dining, city_work)
        print(f"\n✓ Done: {trip['id']}")

    print("\nAll trips processed.")
    print("Next: review candidates.md, then run travel-reservations.py.")


if __name__ == "__main__":
    main()
