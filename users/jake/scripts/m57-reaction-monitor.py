#!/usr/bin/env python3
"""
M57 Reaction Monitor — monitors Telegram reactions to bus alerts.
When a 👍 reaction is detected on a bus alert message, mutes alerts until midnight.

Requires: Telegram bot token set in environment variable TELEGRAM_BOT_TOKEN

Can also be called manually:
  python3 m57-reaction-monitor.py --mute-until 23:59   # mute until 11:59pm ET today
  python3 m57-reaction-monitor.py --unmute              # unmute immediately
"""

import json
import sys
import argparse
from datetime import datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

MUTE_FILE = Path(__file__).parent / "m57-mute.json"
ET = ZoneInfo("America/New_York")


def get_midnight_et():
    """Get today's midnight ET as an ISO timestamp."""
    now_et = datetime.now(ET)
    midnight = now_et.replace(hour=23, minute=59, second=59, microsecond=0)
    return midnight.isoformat()


def mute_until(until_time):
    """Mute alerts until a specific ISO timestamp."""
    mute_data = {"muted_until": until_time}
    MUTE_FILE.write_text(json.dumps(mute_data, indent=2))
    print(f"Alerts muted until {until_time}")


def unmute():
    """Unmute alerts immediately."""
    if MUTE_FILE.exists():
        MUTE_FILE.unlink()
    print("Alerts unmuted")


def check_reactions():
    """
    Check recent messages for 👍 reactions on bus alerts.
    Currently a placeholder — requires Telegram bot token to implement.
    
    TODO: Implement using Telegram Bot API:
    1. Query chat history for last N messages
    2. Look for messages containing "🚌" (bus alert marker)
    3. Check reactions on those messages
    4. If 👍 found, call mute_until(midnight)
    """
    print("🔍 Checking reactions... (not yet implemented)")
    print("   Need Telegram bot token to query message reactions.")
    print("   For now, use: python3 m57-reaction-monitor.py --mute-until 23:59")


def main():
    parser = argparse.ArgumentParser(description="Monitor bus alert reactions")
    parser.add_argument("--mute-until", help="Mute until this time (ISO format, default: today's 23:59:59 ET)")
    parser.add_argument("--unmute", action="store_true", help="Unmute alerts immediately")
    parser.add_argument("--check", action="store_true", help="Check for 👍 reactions (requires bot token)")
    
    args = parser.parse_args()
    
    if args.unmute:
        unmute()
    elif args.mute_until:
        mute_until(args.mute_until)
    elif args.check:
        check_reactions()
    else:
        # Default: check reactions
        check_reactions()


if __name__ == "__main__":
    main()
