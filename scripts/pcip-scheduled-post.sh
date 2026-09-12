#!/usr/bin/env bash
#
# The 3x/week unattended run: pick the next topic, run its pipeline start
# to finish, and publish it.
#
#   bash scripts/pcip-scheduled-post.sh           # draft only, always safe
#   PCIP_SCHEDULE_LIVE=1 bash scripts/pcip-scheduled-post.sh
#                                                  # publish live
#
# Every pipeline reaches `done` unattended now: medical_review was removed
# from patient_education on 2026-09-10, by explicit decision of Dr. Hendry
# Pascual, founder/CEO/medical director of PassQual Health — see
# pcip/pipelines/library.py for that change. brand_review is the only gate
# left anywhere, is a design-fit check rather than a clinical one, and this
# script auto-approves it on every run (PCIP_AUTO_APPROVE_GATES=brand_review).
#
# The Canva step defaults to `mcp` mode, which pauses for an interactive
# agent session to create/export the design by hand — exactly what a
# background launchd job cannot do. This script forces `connect` mode
# instead (PCIP_CANVA_MODE=connect, added 2026-09-12), which autofills the
# brand template through Canva's own API with no one watching. Requires
# CANVA_ACCESS_TOKEN/CANVA_REFRESH_TOKEN in .env (`pcip canva-auth`) and a
# brand template with autofill fields defined — both already true for the
# account's default template as of this date.
#
# So a scheduled run does one of two things:
#   - it reaches `done` and gets published — as a draft by default, live
#     only with PCIP_SCHEDULE_LIVE=1
#   - something stops it: expired/missing Canva credentials, a template
#     with no autofill fields, or another failure. Logged, and the rotation
#     still advances so one bad run does not jam the schedule — the brief
#     comes up again next cycle either way.
#
set -uo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO" || exit 1
PY="$REPO/.venv/bin/python"; [ -x "$PY" ] || PY="$(command -v python3)"
LOG_DIR="${PCIP_DATA_DIR:-$REPO/pcip_data}/schedule/logs"
mkdir -p "$LOG_DIR"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
LOG="$LOG_DIR/$STAMP.log"

log() { printf '%s\n' "$*" | tee -a "$LOG"; }

log "=== PCIP scheduled run — $STAMP UTC ==="

export PCIP_AUTO_APPROVE_GATES="brand_review"
export PCIP_CANVA_MODE="connect"

NEXT_JSON="$("$PY" -m pcip.cli schedule-next 2>>"$LOG")"
if [ -z "$NEXT_JSON" ]; then
  log "no schedule entry — check examples/schedule/manifest.json"
  exit 1
fi
log "next: $NEXT_JSON"

PIPELINE="$(printf '%s' "$NEXT_JSON" | "$PY" -c 'import json,sys; print(json.load(sys.stdin)["pipeline"])')"
BRIEF="$(printf '%s' "$NEXT_JSON" | "$PY" -c 'import json,sys; print(json.load(sys.stdin)["brief_path"])')"

log "running: pcip run $PIPELINE --brief $BRIEF"
RUN_JSON="$("$PY" -m pcip.cli run "$PIPELINE" --brief "$BRIEF" --quiet 2>>"$LOG")"
log "$RUN_JSON"

STATUS="$(printf '%s' "$RUN_JSON" | "$PY" -c 'import json,sys; print(json.load(sys.stdin).get("status",""))')"
RUN_ID="$(printf '%s' "$RUN_JSON" | "$PY" -c 'import json,sys; print(json.load(sys.stdin).get("run_id",""))')"

case "$STATUS" in
  awaiting_review)
    GATE="$(printf '%s' "$RUN_JSON" | "$PY" -c 'import json,sys; print(json.load(sys.stdin).get("awaiting_gate",""))')"
    log "PAUSED at $GATE — unexpected on an auto-approved gate; check pcip/cli.py's auto_approve_gates handling. In the meantime: pcip approve $RUN_ID --gate $GATE --reviewer \"Dr. Pascual\""
    exit 0
    ;;
  awaiting_handoff)
    log "PAUSED on a handoff (imagery/assembly) — usually a missing provider credential. Run: pcip resume"
    exit 0
    ;;
  failed)
    log "FAILED — see above. The rotation has already advanced; this brief will come up again next cycle."
    exit 1
    ;;
  done)
    log "reached done — publishing"
    ;;
  *)
    log "unexpected status: $STATUS"
    exit 1
    ;;
esac

LIVE_FLAG=""
[ "${PCIP_SCHEDULE_LIVE:-0}" = "1" ] && LIVE_FLAG="--live"
PUB_JSON="$("$PY" -m pcip.cli publish --channel wordpress $LIVE_FLAG 2>>"$LOG")"
log "$PUB_JSON"
if [ -n "$LIVE_FLAG" ]; then
  log "published LIVE."
else
  log "published as DRAFT — review and publish live, or re-run with PCIP_SCHEDULE_LIVE=1."
fi
