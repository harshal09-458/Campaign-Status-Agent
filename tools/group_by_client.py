#!/usr/bin/env python3
"""
Group "sent in the last 24h" campaign data by client.

Usage:
    python3 tools/group_by_client.py [--iterable-sent PATH] [--poplar PATH] [--output PATH]

Reads the outputs of fetch_iterable_sent.py (email/SMS sends) and
fetch_poplar_status.py (postcard sends, run with --days 1), matches each
campaign's name against tools/client_roster.json (case-insensitive,
word-boundary keyword match), and writes a per-client summary of what
actually sent.

Only campaigns that sent something are considered — a quiet Poplar campaign
with zero mailings in the window is never matched or reported, so
"unmatched" only ever surfaces things that genuinely sent but aren't
recognized yet.
"""

import argparse
import json
import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ROSTER_PATH = PROJECT_ROOT / "tools" / "client_roster.json"
DEFAULT_ITERABLE_SENT = PROJECT_ROOT / ".tmp" / "iterable_sent.json"
DEFAULT_POPLAR = PROJECT_ROOT / ".tmp" / "poplar_status.json"
DEFAULT_OUTPUT = PROJECT_ROOT / ".tmp" / "client_status.json"


def load_roster(path: Path) -> list:
    roster = json.loads(path.read_text())["clients"]
    for entry in roster:
        entry["_patterns"] = [
            re.compile(r"\b" + re.escape(alias) + r"\b", re.IGNORECASE) for alias in entry["aliases"]
        ]
    return roster


def match_client(name: str, roster: list) -> str | None:
    best_client = None
    best_len = -1
    for entry in roster:
        for alias, pattern in zip(entry["aliases"], entry["_patterns"]):
            if pattern.search(name) and len(alias) > best_len:
                best_client = entry["client"]
                best_len = len(alias)
    return best_client


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iterable-sent", type=Path, default=DEFAULT_ITERABLE_SENT)
    parser.add_argument("--poplar", type=Path, default=DEFAULT_POPLAR)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    roster = load_roster(ROSTER_PATH)
    client_names = [entry["client"] for entry in roster]
    grouped = {name: {"iterable_sent": [], "poplar_sent": []} for name in client_names}
    unmatched = []

    if args.iterable_sent.exists():
        for c in json.loads(args.iterable_sent.read_text()):
            name = c.get("name", "")
            client = match_client(name, roster)
            entry = {
                "id": c.get("id"),
                "name": name,
                "sent_count": c.get("sent_count"),
                "messageMedium": c.get("messageMedium"),
                "open_rate_pct": c.get("open_rate_pct"),
                "click_rate_pct": c.get("click_rate_pct"),
            }
            if client:
                grouped[client]["iterable_sent"].append(entry)
            else:
                unmatched.append({"source": "iterable", **entry})

    if args.poplar.exists():
        for c in json.loads(args.poplar.read_text()):
            if c.get("total_mailings", 0) <= 0:
                continue
            name = c.get("name", "")
            client = match_client(name, roster)
            entry = {
                "id": c.get("id"),
                "name": name,
                "total_mailings": c.get("total_mailings"),
                "state_counts": c.get("state_counts"),
            }
            if client:
                grouped[client]["poplar_sent"].append(entry)
            else:
                unmatched.append({"source": "poplar", **entry})

    result = {"clients": grouped, "unmatched": unmatched}

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2))

    active_clients = [name for name in client_names if grouped[name]["iterable_sent"] or grouped[name]["poplar_sent"]]
    print(f"Grouped sends for {len(client_names)} roster client(s), {len(active_clients)} with activity in this window -> {args.output}")
    for name in active_clients:
        g = grouped[name]
        print(f"  - {name}: {len(g['iterable_sent'])} Iterable send(s), {len(g['poplar_sent'])} Poplar campaign(s) with sends")
    if unmatched:
        print(f"  ! {len(unmatched)} unmatched send(s) — review and add aliases to {ROSTER_PATH}:")
        for u in unmatched:
            print(f"      [{u['source']}] {u['name']}")


if __name__ == "__main__":
    main()
