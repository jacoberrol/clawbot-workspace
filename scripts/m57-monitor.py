#!/usr/bin/env python3
"""
M57 Bus Monitor — alerts Jake when the bus is ~10 min from his stop.
Stop: WEST END AV / W 61 ST (eastbound, stop MTA_405565)
Window: 7am–8am ET, weekdays only
"""

import json
import subprocess
import sys
import urllib.request
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

# Config
STOP_ID = "MTA_405565"           # West End Av / W 61 St (eastbound M57)
LINE_REF = "MTA NYCT_M57"
ALERT_MINUTES = 10               # alert when bus is this many minutes away
ALERT_WINDOW_MINUTES = 3         # re-alert tolerance (don't spam)
STATE_FILE = "/home/exedev/.openclaw/workspace/scripts/m57-state.json"

ET = ZoneInfo("America/New_York")  # auto-handles EST/EDT transitions


def load_state():
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except Exception:
        return {"last_alerted": {}}


def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def get_arrivals():
    url = (
        f"https://bustime.mta.info/api/siri/stop-monitoring.json"
        f"?key=TEST&MonitoringRef={STOP_ID}&LineRef={LINE_REF}"
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

    arrivals = []
    for visit in visits:
        journey = visit.get("MonitoredVehicleJourney", {})
        call = journey.get("MonitoredCall", {})
        
        # Skip buses not yet in service
        progress_status = journey.get("ProgressStatus", "")
        if "prevTrip" in progress_status and "layover" in progress_status:
            continue

        expected_str = call.get("ExpectedArrivalTime") or call.get("AimedArrivalTime")
        if not expected_str:
            continue

        # Parse arrival time
        try:
            # Handle timezone offset format like "2026-02-21T21:44:36.340-05:00"
            expected = datetime.fromisoformat(expected_str)
        except ValueError:
            continue

        now = datetime.now(timezone.utc)
        minutes_away = (expected.astimezone(timezone.utc) - now).total_seconds() / 60

        distances = call.get("Extensions", {}).get("Distances", {})
        stops_away = distances.get("StopsFromCall", "?")
        readable_dist = distances.get("PresentableDistance", "")
        vehicle_ref = journey.get("VehicleRef", "unknown")

        arrivals.append({
            "vehicle": vehicle_ref,
            "minutes_away": round(minutes_away, 1),
            "stops_away": stops_away,
            "readable": readable_dist,
            "expected_time": expected_str,
        })

    return arrivals


def send_notification(message):
    """Send via openclaw message tool to Jake's Telegram."""
    try:
        result = subprocess.run(
            [
                "openclaw", "message", "send",
                "--channel", "telegram",
                "--target", "455383146",
                "--message", message,
            ],
            capture_output=True, text=True, timeout=15
        )
        if result.returncode != 0:
            print(f"Notify failed: {result.stderr}", file=sys.stderr)
        else:
            print(f"Notified: {message[:80]}")
    except Exception as e:
        print(f"Notify error: {e}", file=sys.stderr)


def main():
    now_et = datetime.now(ET)
    hour = now_et.hour
    weekday = now_et.weekday()  # 0=Mon, 6=Sun

    # Only run on weekdays, 7–8am ET
    if weekday >= 5:
        print(f"Weekend ({now_et.strftime('%A')}), skipping.")
        return

    if not (7 <= hour < 8):
        print(f"Outside window ({now_et.strftime('%H:%M')} ET), skipping.")
        return

    print(f"[{now_et.strftime('%H:%M ET')}] Checking M57 at West End & 61st...")

    try:
        arrivals = get_arrivals()
    except Exception as e:
        print(f"API error: {e}", file=sys.stderr)
        return

    if not arrivals:
        print("No buses found in API response.")
        return

    state = load_state()
    alerted_today = state.get("last_alerted", {})
    today_str = now_et.strftime("%Y-%m-%d")

    for bus in arrivals:
        mins = bus["minutes_away"]
        vehicle = bus["vehicle"]

        print(f"  Bus {vehicle}: {mins:.1f} min away ({bus['readable']}, {bus['stops_away']} stops)")

        # Alert if within our target window (8–12 min = "about 10 min")
        if 8 <= mins <= 13:
            alert_key = f"{today_str}_{vehicle}"
            last_alert = alerted_today.get(alert_key, 0)
            now_ts = now_et.timestamp()

            # Don't re-alert the same bus within 5 minutes
            if now_ts - last_alert < 300:
                print(f"  → Already alerted for this bus recently, skipping.")
                continue

            # Format arrival time nicely
            try:
                arr = datetime.fromisoformat(bus["expected_time"]).astimezone(ET)
                arr_str = arr.strftime("%-I:%M %p")
            except Exception:
                arr_str = f"{mins:.0f} min"

            msg = (
                f"🚌 M57 alert! Bus is {bus['stops_away']} stops away "
                f"(~{mins:.0f} min) — arriving West End & 61st around {arr_str}. "
                f"Time to head out!"
            )
            send_notification(msg)
            alerted_today[alert_key] = now_ts

    state["last_alerted"] = alerted_today
    save_state(state)


if __name__ == "__main__":
    main()
