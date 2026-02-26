#!/usr/bin/env python3
"""
M57 Reaction Monitor — monitors Telegram reactions to bus alerts via OpenClaw.
When a 👍 reaction is detected on a bus alert message, mutes alerts until midnight.

Uses OpenClaw's message API (no token replication — reuses existing OpenClaw config).

Can also be called manually:
  python3 m57-reaction-monitor.py --mute-until 23:59   # mute until 11:59pm ET today
  python3 m57-reaction-monitor.py --unmute              # unmute immediately
"""

import json
import os
import sys
import subprocess
import argparse
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

MUTE_FILE = Path(__file__).parent / "m57-mute.json"
LAST_MESSAGE_FILE = Path(__file__).parent / "m57-last-alert.json"
ET = ZoneInfo("America/New_York")

TELEGRAM_TARGET = os.environ.get("TELEGRAM_TARGET", "455383146")


def get_midnight_et():
    """Get today's 23:59:59 ET as an ISO timestamp."""
    now_et = datetime.now(ET)
    midnight = now_et.replace(hour=23, minute=59, second=59, microsecond=0)
    return midnight.isoformat()


def mute_until(until_time):
    """Mute alerts until a specific ISO timestamp."""
    mute_data = {"muted_until": until_time}
    MUTE_FILE.write_text(json.dumps(mute_data, indent=2))
    print(f"✅ Alerts muted until {until_time}")


def unmute():
    """Unmute alerts immediately."""
    if MUTE_FILE.exists():
        MUTE_FILE.unlink()
    print("✅ Alerts unmuted")


def check_reactions():
    """
    Check for 👍 reactions on the last bus alert message via OpenClaw's reactions API.
    """
    if not LAST_MESSAGE_FILE.exists():
        print("ℹ️  No recent alert message on file")
        return
    
    try:
        last_msg = json.loads(LAST_MESSAGE_FILE.read_text())
        msg_id = last_msg.get("message_id")
        if not msg_id:
            print("ℹ️  No message ID found")
            return
    except Exception as e:
        print(f"⚠️  Could not read last message file: {e}")
        return
    
    try:
        result = subprocess.run(
            [
                "/home/exedev/.npm-global/bin/openclaw", "message", "reactions",
                "--channel", "telegram",
                "--target", TELEGRAM_TARGET,
                "--message-id", str(msg_id),
                "--json",
            ],
            capture_output=True, text=True, timeout=10
        )
        
        if result.returncode != 0:
            print(f"⚠️  Error querying reactions: {result.stderr[:150]}")
            return
        
        try:
            response = json.loads(result.stdout)
            reactions = response.get("reactions", [])
            
            # Look for 👍 emoji
            thumbs_up = next((r for r in reactions if r.get("emoji") == "👍"), None)
            if thumbs_up:
                print(f"👍 Thumbs up reaction detected!")
                mute_until(get_midnight_et())
                return
            
            # Also check by emoji name
            thumbs_up_named = next(
                (r for r in reactions if "thumbs" in r.get("emoji_name", "").lower()),
                None
            )
            if thumbs_up_named:
                print(f"👍 Thumbs up reaction detected!")
                mute_until(get_midnight_et())
                return
            
            print(f"ℹ️  {len(reactions)} reaction(s) found, but no 👍")
        
        except json.JSONDecodeError as e:
            print(f"⚠️  Could not parse reactions response: {e}")
    
    except Exception as e:
        print(f"⚠️  Error checking reactions: {e}")


def main():
    parser = argparse.ArgumentParser(description="Monitor bus alert reactions")
    parser.add_argument("--mute-until", help="Mute until this time (ISO format, default: today's 23:59:59 ET)")
    parser.add_argument("--unmute", action="store_true", help="Unmute alerts immediately")
    parser.add_argument("--check", action="store_true", help="Check for 👍 reactions via OpenClaw")
    
    args = parser.parse_args()
    
    if args.unmute:
        unmute()
    elif args.mute_until:
        mute_until(args.mute_until)
    else:  # default: check reactions
        check_reactions()


if __name__ == "__main__":
    main()
