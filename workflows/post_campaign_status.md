# Post Campaign Status

## Objective
Every morning, report what actually **sent in the last 24 hours** — email/SMS
(Iterable) and postcards (Poplar) — to Slack, **one post per client, in that
client's own Slack channel**. This is not a combined digest; each client only
sees their own activity.

## Schedule
Intended to run daily at **10:00 AM IST**, unattended. Status: still being
validated — see "Automation status" below before assuming this fires on its
own.

## Client roster
`tools/client_roster.json` maps each client to keyword aliases matched
(case-insensitive, word-boundary) against campaign names. **Scope is
deliberately limited to 22 named clients** (per explicit instruction —
2026-08-04): PRISM, Zachry, City of Fort Worth, AAA, Elbit, Vericast, Dexter,
West Fargo, NAEBT, CCT, GEICO, Dexcom, KeHE, NDPHIT, Evry, Silgan, AZLGEBT,
RAGHT, FRP, Mohave County (MCEBT), SSCGP (Southern Star), Weston.

Two pairs from the original 24-name list turned out to each be one client
under two different naming conventions (confirmed with the user
2026-08-04), merged into single roster entries with both aliases:
- **Mohave County (MCEBT)** — "MCEBT" = Mohave County Employee Benefit
  Trust, same pattern as NAEBT/AZLGEBT.
- **SSCGP (Southern Star)** — same client, two names.

The Iterable/Poplar accounts contain other active campaigns outside this
list (e.g. Bausch Health, GCRBC, HRB, Okaloosa, RS Hughes, Schreiber Foods,
Trinchero, plus generic/test campaigns like kit-return reminders and
surveys) — these are **intentionally excluded** from the report, not an
oversight. Don't add them back to the roster without the user asking.

## Per-client Slack channels
`tools/client_channels.json` maps each roster client to its Slack channel
(name + ID), found via `slack_search_channels` on 2026-08-04. Naming
convention is `#<client>-marketing` (private channels, mostly).

## Message format
Confirmed 2026-08-04. One block per campaign that sent; a client with
multiple sends in the window gets one Slack message with multiple blocks
(divided by `---`), not one message per campaign.

**Email/SMS (Iterable), one block per campaign:**
```
Last 24 hrs campaign sent:
Campaign Name: <name>
Campaign ID: <id>
Total Sent: <sent_count>
Open Rate: <open_rate_pct>%
Click Rate: <click_rate_pct>%
```
No "Campaign Link" line — explicitly dropped, not needed. For SMS
campaigns, the **Open Rate line is omitted entirely** (no open-tracking
pixel for SMS); Click Rate is still shown.

**Postcards (Poplar), one block per campaign:**
```
Last 24 hrs postcards sent:
Campaign Name: <name>
Campaign ID: <id>
Total Sent: <total_mailings>
Delivered: <count of state == "delivered">
```
Deliberately just these two numbers — no cost, no failed/undeliverable
breakdown, no per-recipient address data. `Delivered` will often read `0`
for something sent in the last 24h, since USPS transit alone takes several
days — that's expected, not a bug (see Edge cases).

`tools/compose_messages.py` generates this deterministically from
`.tmp/client_status.json` + `tools/client_channels.json` — see Steps below.

## Steps

1. **Fetch Iterable sends (last 24h)**
   `python3 tools/fetch_iterable_sent.py`
   → writes `.tmp/iterable_sent.json`. Checks every campaign in the account
   (not just currently-"Running" ones — a one-time campaign can send and
   finish inside the window) against `GET /api/campaigns/metrics` for the
   window, keeping only campaigns with a nonzero sent count. `--hours N` to
   change the window size; default 24.

2. **Fetch Poplar sends (last 24h)**
   `python3 tools/fetch_poplar_status.py --days 1`
   → writes `.tmp/poplar_status.json`. `--days 1` is the 24h-window
   equivalent for Poplar's `start_date`/`end_date` filters.

