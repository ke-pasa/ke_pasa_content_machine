#!/bin/bash
set -euo pipefail

# This script runs the digest worker once daily at 21:00 local time.
while true; do
  now=$(date +%s)
  # compute next 21:00
  target_today=$(date -d "21:00" +%s 2>/dev/null || date -v+0H -j -f "%H:%M" "21:00" +%s)
  if [ "$target_today" -le "$now" ]; then
    # it's past 21:00 today, schedule for tomorrow
    target=$(date -d "tomorrow 21:00" +%s 2>/dev/null || date -v+1d -j -f "%Y-%m-%d %H:%M" "$(date +%Y-%m-%d) 21:00" +%s)
  else
    target=$target_today
  fi
  sleep_seconds=$((target - now))
  sleep $sleep_seconds
  # Run the digest worker once
  python -m workers.publisher.digest_worker || true
  # small pause before recalculating next run
  sleep 5
done
