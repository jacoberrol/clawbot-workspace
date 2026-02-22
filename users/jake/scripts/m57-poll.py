#!/usr/bin/env python3
"""
M57 Bus Poller — runs every minute, records current bus positions to file.
Always runs (no time window check) so "where's my bus" works any time.
"""

import json
import urllib.request
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from pathlib import Path

STOP_ID = "MTA_405565"       # West End Av / W 61 St (eastbound M57)
LINE_REF = "MTA NYCT_M57"
STATUS_FILE = Path(__file__).parent / "m57-status.json"
ET = ZoneInfo("America/New_York")


def get_arrivals():
    import urllib.parse
    url = (
        f"https://bustime.mta.info/api/siri/stop-monitoring.json"
        f"?key=TEST&MonitoringRef={STOP_ID}&LineRef={urllib.parse.quote(LINE_REF)}"
    )
    req = urllib.request.Request(url, headers={"User-Agent": "M57Monitor/1.0"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = json.loads(resp.read())

    visits = (
        data.get("Siri", {})
        .get("ServiceDelivery", {})
        .get("StopMonitoringDelivery", [{}])[0]
        .get("MonitoredStopVisit", [])
    )

    now_utc = datetime.now(timezone.utc)
    buses = []

    for visit in visits:
        journey = visit.get("MonitoredVehicleJourney", {})
        call = journey.get("MonitoredCall", {})

        expected_str = call.get("ExpectedArrivalTime") or call.get("AimedArrivalTime")
        if not expected_str:
            continue

        try:
            expected = datetime.fromisoformat(expected_str)
        except ValueError:
            continue

        minutes_away = (expected.astimezone(timezone.utc) - now_utc).total_seconds() / 60

        distances = call.get("Extensions", {}).get("Distances", {})
        progress_status = journey.get("ProgressStatus", "")
        in_service = not ("prevTrip" in progress_status and "layover" in progress_status)

        buses.append({
            "vehicle": journey.get("VehicleRef", "unknown"),
            "minutes_away": round(minutes_away, 1),
            "stops_away": distances.get("StopsFromCall", "?"),
            "distance_readable": distances.get("PresentableDistance", "?"),
            "expected_arrival": expected_str,
            "in_service": in_service,
            "progress_status": progress_status,
        })

    # Sort by arrival time
    buses.sort(key=lambda b: b["minutes_away"])
    return buses


def main():
    now_et = datetime.now(ET)
    now_utc = datetime.now(timezone.utc)

    try:
        buses = get_arrivals()
        status = {
            "polled_at": now_utc.isoformat(),
            "polled_at_et": now_et.strftime("%Y-%m-%d %H:%M:%S %Z"),
            "stop": "West End Av / W 61 St (eastbound M57)",
            "stop_id": STOP_ID,
            "buses": buses,
            "error": None,
        }
        print(f"[{now_et.strftime('%H:%M %Z')}] {len(buses)} bus(es) found")
        for b in buses[:3]:
            svc = "✅" if b["in_service"] else "🔜"
            print(f"  {svc} {b['minutes_away']:.1f} min | {b['distance_readable']} | {b['stops_away']} stops")
    except Exception as e:
        print(f"[{now_et.strftime('%H:%M %Z')}] ERROR: {e}")
        # Preserve last known good data, just add error flag
        try:
            existing = json.loads(STATUS_FILE.read_text())
        except Exception:
            existing = {}
        status = {**existing, "error": str(e), "error_at": now_utc.isoformat()}

    STATUS_FILE.write_text(json.dumps(status, indent=2))


if __name__ == "__main__":
    main()