3. **Group by client**
   `python3 tools/group_by_client.py`
   → reads both files above, matches each campaign that actually sent
   something to a client via `tools/client_roster.json`, and writes
   `.tmp/client_status.json` (per client: `iterable_sent` list,
   `poplar_sent` list — both empty if nothing sent). Quiet Poplar campaigns
   (zero mailings in the window) are never matched, so the printed
   **unmatched** list only ever contains genuine sends from out-of-roster
   clients or generic/test campaigns — expected, not an error (see "Client
   roster" above).

4. **Compose messages**
   `python3 tools/compose_messages.py`
   → reads `.tmp/client_status.json` + `tools/client_channels.json`, writes
   `.tmp/client_messages.json`: `{ client: { channel_id, channel_name,
   message } }`, one entry per client with activity (clients with nothing
   in the window are simply absent — no empty "nothing happened" message
   unless the user asks for one later). Formatting matches "Message format"
   above exactly; no judgment calls needed at post time.

5. **Post each composed message to Slack** via
   `mcp__claude_ai_Slack__slack_send_message` (`channel_id`, `message`),
   looping over `.tmp/client_messages.json`. If a client has activity but no
   entry in `tools/client_channels.json`, `compose_messages.py` already
   flagged it in its printed output — don't skip silently, surface it.

## Automation status
This workflow needs to run unattended at 10:00 AM IST, but Slack posting
goes through the MCP connector (interactive OAuth), and interactively
authenticated MCP connectors may not be available in headless/scheduled
agent runs.

Progress so far (2026-08-04):
- **Posting mechanics confirmed working** in a live interactive session — a
  test message was sent to `#dexcom-marketing` via
  `mcp__claude_ai_Slack__slack_send_message` and landed successfully
  ([message link](https://3tandai.slack.com/archives/C07465A2T2T/p1785839420562399)).
  This only proves the MCP connector works *interactively*, not that it
  survives a headless 10:00 AM cron run — that's still unverified.
- **The actual 10:00 AM IST schedule is on hold, per explicit instruction**
  (2026-08-04: "hold off... we'll work on that later") — don't set up
  `CronCreate`/the scheduling skill for this workflow until the user
  explicitly asks to resume that work. Until then, this workflow only runs
  when someone in a live session asks for it.
- When the schedule does get built: **test empirically** first — set it up,
  let it fire once, and confirm the Slack posts actually land before
  trusting it long-term. If posts start silently failing in the scheduled
  run, the fallback (flagged in CLAUDE.md, not yet built) is a real Slack
  bot token + `chat.postMessage` instead of the MCP tool — don't switch to
  that silently, raise it with the user first.

## Edge cases
- **Unmatched sends from `group_by_client.py`** — expected and fine as long
  as they're out-of-scope clients or generic/test campaigns (see "Client
  roster" above). Only escalate to the user if an unmatched name looks like
  a genuine naming variant of one of the 22 roster clients that the alias
  list is failing to catch (e.g. a new abbreviation) — that's a roster bug
  worth fixing, not something to ignore.
- **A client has zero sends across both sources today** — normal, not an
  error. Per the per-client posting model, just don't post to their channel
  that day (unless the user asks for an explicit "nothing sent today"
  message later).
- **API error from either tool** — the tool exits non-zero with a clear
  message (HTTP status + body). Don't silently skip affected clients; note
  which source failed for that run.
- **Poplar mailing `state` values seen so far**: `processing`, `production`,
  `mailed`, `delivered`, `delivery_exception`, `failed`, `append_failed`,
  `address_invalid`, `suppressed`, `budget_exceeded`,
  `credit_balance_exceeded`, `holdout`. The Slack message only ever surfaces
  `Total Sent` and the `delivered` count (per explicit instruction,
  2026-08-04 — "display this data, ignore the rest") — other states are
  still captured in `.tmp/poplar_status.json`'s `state_counts` for
  debugging, just not posted. Don't add failed/cost/other states back into
  the message without the user asking.
- **A postcard sent in the last 24h almost always shows `Delivered: 0`** —
  USPS transit takes several days, so same-day delivery confirmation is
  rare. Expected, not a bug; don't "fix" this by widening the delivery
  lookback window without checking with the user first, since `Total Sent`
  specifically means "sent in the last 24h."

## Known API quirks (learned the hard way — don't rediscover these)
- **Iterable auth**: `Api-Key: <key>` header (not Bearer).
- **Iterable campaign list**: `GET /api/campaigns` returns *every* campaign
  ever created (1149 in this account, most `Finished`/`Archived`) — no
  built-in "sent recently" filter. campaignState alone doesn't tell you
  whether something sent in a given window, since a one-time campaign
  finishes right after sending.
- **Iterable metrics endpoint**: `GET /api/campaigns/metrics` is what
  actually answers "did this send in this window." Quirks found by testing
  directly against the live API (docs alone didn't cover these):
  - `startDateTime`/`endDateTime` must be full ISO8601 **with a trailing
    `Z`** (e.g. `2026-08-03T00:00:00.000Z`) — a bare
    `2026-08-03T00:00:00` is rejected with a 400.
  - Multiple campaign IDs are **not** comma-separated — repeat the query
    param: `?campaignId=1&campaignId=2&campaignId=3`.
  - Response is CSV (`Content-Type: text/plain`), not JSON. Columns include
    `Total Email Sends` (and would include SMS/push equivalents for those
    mediums) — `tools/fetch_iterable_sent.py` sums any column matching
    `\bsent\b|\bsends\b` to get a medium-agnostic "sent" count.
  - `tools/fetch_iterable_sent.py` checks **all** campaigns each run rather
    than pre-filtering by state — simpler and correct; at ~1150 campaigns
    batched 200-per-call this takes well under a minute.
- **Open Rate / Click Rate**: the metrics endpoint doesn't return a
  precomputed percentage field — `aggregationType=rate` (tried empirically)
  has no effect. Iterable's own dashboard formula (confirmed via their
  Metric Definitions page) is **Unique X (filtered) / Unique Emails
  Delivered**, so `tools/fetch_iterable_sent.py` computes
  `open_rate_pct`/`click_rate_pct` itself from `Unique Email Opens
  (filtered)`, `Unique Email Clicks (filtered)`, and `Unique Emails
  Delivered` — verified against a real historical campaign (344/1213 →
  28.4%, matches). No open rate for SMS (no open-tracking pixel) — per
  explicit instruction (2026-08-04), omit that line for SMS rather than
  show "N/A". **SMS click-rate column names are unverified** — this account
  had no active SMS campaign to test against when this was written;
  `rates_for()` finds them defensively by substring match (`"sms"` +
  `"click"`/`"deliver"`). If a real SMS send ever produces a null
  click_rate_pct, check the raw `metrics` dict in `iterable_sent.json` for
  the actual column names and fix the substrings in
  `tools/fetch_iterable_sent.py`.
- **Poplar auth**: `Authorization: Bearer <token>` header.
- **Poplar has no "list all mailings" endpoint** — go
  `GET /v1/campaigns` (active campaigns, id+name only) →
  `GET /v1/campaign/:id/mailings` (paginated, filterable by
  `start_date`/`end_date`, `per_page` max 100) per campaign.
- **Poplar + Cloudflare**: requests with Python's default `urllib`
  User-Agent get blocked with `403` / `error code: 1010` (Cloudflare bot
  block), even with a valid token. Fix: send a normal browser-like
  `User-Agent` header (already done in `tools/fetch_poplar_status.py`).
- **Poplar read-only queries are free** — credits/cost only apply to
  actually triggering a mailing (`POST /v1/mailing`). The status-fetch tool
  never calls that endpoint, so it's safe to run anytime without checking
  in first.

## Output
The Slack messages are the deliverable. `.tmp/*.json` files are disposable
intermediates — no need to keep or reference them after posting.
