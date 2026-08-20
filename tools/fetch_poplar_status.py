#!/usr/bin/env python3
"""
Fetch postcard/direct-mail send status from the Poplar API.

Usage:
    python3 tools/fetch_poplar_status.py [--days N] [--all-time] [--output PATH]

Poplar has no "list all mailings" endpoint, so this tool works in two steps:
  1. GET /v1/campaigns          -> every active campaign (id, name)
  2. GET /v1/campaign/:id/mailings (paginated, filtered by created_at window)
                                 -> every mailing in that campaign, then
                                    aggregated by `state`

By default only mailings created in the last N days are pulled (--days, default
7) to avoid dragging a campaign's entire history on every run; pass --all-time
to remove that filter.

Auth: Authorization: Bearer <token> (production token required for anything
beyond the mailings-create endpoint).
Docs: https://docs.heypoplar.com/api/endpoints/other-endpoints
      https://docs.heypoplar.com/api/endpoints/mailing

Known `state` values (from Poplar docs/webhooks):
  processing, mailed, delivered, delivery_exception, failed,
  append_failed, address_invalid, suppressed, budget_exceeded,
  credit_balance_exceeded, holdout
"""

import argparse
import json
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = PROJECT_ROOT / ".env"
DEFAULT_OUTPUT = PROJECT_ROOT / ".tmp" / "poplar_status.json"

BASE_URL = "https://api.heypoplar.com/v1"
PER_PAGE = 100
MAX_RATE_LIMIT_RETRIES = 5
DEFAULT_RETRY_AFTER_SECONDS = 30


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


def api_get(path: str, api_key: str, params: dict | None = None):
    url = f"{BASE_URL}{path}"
    if params:
        query = "&".join(f"{k}={v}" for k, v in params.items() if v is not None)
        if query:
            url = f"{url}?{query}"
    request = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {api_key}",
            "User-Agent": "Mozilla/5.0 (compatible; DigbiCampaignStatusAgent/1.0)",
            "Accept": "application/json",
        },
    )
    wait_seconds = DEFAULT_RETRY_AFTER_SECONDS
    for attempt in range(1, MAX_RATE_LIMIT_RETRIES + 2):
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                body = json.loads(response.read().decode("utf-8"))
                return body, response.headers
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", errors="replace")
            if e.code == 429 and attempt <= MAX_RATE_LIMIT_RETRIES:
                try:
                    wait_seconds = json.loads(detail).get("retry_after", wait_seconds)
                except (json.JSONDecodeError, AttributeError):
                    pass
                print(f"  Poplar rate-limited (attempt {attempt}/{MAX_RATE_LIMIT_RETRIES}), waiting {wait_seconds}s before retry...")
                time.sleep(wait_seconds)
                wait_seconds *= 2
                continue
            raise SystemExit(f"Poplar API error {e.code} for {url}: {detail}")
        except urllib.error.URLError as e:
            raise SystemExit(f"Failed to reach Poplar API: {e.reason}")


def fetch_active_campaigns(api_key: str) -> list:
    campaigns, _ = api_get("/campaigns", api_key)
    return campaigns


def fetch_campaign_mailings(api_key: str, campaign_id: str, start_date: str | None, end_date: str | None) -> list:
    mailings = []
    page = 1
    while True:
        params = {"per_page": PER_PAGE, "page": page, "start_date": start_date, "end_date": end_date}
        batch, headers = api_get(f"/campaign/{campaign_id}/mailings", api_key, params)
        mailings.extend(batch)
        total_pages = headers.get("X-Total-Pages")
        if not total_pages or page >= int(total_pages):
            break
        page += 1
    return mailings


def summarize(mailings: list) -> dict:
    counts = {}
    for m in mailings:
        state = m.get("state", "unknown")
        counts[state] = counts.get(state, 0) + 1
    return counts


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--days", type=int, default=7, help="Only include mailings created in the last N days (default 7)")
    parser.add_argument("--all-time", action="store_true", help="Ignore the date window and pull full campaign history")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="Where to write the JSON output")
    args = parser.parse_args()

    env = load_env(ENV_PATH)
    api_key = env.get("POPLAR_API_KEY")
    if not api_key:
        raise SystemExit(f"POPLAR_API_KEY not set in {ENV_PATH}")

    start_date = end_date = None
    if not args.all_time:
        now = datetime.now(timezone.utc)
        start_date = (now - timedelta(days=args.days)).strftime("%Y-%m-%dT%H:%M:%S")
        end_date = now.strftime("%Y-%m-%dT%H:%M:%S")

    campaigns = fetch_active_campaigns(api_key)
    results = []
    for i, campaign in enumerate(campaigns):
        if i > 0:
            time.sleep(0.3)
        campaign_id = campaign.get("id")
        mailings = fetch_campaign_mailings(api_key, campaign_id, start_date, end_date)
        results.append(
            {
                "id": campaign_id,
                "name": campaign.get("name"),
                "total_mailings": len(mailings),
                "state_counts": summarize(mailings),
                "mailings": mailings,
            }
        )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(results, indent=2))

    window = "all time" if args.all_time else f"last {args.days} day(s)"
    print(f"Fetched {len(results)} active campaign(s), mailings window: {window} -> {args.output}")
    for c in results:
        counts_str = ", ".join(f"{k}={v}" for k, v in c["state_counts"].items()) or "no mailings in window"
        print(f"  - {c['name']} (id={c['id']}): {c['total_mailings']} mailing(s) [{counts_str}]")


if __name__ == "__main__":
    main()
