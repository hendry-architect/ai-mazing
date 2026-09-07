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

# Running from another branch means running PCIP without the fixes on this
# one, and the symptom is a bug that was already fixed reappearing. Cheap to
# detect, confusing to debug.
PCIP_BRANCH="claude/passqual-creative-platform-sl5wzw"
CUR_BRANCH="$(git -C "$REPO" rev-parse --abbrev-ref HEAD 2>/dev/null || echo "")"
if [ -n "$CUR_BRANCH" ] && [ "$CUR_BRANCH" != "$PCIP_BRANCH" ]; then
    printf '\033[33m  ⚠ on branch "%s", not "%s"\033[0m\n' "$CUR_BRANCH" "$PCIP_BRANCH"
    printf '    You may be running an older version of PCIP. Switch with:\n'
    printf '      git checkout %s && git pull origin %s\n\n' "$PCIP_BRANCH" "$PCIP_BRANCH"
fi

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
    detail = (step.get("detail") or "").replace("\n", "⏎")
    if step.get("status") != "failed":
        detail = detail[:96]
    print(f"STEP|{step.get('step')}|{step.get('status')}|{detail}")
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
        # A review gate you cannot read is not a review. Render the article to
        # a file and point at it, rather than asking for approval of something
        # that has only ever existed as a JSON field.
        REVIEWFILE="$("$PY" - "$DATA" "$RUN" "$NEED" <<'PYEOF'
import html, pathlib, sys
from pcip.graph.store import KnowledgeGraph
from pcip.annotations import find_review_annotations

data, run_id, gate = sys.argv[1], sys.argv[2], sys.argv[3]
g = KnowledgeGraph(str(pathlib.Path(data) / "graph.db"))
run = (g.get_node(run_id) or {}).get("payload", {})
fields = (run.get("context") or {}).get("copy_fields") or {}
bodies = fields.get("bodies") or {}
if not bodies and fields.get("body_html"):
    bodies = {"es": fields["body_html"]}
titles = fields.get("titles") or {}

notes = []
for body in bodies.values():
    notes.extend(find_review_annotations(body))

out = pathlib.Path(data) / "review"
out.mkdir(parents=True, exist_ok=True)
path = out / f"{run_id}-{gate}.html"

parts = [
    "<meta charset='utf-8'>",
    "<style>body{font:16px/1.6 -apple-system,system-ui,sans-serif;"
    "max-width:44rem;margin:3rem auto;padding:0 1.5rem;color:#14181F}"
    "h1{font-size:1.5rem}h2{font-size:1.15rem;margin-top:2rem}"
    ".note{background:#FDF3D8;border-left:4px solid #F4B41C;padding:.75rem 1rem;"
    "margin:1rem 0;border-radius:4px}"
    ".meta{color:#667;font-size:.9rem}hr{margin:3rem 0;border:0;"
    "border-top:1px solid #ddd}</style>",
    f"<p class='meta'>Run {html.escape(run_id)} &middot; gate: "
    f"<strong>{html.escape(gate)}</strong></p>",
]
if notes:
    parts.append(f"<div class='note'><strong>{len(notes)} item(s) flagged for "
                 "clinician sign-off.</strong> These are removed from the "
                 "published article and kept in the audit trail — read them "
                 "before approving:<ul>")
    for n in notes:
        parts.append(f"<li>{html.escape(n)}</li>")
    parts.append("</ul></div>")

meta_t = fields.get("meta_title", "")
meta_d = fields.get("meta_description", "")
if meta_t or meta_d:
    parts.append(f"<p class='meta'>SEO title: {html.escape(meta_t)}<br>"
                 f"Meta description: {html.escape(meta_d)}</p>")

for lang, body in bodies.items():
    parts.append("<hr>")
    parts.append(f"<p class='meta'>{lang.upper()} &middot; "
                 f"{len(body.split())} words</p>")
    parts.append(f"<h1>{html.escape(titles.get(lang, ''))}</h1>")
    parts.append(body)

faq = fields.get("faq") or []
if faq:
    parts.append("<hr><h2>FAQ</h2>")
    for item in faq:
        parts.append(f"<p><strong>{html.escape(str(item.get('q','')))}</strong><br>"
                     f"{html.escape(str(item.get('a','')))}</p>")

path.write_text("\n".join(parts), encoding="utf-8")
print(path)
PYEOF
)"
        if [ -n "$REVIEWFILE" ] && [ -f "$REVIEWFILE" ]; then
            info ""
            info "Read it first — this opens in your browser:"
            info "  open \"$REVIEWFILE\""
            if [ "$SHOW_ONLY" != "1" ] && command -v open >/dev/null 2>&1; then
                open "$REVIEWFILE" >/dev/null 2>&1 && ok "opened the article for review"
            fi
        fi
        info ""
        info "This is a human decision and the script will not make it."
        info "When you have read it, approve with the id already filled in:"
        info ""
        info "  python3 -m pcip --data-dir pcip_data approve $RUN \\"
        info "      --gate $NEED --reviewer \"Dr. Pascual\""
        info ""
        info "or reject it:"
        info "  python3 -m pcip --data-dir pcip_data reject $RUN \\"
        info "      --gate $NEED --reason \"...\"" ;;
    failed::*)
        bad "the run failed"
        # Print the failure in full. Truncating it hides the only actionable
        # content the step produced.
        "$PY" - "$DATA" "$RUN" <<'PYEOF'
import pathlib, sys, textwrap
from pcip.graph.store import KnowledgeGraph
g = KnowledgeGraph(str(pathlib.Path(sys.argv[1]) / "graph.db"))
run = (g.get_node(sys.argv[2]) or {}).get("payload", {})
for step in run.get("steps", []):
    if step.get("status") != "failed":
        continue
    print(f"\n    why {step.get('step')} failed:\n")
    for line in (step.get("detail") or "").splitlines():
        print("      " + line if line.strip() else "")

    # What did the copy step actually produce? A standard failure is usually
    # a shape problem, and the field inventory says which.
    fields = (run.get("context") or {}).get("copy_fields") or {}
    if fields:
        print("\n    what the copy step produced:")
        bodies = fields.get("bodies") or {}
        if bodies:
            for lang, body in bodies.items():
                words = len(body.split())
                print(f"      bodies[{lang}]: {words} words")
        else:
            print("      bodies: EMPTY — the model did not return the")
            print("              bilingual shape, so everything fell back")
        legacy = fields.get("body_html") or ""
        if legacy:
            print(f"      body_html (legacy single-language): {len(legacy.split())} words")
        for key in ("meta_title", "meta_description"):
            val = fields.get(key) or ""
            print(f"      {key}: {len(val)} chars" if val else f"      {key}: MISSING")
        print(f"      faq: {len(fields.get('faq') or [])} item(s)")
        print(f"      titles: {sorted((fields.get('titles') or {}).keys()) or 'MISSING'}")
    break
PYEOF
        printf '\n'
        info "Re-run to regenerate:"
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
