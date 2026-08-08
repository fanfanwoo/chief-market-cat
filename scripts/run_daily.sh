#!/bin/bash
# CMC daily pipeline runner — invoked by launchd (see com.cmc.dashboard.plist).
# Runs the full pipeline, whose final stage writes data/dashboard/dashboard_<date>.html.
# Logs each run to data/logs/run_<date>.log. Safe to run by hand to test.

PROJ="/Users/wulingsenmacpro/Codex/Vibe trading/chief-market-cat"
PY="$PROJ/.venv/bin/python"

cd "$PROJ" || { echo "cannot cd to $PROJ"; exit 1; }
mkdir -p data/logs

LOG="data/logs/run_$(date +%Y-%m-%d).log"
{
  echo "=================================================================="
  echo "=== CMC run started $(date) ==="
  "$PY" -m cmc.run
  rc=$?
  echo "--- capturing dashboard screenshot ---"
  "$PY" "$PROJ/scripts/screenshot_dashboard.py" || echo "screenshot step failed (non-fatal)"
  echo "=== CMC run finished $(date) — exit code $rc ==="
} >> "$LOG" 2>&1

exit $rc
