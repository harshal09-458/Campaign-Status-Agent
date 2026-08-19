#!/usr/bin/env python3
"""
Post composed client messages to Slack via a bot token (chat.postMessage),
NOT the MCP connector — this is meant to run unattended (local cron/launchd),
and MCP posting only works inside a live interactive Claude session.

Usage:
    python3 tools/post_to_slack.py [--messages PATH]

Requires SLACK_BOT_TOKEN in .env — a bot token (starts with xoxb-) from a
Slack app with the chat:write scope, installed to the workspace. The bot
must also be INVITED into each client's channel individually (Slack
requires bot membership to post into private channels — `/invite @BotName`
in each one); posting will fail with "not_in_channel" for any channel it
hasn't been added to yet.

Continues past individual channel failures (e.g. one channel not yet
invited) rather than aborting the whole run — reports a clear per-client
summary either way. Exits nonzero if at least one post failed, so cron logs
make failures visible.
"""

import argparse
import json
import urllib.error
import urllib.request
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = PROJECT_ROOT / ".env"
DEFAULT_MESSAGES = PROJECT_ROOT / ".tmp" / "client_messages.json"

POST_MESSAGE_URL = "https://slack.com/api/chat.postMessage"


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


def post_message(token: str, channel_id: str, text: str) -> dict:
    body = json.dumps({"channel": channel_id, "text": text}).encode("utf-8")
    request = urllib.request.Request(
        POST_MESSAGE_URL,
        data=body,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=utf-8",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--messages", type=Path, default=DEFAULT_MESSAGES)
    args = parser.parse_args()

    env = load_env(ENV_PATH)
    token = env.get("SLACK_BOT_TOKEN")
    if not token:
        raise SystemExit(f"SLACK_BOT_TOKEN not set in {ENV_PATH}")

    if not args.messages.exists():
        print(f"No {args.messages} found — nothing to post.")
        return

    messages = json.loads(args.messages.read_text())
    if not messages:
        print("No clients had activity in this window — posting nothing.")
        return

    failures = []
    for client, m in messages.items():
        try:
            result = post_message(token, m["channel_id"], m["message"])
        except urllib.error.HTTPError as e:
            failures.append((client, m["channel_name"], f"HTTP {e.code}: {e.read().decode('utf-8', errors='replace')}"))
            continue
        except urllib.error.URLError as e:
            failures.append((client, m["channel_name"], f"network error: {e.reason}"))
            continue

        if result.get("ok"):
            print(f"  - {client} -> #{m['channel_name']}: posted")
        else:
            failures.append((client, m["channel_name"], result.get("error", "unknown error")))

    print(f"Posted {len(messages) - len(failures)}/{len(messages)} message(s).")
    if failures:
        print(f"  ! {len(failures)} failure(s):")
        for client, channel_name, error in failures:
            print(f"      {client} (#{channel_name}): {error}")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
