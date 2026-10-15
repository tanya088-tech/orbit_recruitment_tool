#!/bin/bash
# Double-click this file to start Ace Talent Consulting Job Radar. It opens the dashboard in your browser.
# Keep this window open while you use the dashboard; close it to stop the app.
cd "$(dirname "$0")" || exit 1
if [ -x ".venv/bin/python3" ]; then PY=".venv/bin/python3"; else PY="python3"; fi
"$PY" run_dashboard.py --ingest --open
status=$?
if [ $status -ne 0 ]; then
  echo
  echo "Ace Talent Consulting Job Radar stopped with an error (code $status). Read the message above."
  read -r -p "Press Return to close this window. "
fi
