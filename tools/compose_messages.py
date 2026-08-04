#!/usr/bin/env python3
"""
Compose the exact Slack message text for each client with activity, from
tools/client_channels.json + .tmp/client_status.json.

Formatting is fully deterministic (fixed templates, no judgment calls), so
it lives here rather than being freehand-composed at post time — one less
place for the wording to drift day to day.

Usage:
    python3 tools/compose_messages.py [--client-status PATH] [--output PATH]

Templates (per explicit instruction, 2026-08-04):

  Email/SMS (one block per Iterable campaign that sent):
    Last 24 hrs campaign sent:
    Campaign Name: <name>
    Campaign ID: <id>
    Total Sent: <sent_count>
    Open Rate: <open_rate_pct>%      (omitted entirely for SMS — no open tracking)
    Click Rate: <click_rate_pct>%

  Postcards (one block per Poplar campaign that sent):
    Last 24 hrs postcards sent:
    Campaign Name: <name>
    Campaign ID: <id>
    Total Sent: <total_mailings>
    Delivered: <state_counts.delivered, or 0>

A client with multiple campaigns in a day gets one Slack message containing
multiple blocks (separated by a divider), not one message per campaign —
keeps channel noise down.

Output: .tmp/client_messages.json, only for clients with something to post:
  { "<client>": { "channel_id": ..., "channel_name": ..., "message": "..." } }
"""

import argparse
import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CLIENT_STATUS = PROJECT_ROOT / ".tmp" / "client_status.json"
CHANNELS_PATH = PROJECT_ROOT / "tools" / "client_channels.json"
DEFAULT_OUTPUT = PROJECT_ROOT / ".tmp" / "client_messages.json"

DIVIDER = "\n\n---\n\n"


def rate_str(value) -> str:
    return f"{value}%" if value is not None else "N/A"


def format_iterable_block(c: dict) -> str:
    lines = [
        "Last 24 hrs campaign sent:",
        f"Campaign Name: {c['name']}",
        f"Campaign ID: {c['id']}",
        f"Total Sent: {c['sent_count']}",
    ]
    if (c.get("messageMedium") or "").lower() != "sms":
        lines.append(f"Open Rate: {rate_str(c.get('open_rate_pct'))}")
    lines.append(f"Click Rate: {rate_str(c.get('click_rate_pct'))}")
    return "\n".join(lines)


def format_poplar_block(c: dict) -> str:
    delivered = (c.get("state_counts") or {}).get("delivered", 0)
    lines = [
        "Last 24 hrs postcards sent:",
        f"Campaign Name: {c['name']}",
        f"Campaign ID: {c['id']}",
        f"Total Sent: {c['total_mailings']}",
        f"Delivered: {delivered}",
    ]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--client-status", type=Path, default=DEFAULT_CLIENT_STATUS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    status = json.loads(args.client_status.read_text())["clients"]
    channels = json.loads(CHANNELS_PATH.read_text())["channels"]

    messages = {}
    skipped_no_channel = []

    for client, data in status.items():
        blocks = [format_iterable_block(c) for c in data.get("iterable_sent", [])]
        blocks += [format_poplar_block(c) for c in data.get("poplar_sent", [])]
        if not blocks:
            continue

        channel = channels.get(client)
        if not channel:
            skipped_no_channel.append(client)
            continue

        messages[client] = {
            "channel_id": channel["channel_id"],
            "channel_name": channel["channel_name"],
            "message": DIVIDER.join(blocks),
        }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(messages, indent=2))

    print(f"Composed {len(messages)} message(s) -> {args.output}")
    for client, m in messages.items():
        print(f"  - {client} -> #{m['channel_name']}")
    if skipped_no_channel:
        print(f"  ! {len(skipped_no_channel)} client(s) had activity but no channel mapping — add to {CHANNELS_PATH}:")
        for client in skipped_no_channel:
            print(f"      {client}")


if __name__ == "__main__":
    main()
