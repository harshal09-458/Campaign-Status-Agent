#!/usr/bin/env python3
"""
Fetch campaign data from the Iterable API.

Usage:
    python3 tools/fetch_iterable_campaigns.py [--all] [--output PATH]

Hits GET https://api.iterable.com/api/campaigns and writes the campaign list
to .tmp/campaigns.json (default). By default only campaigns in an
"active/launched" state are kept (see ACTIVE_STATES below); pass --all to
keep every campaign regardless of state.

Auth: Iterable expects the API key in an `Api-Key` header (not Bearer).
Docs: https://api.iterable.com/api/docs#campaigns_campaigns
"""

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = PROJECT_ROOT / ".env"
DEFAULT_OUTPUT = PROJECT_ROOT / ".tmp" / "campaigns.json"

API_URL = "https://api.iterable.com/api/campaigns"

# Iterable campaignState values we consider "currently active/launched".
# Full set observed in the API: Draft, Ready, Scheduled, Running, Recurring,
# Finished, Aborted. Adjust here if Digbi's usage of these states differs.
ACTIVE_STATES = {"Running", "Recurring", "Scheduled"}


def load_env(path: Path) -> dict:
    env = {}
    if not path.exists():
        return env
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        env[key.strip()] = value.strip()
    return env


def fetch_campaigns(api_key: str) -> dict:
    request = urllib.request.Request(API_URL, headers={"Api-Key": api_key})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        raise SystemExit(f"Iterable API error {e.code}: {body}")
    except urllib.error.URLError as e:
        raise SystemExit(f"Failed to reach Iterable API: {e.reason}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--all", action="store_true", help="Keep all campaigns, not just active ones"
    )
    parser.add_argument(
        "--output", type=Path, default=DEFAULT_OUTPUT, help="Where to write the JSON output"
    )
    args = parser.parse_args()

    env = load_env(ENV_PATH)
    api_key = env.get("ITERABLE_API_KEY")
    if not api_key:
        raise SystemExit(f"ITERABLE_API_KEY not set in {ENV_PATH}")

    data = fetch_campaigns(api_key)
    campaigns = data.get("campaigns", [])

    if not args.all:
        campaigns = [c for c in campaigns if c.get("campaignState") in ACTIVE_STATES]

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(campaigns, indent=2))

    print(f"Fetched {len(campaigns)} campaign(s) -> {args.output}")
    for c in campaigns:
        print(f"  - [{c.get('campaignState')}] {c.get('name')} (id={c.get('id')})")


if __name__ == "__main__":
    main()
