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

5. **Post each composed message to Slack.** Two paths depending on context —
   see "Automation" below for which to use when:
   - **Live/manual session**: `mcp__claude_ai_Slack__slack_send_message`
     (`channel_id`, `message`), looping over `.tmp/client_messages.json`.
   - **Unattended (local cron)**: `python3 tools/post_to_slack.py` — same
     input file, posts via a Slack bot token instead of MCP.

   Either path: if a client has activity but no entry in
   `tools/client_channels.json`, `compose_messages.py` already flagged it in
   its printed output — don't skip silently, surface it.

## Automation
**Decided 2026-08-04: local cron (`launchd`), not a cloud routine.** A cloud
routine (`RemoteTrigger`/the scheduling skill) was attempted first but hit
two blockers: this project wasn't a hosted git repo a cloud sandbox could
clone, and there was no confirmed way to get `ITERABLE_API_KEY`/
`POPLAR_API_KEY` into that sandbox without committing them somewhere (never
acceptable). Local cron sidesteps both — it runs directly on this Mac,
against the existing `.env`.

**The catch this created**: Slack MCP only works inside a live Claude
session, and a bare `launchd` job has no LLM/session in the loop at all. So
the unattended path needed a real fallback — exactly the one flagged (but
not yet built) earlier in this project: a **Slack bot token +
`chat.postMessage`**, via `tools/post_to_slack.py`, used *only* for the
unattended cron path. Live/manual runs in a Claude session still use the
MCP tool as before (confirmed working via a test post to
`#dexcom-marketing`,
[message link](https://3tandai.slack.com/archives/C07465A2T2T/p1785839420562399)).

**Setup pieces:**
- `tools/run_daily.sh` — chains all 5 steps above (uses the absolute
  Python path `/opt/homebrew/bin/python3`, since `launchd` doesn't run
  under a login shell with the normal `PATH`). Logs both stdout/stderr to
  `.tmp/run.log` (append-only — no LLM is around to surface failures, so
  check this file if a day's post seems to be missing).
- `~/Library/LaunchAgents/com.digbihealth.campaign-status-agent.plist` —
  `StartCalendarInterval` Hour=10 Minute=0. This Mac's system timezone is
  already `Asia/Kolkata`, confirmed via `/etc/localtime`, so no UTC
  conversion was needed. Loaded via
  `launchctl bootstrap gui/<uid> <plist path>`. If it ever needs
  reloading: `launchctl bootout gui/<uid>/com.digbihealth.campaign-status-agent`
  then bootstrap again.
- **`SLACK_BOT_TOKEN` in `.env`** — a bot token (`xoxb-...`) from the
  "Campaign Status Agent" Slack app (bot user: `campaign_status_agent`).
  Created 2026-08-05 with scopes `commands, chat:write, app_mentions:read,
  channels:read, groups:read` (the last two added after the app was first
  installed, which required a reinstall to take effect — a plain scope
  edit in the app config does *not* update a token already issued).
- **The bot has been individually invited into all 22 of the 22 client
  channels** (`/invite @campaign_status_agent` in each), confirmed
  2026-08-05 via `conversations.info` per channel (`is_member: true` for
  all). Slack requires bot membership to post into private channels, and
  per `slack_search_channels` results from earlier, these are almost all
  private — for a private channel the bot hasn't joined,
  `conversations.info` returns `channel_not_found` (not `not_in_channel`),
  since Slack hides private-channel existence from non-members entirely.
  `tools/post_to_slack.py` still reports `not_in_channel` per-client
  rather than aborting the whole run if a channel is ever missed after a
  future roster addition, so one not-yet-invited channel won't block the
  others from posting.
- The local git repo initialized earlier (for the abandoned cloud-routine
  attempt, intended for `https://github.com/harshal09-458/Campaign-Status-Agent`)
  is no longer required for automation to work, since local cron doesn't
  need a hosted repo at all. It's still there as plain local version
  control if wanted, but the stalled push (blocked on a GitHub account
  mismatch) is no longer a blocker for anything.

**Confirmed 2026-08-05**: full manual pipeline run, all 5 steps, using
`tools/post_to_slack.py` (bot token, not MCP) for the post step — 5/22
clients had activity in the window and all 5 posted successfully
(City of Fort Worth, Elbit, Dexter, AZLGEBT, RAGHT). This was a real run
against live Iterable/Poplar data, not a placeholder test.

**Not yet done**: a live end-to-end test of a real cron firing (current
verification only covers manual invocation of the steps/`run_daily.sh`,
not `launchd` actually firing it unattended at 10:00 AM).

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
