#!/bin/bash
# Daily auto-commit and push for the clawbot workspace.
# Cron: 0 4 * * * (4am UTC daily)

WORKSPACE="/home/exedev/clawbot/workspace"
SCRIPTS="$WORKSPACE/users/jake/scripts"
LOG="$SCRIPTS/git-autopush.log"

cd "$WORKSPACE" || exit 1

# Export current crontab so it's version controlled
crontab -l > "$SCRIPTS/crontab.txt" 2>/dev/null || true

# Stage any changes
git add -A

# Only commit if there's something new
if git diff --cached --quiet; then
  echo "[$(date -u +"%Y-%m-%d %H:%M UTC")] Nothing to commit." >> "$LOG"
  exit 0
fi

TIMESTAMP=$(date -u +"%Y-%m-%d %H:%M UTC")
git commit -m "Auto-commit: $TIMESTAMP"
git push origin main >> "$LOG" 2>&1
PUSH_STATUS=$?

if [ $PUSH_STATUS -eq 0 ]; then
  echo "[$TIMESTAMP] Pushed OK." >> "$LOG"
else
  echo "[$TIMESTAMP] Push FAILED — check $LOG" >> "$LOG"
fi
