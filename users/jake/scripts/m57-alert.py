#!/usr/bin/env python3
"""
M57 Alert - runs every minute between 6:30-8:30am ET.
Reads the status file written by m57-poll.py and notifies Jake
when a bus is ~10 minutes from his stop.
"""

import json
import os
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv_loader import load_dotenv
load_dotenv()

STATUS_FILE = Path(__file__).parent / "m57-status.json"
ALERT_STATE_FILE = Path(__file__).parent / "m57-alert-state.json"

ET = ZoneInfo("America/New_York")
ALERT_MIN = 8    # lower bound: alert if bus is >= this many minutes away
ALERT_MAX = 13   # upper bound: alert if bus is <= this many minutes away
RESEND_COOLDOWN = 300  # don't re-alert same bus within 5 minutes (seconds)

# Alert window: 6:30am–8:30am ET
WINDOW_START = (6, 30)
WINDOW_END   = (8, 30)


def in_window(now_et):
    t = (now_et.hour, now_et.minute)
    return WINDOW_START <= t < WINDOW_END


def load_alert_state():
    try:
        return json.loads(ALERT_STATE_FILE.read_text())
    except Exception:
        return {"alerted": {}}


def save_alert_state(state):
    ALERT_STATE_FILE.write_text(json.dumps(state, indent=2))


def send_notification(message):
    try:
        result = subprocess.run(
            [
                "openclaw", "message", "send",
                "--channel", "telegram",
                "--target", os.environ.get("TELEGRAM_TARGET", ""),
                "--message", message,
            ],
            capture_output=True, text=True, timeout=15
        )
        if result.returncode != 0:
            print(f"Notify failed: {result.stderr}", file=sys.stderr)
        else:
            print(f"Notified: {message[:100]}")
    except Exception as e:
        print(f"Notify error: {e}", file=sys.stderr)


def main():
    now_et = datetime.now(ET)

    if not in_window(now_et):
        print(f"[{now_et.strftime('%H:%M %Z')}] Outside alert window, skipping.")
        return

    # Load latest poll data
    try:
        status = json.loads(STATUS_FILE.read_text())
    except Exception as e:
        print(f"Could not read status file: {e}", file=sys.stderr)
        return

    if status.get("error"):
        print(f"Last poll had error: {status['error']}")
        return

    buses = status.get("buses", [])
    polled_at = status.get("polled_at_et", "unknown")
    alert_state = load_alert_state()
    alerted = alert_state.get("alerted", {})
    now_ts = now_et.timestamp()
    today_str = now_et.strftime("%Y-%m-%d")

    print(f"[{now_et.strftime('%H:%M %Z')}] Checking {len(buses)} bus(es) from poll at {polled_at}")

    for bus in buses:
        mins = bus["minutes_away"]
        vehicle = bus["vehicle"]
        in_service = bus.get("in_service", True)

        print(f"  Bus {vehicle}: {mins:.1f} min | {bus['distance_readable']} | in_service={in_service}")

        if not in_service:
            continue

        if ALERT_MIN <= mins <= ALERT_MAX:
            alert_key = f"{today_str}_{vehicle}"
            last_alert_ts = alerted.get(alert_key, 0)

            if now_ts - last_alert_ts < RESEND_COOLDOWN:
                print(f"  → Already alerted this bus recently, skipping.")
                continue

            # Format arrival time
            try:
                from datetime import timezone
                arr = datetime.fromisoformat(bus["expected_arrival"]).astimezone(ET)
                arr_str = arr.strftime("%-I:%M %p")
            except Exception:
                arr_str = f"~{mins:.0f} min"

            msg = (
                f"🚌 M57 alert! Bus is {bus['stops_away']} stops away "
                f"(~{mins:.0f} min) — arriving West End & 61st around {arr_str}. "
                f"Time to head out!"
            )
            send_notification(msg)
            alerted[alert_key] = now_ts

    alert_state["alerted"] = alerted
    save_alert_state(alert_state)


if __name__ == "__main__":
    main()
