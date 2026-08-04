# Agent Instructions

You're working inside the **WAT framework** (Workflows, Agents, Tools). This architecture separates concerns so that probabilistic AI handles reasoning while deterministic code handles execution. That separation is what makes this system reliable.

## Project objective

Build an agent that reports send/campaign status to **Slack** for Digbi Health, pulling from two
sources:
- **Iterable** — which email/campaigns are currently launched/active, and their status.
- **Poplar** — the status of postcards/direct mail sent out.

## The WAT Architecture

**Layer 1: Workflows (The Instructions)**
- Markdown SOPs stored in `workflows/`
- Each workflow defines the objective, required inputs, which tools to use, expected outputs, and how to handle edge cases
- Written in plain language, the same way you'd brief someone on your team

**Layer 2: Agents (The Decision-Maker)**
- This is your role. You're responsible for intelligent coordination.
- Read the relevant workflow, run tools in the correct sequence, handle failures gracefully, and ask clarifying questions when needed
- You connect intent to execution without trying to do everything yourself
- Example: If you need campaign data from Iterable, don't call the API ad hoc. Read `workflows/post_campaign_status.md`, figure out the required inputs, then execute `tools/fetch_iterable_campaigns.py`

**Layer 3: Tools (The Execution)**
- Python scripts in `tools/` that do the actual work
- API calls, data transformations, file operations
- Credentials and API keys are stored in `.env`
- These scripts are consistent, testable, and fast

**Why this matters:** When AI tries to handle every step directly, accuracy drops fast. If each step is 90% accurate, you're down to 59% success after just five steps. By offloading execution to deterministic scripts, you stay focused on orchestration and decision-making where you excel.

## How to Operate

**1. Look for existing tools first**
Before building anything new, check `tools/` based on what your workflow requires. Only create new scripts when nothing exists for that task.

**2. Learn and adapt when things fail**
When you hit an error:
- Read the full error message and trace
- Fix the script and retest (if it uses paid API calls or credits, check with me before running again)
- Document what you learned in the workflow (rate limits, timing quirks, unexpected behavior)
- Example: You get rate-limited on the Iterable API, so you dig into the docs, discover a batch/campaigns endpoint, refactor the tool to use it, verify it works, then update the workflow so this never happens again

**3. Keep workflows current**
Workflows should evolve as you learn. When you find better methods, discover constraints, or encounter recurring issues, update the workflow. That said, don't create or overwrite workflows without asking unless I explicitly tell you to. These are your instructions and need to be preserved and refined, not tossed after one use.

## The Self-Improvement Loop

Every failure is a chance to make the system stronger:
1. Identify what broke
2. Fix the tool
3. Verify the fix works
4. Update the workflow with the new approach
5. Move on with a more robust system

This loop is how the framework improves over time.

## Integrations for this project

- **Iterable API** — key lives in `.env` as `ITERABLE_API_KEY` (reused from the sibling
  `Documents/Agentic workflows/.env` project, Digbi Health). Fetch campaign data with a
  deterministic tool in `tools/` (e.g. `tools/fetch_iterable_campaigns.py`) that hits the Iterable
  REST API directly — https://api.iterable.com/api/campaigns for the list, filter/format the
  active-campaign fields the workflow needs.
- **Poplar API** — key lives in `.env` as `POPLAR_API_KEY`. Deliberately a **separate key** from
  the one already in `Documents/Agentic workflows/.env` — not shared, scoped just to this agent.
  Fetch postcard/mail-send status with a deterministic tool (e.g.
  `tools/fetch_poplar_status.py`). Check Poplar's API docs for the actual send-status endpoint and
  auth scheme (header name, etc.) before assuming it matches Iterable's — don't guess.
- **Slack** — posting does **not** go through a bot token or webhook. It goes through the
  **Slack MCP server** (`mcp.slack.com`, surfaced in this environment as the `claude.ai Slack`
  connector — tools like `mcp__claude_ai_Slack__slack_send_message`). This was a deliberate choice:
  it reuses your existing authorized Slack connection instead of provisioning a new bot/app.

  **Consequence:** because the Slack MCP server authenticates via an interactive OAuth session,
  the "post to Slack" step can only run *inside a live Claude session* (this chat, Claude Desktop,
  or a scheduled Claude agent run) — not from a bare cron job with no LLM in the loop. So the
  actual shape of this project is:
  1. `tools/fetch_iterable_campaigns.py` — deterministic, can run anywhere, outputs campaign data
     (e.g. to `.tmp/campaigns.json`).
  2. The agent (you) reads that output, formats a status message, and calls
     `mcp__claude_ai_Slack__slack_send_message` to post it.

  If unattended, no-Claude-session automation becomes a requirement later, revisit: that needs a
  bot token + `chat.postMessage` instead of the MCP server — flag it to me rather than silently
  switching approaches.

## File Structure

**What goes where:**
- **Deliverables**: The Slack post itself is the deliverable — no need to duplicate output elsewhere unless asked
- **Intermediates**: Temporary processing files that can be regenerated

**Directory layout:**
```
.tmp/           # Temporary files (API responses, intermediate exports). Regenerated as needed.
tools/          # Python scripts for deterministic execution
workflows/      # Markdown SOPs defining what to do and how
.env            # API keys and environment variables (NEVER store secrets anywhere else)
```

**Core principle:** Local files are just for processing. Anything I need to see or use lives in Slack (or wherever we agree the deliverable belongs). Everything in `.tmp/` is disposable.

## Bottom Line

You sit between what I want (workflows) and what actually gets done (tools). Your job is to read instructions, make smart decisions, call the right tools, recover from errors, and keep improving the system as you go.

Stay pragmatic. Stay reliable. Keep learning.
