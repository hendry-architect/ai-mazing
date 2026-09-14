#!/usr/bin/env bash
#
# The 3x/week unattended run, agent-driven: pick the next topic, run its
# pipeline start to finish — including fulfilling any Canva handoff with
# real Canva tools — and publish it. No human present, none needed.
#
#   bash scripts/pcip-scheduled-agent.sh           # draft only, always safe
#   PCIP_SCHEDULE_LIVE=1 bash scripts/pcip-scheduled-agent.sh
#                                                   # publish live
#
# Why this exists, replacing pcip-scheduled-post.sh (2026-09-13): that
# script forced PCIP_CANVA_MODE=connect so a plain bash job could finish
# without anyone to fulfil a Canva handoff — but Canva's Connect API
# autofill quota is a one-time trial that does not reset, and lifting it
# requires Canva Enterprise (30+ seats, sales-negotiated pricing — the
# wrong product for a solo practice). That path dead-ends after the trial
# is spent, which it was, the same night this was built.
#
# This script instead hands the whole run to `claude -p` — a real Claude
# Code agent, run non-interactively — which fulfils an `mcp` mode Canva
# handoff itself, the same way an interactive session already proved out
# live (two published articles, zero human intervention, 2026-09-12/13).
# No Canva quota is involved: this uses the same design/export tools an
# interactive Canva user has, not the gated Connect API.
#
# Requires the `claude` CLI logged into an account with Canva connected
# (confirm with: claude -p "list your mcp__*Canva*__ tools").
#
set -uo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO" || exit 1

# launchd's minimal environment doesn't have the PATH entries an
# interactive shell has — same reason pcip-scheduled-post.sh resolves its
# python by absolute path instead of trusting `python` to be found.
CLAUDE="$(command -v claude || true)"
for candidate in "$CLAUDE" "$HOME/.local/bin/claude" "/opt/homebrew/bin/claude" "/usr/local/bin/claude"; do
  if [ -n "$candidate" ] && [ -x "$candidate" ]; then
    CLAUDE="$candidate"
    break
  fi
done
if [ -z "${CLAUDE:-}" ] || [ ! -x "$CLAUDE" ]; then
  echo "error: could not find the claude CLI. Run 'which claude' and hardcode" \
       "the path into CLAUDE= above." >&2
  exit 1
fi

LOG_DIR="${PCIP_DATA_DIR:-$REPO/pcip_data}/schedule/logs"
mkdir -p "$LOG_DIR"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
LOG="$LOG_DIR/${STAMP}-agent.log"

if [ "${PCIP_SCHEDULE_LIVE:-0}" = "1" ]; then
  PUBLISH_INSTRUCTION="Publish it LIVE: \`.venv/bin/python -m pcip.cli publish <output_id> --channel wordpress --live\`"
else
  PUBLISH_INSTRUCTION="Publish it as a DRAFT (no --live flag) — this invocation did not set PCIP_SCHEDULE_LIVE=1."
fi

PROMPT="This is a scheduled, fully automated content run for PCIP (the PassQual Creative Intelligence Platform), for PassQual Health (Dr. Hendry Pascual). No human is watching this — complete it entirely on your own using your Canva MCP tools, or stop and clearly explain why not.

Repo: this checkout, at $REPO.

Do this, in order:

1. \`cd\` into the repo (you are already there). Run:
   \`.venv/bin/python -m pcip.cli schedule-next\`
   This tells you the next pipeline + brief_path in the 3x/week content rotation.

2. Run:
   \`export PCIP_AUTO_APPROVE_GATES=brand_review\`
   \`.venv/bin/python -m pcip.cli run <pipeline> --brief <brief_path>\`
   using the exact values from step 1. Do NOT set PCIP_CANVA_MODE — leave it
   unset so it defaults to \`mcp\` mode, which uses your own Canva tools
   rather than the Connect API (whose free autofill quota is a one-time
   trial that does not reset and requires Canva Enterprise to lift — never
   use PCIP_CANVA_MODE=connect).

3. If the run reaches status \`awaiting_handoff\` needing Canva assembly or
   export, fulfil it yourself with your own Canva tools:
   - Assembly: \`create-design-from-brand-template\` with the
     \`brand_template_id\` from the handoff JSON, then \`read-design\`
     (open_transaction: true) to see its text elements, then \`edit-design\`
     with \`replace_text\` operations to place the handoff's \`copy_fields\`
     (title/headline -> the headline-like field, a short excerpt or the
     first sentence of the caption -> body, the caption's own
     call-to-action after the arrow -> any cta field) — commit the
     transaction, then:
     \`.venv/bin/python -m pcip.cli attach <run_id> --design-id <id> --design-url <view_url>\`
   - Export: \`export-design\` (format png), then:
     \`.venv/bin/python -m pcip.cli attach <run_id> --export-url '<signed_url>'\`
     (try this first — it works as long as this machine's network can
     reach export-download.canva.com, which it can) or, if that ever
     fails, download the file yourself and use \`--export-file <path>\`
     instead.
   Repeat attach/resume until status is \`done\`.

4. Once \`done\`, run \`.venv/bin/python -m pcip.cli outputs\`, take the
   newest unpublished one, and: $PUBLISH_INSTRUCTION

5. If anything fails for a reason you can't fix yourself (missing/expired
   credentials, a genuine external outage, a persistent WordPress 5xx, a
   Canva quota error), stop and clearly state what happened and what
   Dr. Pascual needs to do — don't retry blindly. The rotation has already
   advanced past this brief regardless, so a failure here does not jam the
   schedule.

6. Finish with a short, concrete summary: the published title + URL (and
   whether it went live or stayed a draft), or exactly what blocked it and
   why."

echo "=== PCIP agent-driven scheduled run — $STAMP UTC ===" | tee -a "$LOG"
echo "claude: $CLAUDE" | tee -a "$LOG"
"$CLAUDE" -p "$PROMPT" --permission-mode bypassPermissions >>"$LOG" 2>&1
STATUS=$?
echo "=== claude exited $STATUS — see $LOG for the full run ===" | tee -a "$LOG"
exit "$STATUS"
