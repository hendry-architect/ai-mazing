#!/usr/bin/env bash
#
# The 3x/week unattended run: pick the next topic, run its pipeline through
# to whatever gate it has, and publish what needs no further human approve.
#
#   bash scripts/pcip-scheduled-post.sh           # draft only, always safe
#   PCIP_SCHEDULE_LIVE=1 bash scripts/pcip-scheduled-post.sh
#                                                  # publish live -- but only
#                                                  # the topics that never
#                                                  # touched medical_review
#
# What "completely automatic" means here, precisely: every pipeline step up
# to a gate runs with zero input. brand_review is safe to auto-approve --
# it is a design-fit check, never a clinical one -- and is turned on for
# every run this script makes (PCIP_AUTO_APPROVE_GATES=brand_review).
# medical_review is not, and cannot be: it is hard-coded NEVER_AUTO_APPROVE
# in pcip/pipelines/base.py, no environment variable reaches it, and a run
# that stops there is not a bug in this script -- it is the one thing in
# this whole pipeline that still needs a clinician, on purpose.
#
# So a scheduled run does one of three things:
#   - a non-clinical topic (marketing_asset) finishes end to end and is
#     published -- as a draft by default, live only with PCIP_SCHEDULE_LIVE=1
#   - a clinical topic (patient_education) reaches medical_review and stops;
#     this script logs it and leaves it for `pcip approve` — same as any
#     other run, nothing scheduled-specific about finishing it
#   - something fails outright (a credential, an API error); logged, and
#     the rotation still advances so one bad run does not jam the schedule
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

# brand_review only. medical_review is NEVER_AUTO_APPROVE in the code and
# cannot be added here even by mistake — this line does not reach it.
export PCIP_AUTO_APPROVE_GATES="brand_review"

NEXT_JSON="$("$PY" -m pcip.cli schedule-next 2>>"$LOG")"
if [ -z "$NEXT_JSON" ]; then
  log "no schedule entry — check examples/schedule/manifest.json"
  exit 1
fi
log "next: $NEXT_JSON"

PIPELINE="$(printf '%s' "$NEXT_JSON" | "$PY" -c 'import json,sys; print(json.load(sys.stdin)["pipeline"])')"
BRIEF="$(printf '%s' "$NEXT_JSON" | "$PY" -c 'import json,sys; print(json.load(sys.stdin)["brief_path"])')"
CLINICAL="$(printf '%s' "$NEXT_JSON" | "$PY" -c 'import json,sys; print(json.load(sys.stdin)["clinical"])')"

log "running: pcip run $PIPELINE --brief $BRIEF (clinical=$CLINICAL)"
RUN_JSON="$("$PY" -m pcip.cli run "$PIPELINE" --brief "$BRIEF" --quiet 2>>"$LOG")"
log "$RUN_JSON"

STATUS="$(printf '%s' "$RUN_JSON" | "$PY" -c 'import json,sys; print(json.load(sys.stdin).get("status",""))')"
RUN_ID="$(printf '%s' "$RUN_JSON" | "$PY" -c 'import json,sys; print(json.load(sys.stdin).get("run_id",""))')"

case "$STATUS" in
  awaiting_review)
    GATE="$(printf '%s' "$RUN_JSON" | "$PY" -c 'import json,sys; print(json.load(sys.stdin).get("awaiting_gate",""))')"
    log "PAUSED at $GATE — this needs a person: pcip approve $RUN_ID --gate $GATE --reviewer \"Dr. Pascual\""
    exit 0
    ;;
  awaiting_handoff)
    log "PAUSED on a handoff (imagery/assembly) — run: pcip resume"
    exit 0
    ;;
  failed)
    log "FAILED — see above. The rotation has already advanced; this brief will come up again next cycle."
    exit 1
    ;;
  done)
    log "reached done with no pending gate — assembling publish"
    ;;
  *)
    log "unexpected status: $STATUS"
    exit 1
    ;;
esac

# Only reachable when the run finished clean — which for patient_education
# is impossible (medical_review always stops it first), so this is always a
# non-clinical topic by construction, not by re-checking here.
LIVE_FLAG=""
[ "${PCIP_SCHEDULE_LIVE:-0}" = "1" ] && LIVE_FLAG="--live"
PUB_JSON="$("$PY" -m pcip.cli publish --channel wordpress $LIVE_FLAG 2>>"$LOG")"
log "$PUB_JSON"
if [ -n "$LIVE_FLAG" ]; then
  log "published LIVE."
else
  log "published as DRAFT — review and publish live, or re-run with PCIP_SCHEDULE_LIVE=1."
fi
