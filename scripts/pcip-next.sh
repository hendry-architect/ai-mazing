#!/usr/bin/env bash
#
# Show where the current run stands and do the next obvious thing.
#
#   bash scripts/pcip-next.sh            # report, and act where it is unambiguous
#   bash scripts/pcip-next.sh --show     # report only, change nothing
#
# Every instruction in this project that contained a <PLACEHOLDER> has cost a
# round, because a placeholder pasted literally is what the instruction said to
# do. This script looks the ids up instead, and where it cannot act on its own
# — a review gate is a human decision — it prints the exact command with the
# real id already filled in.
#
set -uo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO" || exit 1
PY="$REPO/.venv/bin/python"; [ -x "$PY" ] || PY="$(command -v python3)"
DATA="${PCIP_DATA_DIR:-$REPO/pcip_data}"
SHOW_ONLY=0
[ "${1:-}" = "--show" ] && SHOW_ONLY=1

# The design already built in the Canva account for this deliverable.
DESIGN_ID="DAHUecsTYgU"
DESIGN_URL="https://www.canva.com/d/hZsWYCvlC6IDoCn"
DESIGN_TITLE="Prevención de la Diabetes — Hábitos Diarios"

ok()   { printf '\033[32m  ✓ %s\033[0m\n' "$*"; }
warn() { printf '\033[33m  ⚠ %s\033[0m\n' "$*"; }
bad()  { printf '\033[31m  ✗ %s\033[0m\n' "$*"; }
info() { printf '    %s\n' "$*"; }
hdr()  { printf '\n\033[1m━━━ %s ━━━\033[0m\n' "$*"; }

hdr "Current run"
STATE="$("$PY" - "$DATA" <<'PYEOF'
import json, pathlib, sys
from pcip.graph.store import KnowledgeGraph
db = pathlib.Path(sys.argv[1]) / "graph.db"
if not db.exists():
    print("NONE||"); raise SystemExit
runs = KnowledgeGraph(str(db)).nodes_by_kind("pipeline_run", limit=50)
if not runs:
    print("NONE||"); raise SystemExit
waiting = [r for r in runs
           if (r["payload"].get("status") or "") in ("awaiting_handoff", "awaiting_review")]
run = (waiting or runs)[0]["payload"]
status = run.get("status", "?")
# What is it waiting ON?
need = ""
for step in run.get("steps", []):
    if step.get("status") in ("awaiting_handoff", "awaiting_review"):
        need = step.get("step", "")
        break
print(f"{run.get('id','')}|{status}|{need}")
for step in run.get("steps", []):
    print(f"STEP|{step.get('step')}|{step.get('status')}|{(step.get('detail') or '')[:96]}")
PYEOF
)"
LINE1="$(printf '%s' "$STATE" | head -1)"
RUN="$(printf '%s' "$LINE1" | cut -d'|' -f1)"
STATUS="$(printf '%s' "$LINE1" | cut -d'|' -f2)"
NEED="$(printf '%s' "$LINE1" | cut -d'|' -f3)"

if [ "$RUN" = "NONE" ] || [ -z "$RUN" ]; then
    bad "no pipeline run yet"
    info "Start one:"
    info "  python3 -m pcip --data-dir pcip_data run patient_education \\"
    info "      --brief examples/brief-diabetes-es.json"
    exit 0
fi
info "run:    $RUN"
info "status: $STATUS"
printf '%s\n' "$STATE" | grep '^STEP|' | while IFS='|' read -r _ name st detail; do
    case "$st" in
        done) mark="✓" ;;
        awaiting_review|awaiting_handoff) mark="→" ;;
        failed) mark="✗" ;;
        *) mark="·" ;;
    esac
    printf '      %s %-16s %-18s %s\n' "$mark" "$name" "$st" "$detail"
done

hdr "Next"
case "$STATUS::$NEED" in
    awaiting_handoff::assemble|awaiting_handoff::assembly)
        info "waiting for the Canva design"
        if [ "$SHOW_ONLY" = "1" ]; then
            info "  bash scripts/pcip-next.sh   # attaches design $DESIGN_ID"
        else
            "$PY" -m pcip --data-dir "$DATA" attach "$RUN" \
                --design-id "$DESIGN_ID" --design-url "$DESIGN_URL" \
                --design-title "$DESIGN_TITLE" >/dev/null 2>&1 \
                && ok "attached design $DESIGN_ID — re-run to see the next step" \
                || bad "could not attach the design"
        fi ;;
    awaiting_handoff::export)
        FILE="$(ls -t "$HOME/Downloads"/*.png "$HOME/Downloads"/*.pdf 2>/dev/null | head -1)"
        if [ -z "$FILE" ]; then
            warn "waiting for the exported file"
            info "Open the design and use Share → Download → PNG:"
            info "  $DESIGN_URL"
            info "Leave it in ~/Downloads and run this script again."
            info "(PNG, not PDF: the standard requires a hero image, and a PDF"
            info " cannot be a featured image.)"
        elif [ "$SHOW_ONLY" = "1" ]; then
            info "would attach: $(basename "$FILE")"
        else
            "$PY" -m pcip --data-dir "$DATA" attach "$RUN" --export-file "$FILE" >/dev/null 2>&1 \
                && ok "attached $(basename "$FILE")" || bad "could not attach $(basename "$FILE")"
        fi ;;
    awaiting_handoff::generate_copy)
        warn "waiting for copy, which means no copy provider is configured"
        info "PCIP pauses instead of inventing an article. Add the key and"
        info "re-run the pipeline so it writes to the PH standard:"
        info "  bash scripts/pcip-set-key.sh ANTHROPIC_API_KEY"
        info "  python3 -m pcip --data-dir pcip_data run patient_education \\"
        info "      --brief examples/brief-diabetes-es.json"
        info ""
        info "If the key IS set, a shell variable may be overriding it:"
        info "  unset ANTHROPIC_API_KEY && bash scripts/pcip-publish.sh" ;;
    awaiting_review::*)
        warn "waiting for YOUR review of: $NEED"
        info "This is a human decision and the script will not make it."
        info "Read the copy, then approve with the id already filled in:"
        info ""
        info "  python3 -m pcip --data-dir pcip_data approve $RUN \\"
        info "      --gate $NEED --reviewer \"Dr. Pascual\""
        info ""
        info "or reject it:"
        info "  python3 -m pcip --data-dir pcip_data reject $RUN \\"
        info "      --gate $NEED --reason \"...\"" ;;
    failed::*)
        bad "the run failed — see the step detail above"
        info "If it stopped at ph_standard, the copy is below the PassQual"
        info "Health article standard and the message lists every finding."
        info "Re-run the pipeline to regenerate:"
        info "  python3 -m pcip --data-dir pcip_data run patient_education \\"
        info "      --brief examples/brief-diabetes-es.json" ;;
    done::*)
        ok "run complete — ready to publish"
        info "  bash scripts/pcip-publish.sh          # draft"
        info "  bash scripts/pcip-publish.sh --live   # publish" ;;
    *)
        info "status '$STATUS' — nothing to do automatically" ;;
esac
printf '\n'
