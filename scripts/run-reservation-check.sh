#!/bin/bash
# Gastropub Reservation Monitor — wrapper script
# Runs the Playwright check and sends an OpenClaw notification if slots are found.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_FILE="$SCRIPT_DIR/reservation-check.log"
NODE_SCRIPT="$SCRIPT_DIR/check-reservations.js"

# Run the check, capture output
OUTPUT=$(node "$NODE_SCRIPT" 2>&1)
EXIT_CODE=$?

# Log everything
echo "=== $(date -u +"%Y-%m-%d %H:%M:%S UTC") ===" >> "$LOG_FILE"
echo "$OUTPUT" >> "$LOG_FILE"
echo "" >> "$LOG_FILE"

# Check if there's new availability to notify about
NOTIFY_LINE=$(echo "$OUTPUT" | grep "^NOTIFY:" | head -1)

if [ -z "$NOTIFY_LINE" ]; then
  # Script may have errored
  if [ $EXIT_CODE -ne 0 ]; then
    echo "[reservation-check] Script failed, check $LOG_FILE" >&2
  fi
  exit $EXIT_CODE
fi

NOTIFY_MSG="${NOTIFY_LINE#NOTIFY:}"

if [ "$NOTIFY_MSG" != "none" ] && [ -n "$NOTIFY_MSG" ]; then
  # Send notification via openclaw
  MSG="🎉 Reservation slots found! $NOTIFY_MSG — check now and book before they go!"
  openclaw message send --message "$MSG" 2>/dev/null || true
  echo "[reservation-check] Notified: $NOTIFY_MSG"
fi

exit 0
