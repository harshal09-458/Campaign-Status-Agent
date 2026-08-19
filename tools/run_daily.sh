#!/bin/bash
# Runs the full Post Campaign Status pipeline end to end. Invoked by
# launchd (com.digbihealth.campaign-status-agent.plist) daily at 10:00 AM
# IST — not meant to be edited per-run; edit the pipeline steps here if the
# workflow changes, and update workflows/post_campaign_status.md to match.
set -e

PROJECT_ROOT="/Users/harshalgundetty/Documents/Digbi Campaign Status Agent"
PYTHON="/opt/homebrew/bin/python3"

cd "$PROJECT_ROOT"

echo "=== Run started: $(date) ==="

"$PYTHON" tools/fetch_iterable_sent.py
"$PYTHON" tools/fetch_poplar_status.py --days 1
"$PYTHON" tools/group_by_client.py
"$PYTHON" tools/compose_messages.py
"$PYTHON" tools/post_to_slack.py

echo "=== Run finished: $(date) ==="
