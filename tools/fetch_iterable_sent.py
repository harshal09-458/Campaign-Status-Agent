#!/usr/bin/env python3
"""
Find Iterable campaigns that actually SENT something in a recent time window
(default: last 24 hours) — regardless of current campaignState. A campaign's
state (Running/Finished/etc.) says nothing about whether it sent in this
specific window, so the only signal that matters is the metrics endpoint's
sent count for the window itself.

Pulls every campaign in the account, batches their IDs through
GET /api/campaigns/metrics (repeated `campaignId=` params, since the
endpoint doesn't accept a comma-separated list), and keeps only campaigns
with a nonzero "sent" count in the window.

Usage:
    python3 tools/fetch_iterable_sent.py [--hours 24] [--output PATH]

Auth: `Api-Key: <key>` header (not Bearer).
Metrics endpoint quirks learned by testing directly against the live API:
  - startDateTime/endDateTime must be ISO8601 WITH a trailing `Z` (or
    milliseconds + `Z`) — a bare "2026-08-03T00:00:00" is rejected.
  - Multiple campaign IDs are NOT comma-separated; repeat the query param:
    ?campaignId=1&campaignId=2&campaignId=3
  - Response is CSV (Content-Type: text/plain), not JSON.
"""

import argparse
import csv
import io
import re
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = PROJECT_ROOT / ".env"
DEFAULT_OUTPUT = PROJECT_ROOT / ".tmp" / "iterable_sent.json"

CAMPAIGNS_URL = "https://api.iterable.com/api/campaigns"
METRICS_URL = "https://api.iterable.com/api/campaigns/metrics"
BATCH_SIZE = 200
SENT_COLUMN_RE = re.compile(r"\bsent\b|\bsends\b", re.IGNORECASE)


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


def api_get(url: str, api_key: str) -> str:
    request = urllib.request.Request(url, headers={"Api-Key": api_key})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        raise SystemExit(f"Iterable API error {e.code} for {url}: {e.read().decode('utf-8', errors='replace')}")
    except urllib.error.URLError as e:
        raise SystemExit(f"Failed to reach Iterable API: {e.reason}")


def fetch_all_campaigns(api_key: str) -> list:
    import json

    body = api_get(CAMPAIGNS_URL, api_key)
    return json.loads(body).get("campaigns", [])


def iso_z(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")


def fetch_metrics(api_key: str, campaign_ids: list, start: datetime, end: datetime) -> list:
    rows = []
    for i in range(0, len(campaign_ids), BATCH_SIZE):
        batch = campaign_ids[i : i + BATCH_SIZE]
        params = "&".join(f"campaignId={cid}" for cid in batch)
        url = f"{METRICS_URL}?{params}&startDateTime={iso_z(start)}&endDateTime={iso_z(end)}"
        csv_text = api_get(url, api_key)
        reader = csv.DictReader(io.StringIO(csv_text))
        rows.extend(reader)
    return rows


def sent_count(row: dict) -> int:
    total = 0
    for col, val in row.items():
        if col == "id" or not SENT_COLUMN_RE.search(col):
            continue
        try:
            total += int(float(val))
        except (TypeError, ValueError):
            continue
    return total


def find_col(row: dict, *substrings: str):
    """Find a column whose name contains all given substrings, case-insensitively."""
    for col in row:
        lower = col.lower()
        if all(s in lower for s in substrings):
            return row[col]
    return None


def pct(numerator, denominator):
    try:
        num, den = float(numerator), float(denominator)
    except (TypeError, ValueError):
        return None
    if den <= 0:
        return None
    return round(num / den * 100, 1)


def rates_for(row: dict, message_medium: str) -> dict:
    """
    Open/click rate, matching Iterable's own dashboard formula (confirmed via
    their Metric Definitions support page): Unique <X> (filtered) / Unique
    Emails Delivered. Open rate has no SMS equivalent (no open-tracking
    pixel), so it's always None for SMS — per explicit instruction
    (2026-08-04), the Slack message should omit that line for SMS rather
    than show "N/A".

    SMS click-rate column names are NOT verified against a live SMS send
    (this account had none active when this was written) — found
    defensively by substring match ("sms" + "click" / "sms" + "delivered").
    If this ever returns None for a real SMS campaign, check the raw
    `metrics` dict in the output JSON for the actual column names and fix
    the substrings here.
    """
    medium = (message_medium or "").lower()
    if medium == "email":
        return {
            "open_rate_pct": pct(row.get("Unique Email Opens (filtered)"), row.get("Unique Emails Delivered")),
            "click_rate_pct": pct(row.get("Unique Email Clicks (filtered)"), row.get("Unique Emails Delivered")),
        }
    if medium == "sms":
        delivered = find_col(row, "sms", "deliver") or find_col(row, "sms", "sent")
        return {
            "open_rate_pct": None,
            "click_rate_pct": pct(find_col(row, "sms", "click"), delivered),
        }
    return {"open_rate_pct": None, "click_rate_pct": None}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--hours", type=int, default=24, help="Reporting window size in hours (default 24)")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    env = load_env(ENV_PATH)
    api_key = env.get("ITERABLE_API_KEY")
    if not api_key:
        raise SystemExit(f"ITERABLE_API_KEY not set in {ENV_PATH}")

    now = datetime.now(timezone.utc)
    window_start = now - timedelta(hours=args.hours)

    all_campaigns = fetch_all_campaigns(api_key)
    metrics_rows = fetch_metrics(api_key, [c["id"] for c in all_campaigns], window_start, now) if all_campaigns else []
    campaigns_by_id = {c["id"]: c for c in all_campaigns}

    sent_campaigns = []
    for row in metrics_rows:
        count = sent_count(row)
        if count <= 0:
            continue
        campaign_id = int(row["id"])
        campaign = campaigns_by_id.get(campaign_id, {})
        medium = campaign.get("messageMedium")
        sent_campaigns.append(
            {
                "id": campaign_id,
                "name": campaign.get("name"),
                "campaignState": campaign.get("campaignState"),
                "messageMedium": medium,
                "sent_count": count,
                **rates_for(row, medium),
                "metrics": row,
            }
        )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    import json

    args.output.write_text(json.dumps(sent_campaigns, indent=2))

    print(
        f"Checked {len(all_campaigns)} campaign(s) for sends in the last {args.hours}h "
        f"-> {len(sent_campaigns)} sent something -> {args.output}"
    )
    for c in sent_campaigns:
        rate_bits = []
        if c["open_rate_pct"] is not None:
            rate_bits.append(f"open {c['open_rate_pct']}%")
        if c["click_rate_pct"] is not None:
            rate_bits.append(f"click {c['click_rate_pct']}%")
        rate_str = f" ({', '.join(rate_bits)})" if rate_bits else ""
        print(f"  - {c['name']} (id={c['id']}, state={c['campaignState']}): {c['sent_count']} sent{rate_str}")


if __name__ == "__main__":
    main()
