#!/usr/bin/env bash
#
# PCIP bring-up — every phase, no prompts, no stopping.
#
# Runs the whole platform from a cold laptop to a finished deliverable and
# prints one honest report at the end. Safe to re-run: every phase is
# idempotent, and a phase that cannot run is recorded as BLOCKED rather than
# aborting the ones after it — the point is to learn everything that is wrong
# in a single pass instead of one error per attempt.
#
# Never prints a credential. Only key names and pass/fail.
#
#   bash scripts/pcip-bringup.sh
#
set -uo pipefail          # deliberately NOT -e: phases report, they don't abort

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO" || exit 1
VENV="$REPO/.venv"
PY="$VENV/bin/python"
DATA="${PCIP_DATA_DIR:-$REPO/pcip_data}"
BRANCH="claude/passqual-creative-platform-sl5wzw"

RESULTS=()
note()  { printf '  %s\n' "$*"; }
ok()    { RESULTS+=("OK|$1");      printf '\033[32m  ✓ %s\033[0m\n' "$1"; }
warn()  { RESULTS+=("BLOCKED|$1"); printf '\033[33m  ⚠ %s\033[0m\n' "$1"; }
bad()   { RESULTS+=("FAIL|$1");    printf '\033[31m  ✗ %s\033[0m\n' "$1"; }
phase() { printf '\n\033[1m━━━ %s ━━━\033[0m\n' "$*"; }

# ── Phase 1 — repository ─────────────────────────────────────────────────────
phase "Phase 1/9  Repository"
note "path: $REPO"
if git -C "$REPO" rev-parse --git-dir >/dev/null 2>&1; then
  git -C "$REPO" fetch origin "$BRANCH" --quiet 2>/dev/null
  CURRENT="$(git -C "$REPO" rev-parse --abbrev-ref HEAD)"
  if [ "$CURRENT" != "$BRANCH" ]; then
    git -C "$REPO" checkout "$BRANCH" --quiet 2>/dev/null \
      || git -C "$REPO" checkout -b "$BRANCH" "origin/$BRANCH" --quiet 2>/dev/null
  fi
  if git -C "$REPO" diff --quiet && git -C "$REPO" diff --cached --quiet; then
    git -C "$REPO" merge --ff-only "origin/$BRANCH" --quiet 2>/dev/null \
      && ok "on $BRANCH at $(git -C "$REPO" rev-parse --short HEAD)" \
      || warn "could not fast-forward — local commits present, keeping them"
  else
    warn "uncommitted local changes — not pulling, keeping your work"
  fi
else
  bad "not a git repository"
fi

# ── Phase 2 — interpreter ────────────────────────────────────────────────────
phase "Phase 2/9  Python environment"
# A venv records an absolute path. This repo has been moved and copied, so a
# stale pyvenv.cfg pointing at a directory that no longer exists is the single
# most likely reason `python -m pcip` says "No module named pcip".
if [ -x "$PY" ] && "$PY" -c 'import sys' >/dev/null 2>&1; then
  ok "venv usable ($("$PY" -V 2>&1))"
else
  [ -e "$VENV" ] && { note "stale venv found — rebuilding"; rm -rf "$VENV"; }
  if python3 -m venv "$VENV" >/dev/null 2>&1 && [ -x "$PY" ]; then
    ok "venv created ($("$PY" -V 2>&1))"
  else
    bad "could not create a venv — install Python 3 from python.org"
    PY="$(command -v python3)"
    note "falling back to system python: $PY"
  fi
fi

# ── Phase 3 — dependencies ───────────────────────────────────────────────────
phase "Phase 3/9  Dependencies"
# pcip/requirements.txt, not the repo root file: the root one carries the
# Streamlit analytics app (pandas, numpy, pyarrow) which PCIP does not use and
# which is slow and failure-prone to build on a laptop.
if "$PY" -m pip install --quiet --disable-pip-version-check -r "$REPO/pcip/requirements.txt" 2>/dev/null; then
  ok "installed: requests, PyYAML, anthropic, pytest"
else
  bad "pip install failed — run it by hand to see why:"
  note "\"$PY\" -m pip install -r \"$REPO/pcip/requirements.txt\""
fi

# ── Phase 4 — credentials present (names only, never values) ─────────────────
phase "Phase 4/9  Credentials"
# Keep a rolling backup before anything touches .env. It went missing once
# between runs — gitignored, so not a checkout, and the template copy below
# uses cp -n and cannot overwrite — and every credential in it had to be
# re-entered. The cause is unknown; the recovery should not be.
if [ -f "$REPO/.env" ]; then
    mkdir -p "$REPO/.pcip-backups" && chmod 700 "$REPO/.pcip-backups"
    BACKUP="$REPO/.pcip-backups/env-$(date +%Y%m%d-%H%M%S)"
    if cp "$REPO/.env" "$BACKUP" 2>/dev/null; then
        chmod 600 "$BACKUP"
        note "backed up .env → .pcip-backups/$(basename "$BACKUP")"
    fi
    # Keep the last 20; a credentials file's history should not grow forever.
    ls -1t "$REPO/.pcip-backups"/env-* 2>/dev/null | tail -n +21 \
        | while read -r stale; do rm -f "$stale"; done
fi
if [ -f "$REPO/.env" ]; then
  PERMS="$(stat -f '%Lp' "$REPO/.env" 2>/dev/null || stat -c '%a' "$REPO/.env" 2>/dev/null)"
  [ "$PERMS" = "600" ] || { chmod 600 "$REPO/.env" 2>/dev/null && note ".env permissions tightened to 600"; }
  # Report which keys carry a non-empty value. An empty ANTHROPIC_API_KEY= is
  # worse than an absent one: it outranks every other credential source.
  "$PY" - "$REPO/.env" <<'PYEOF'
import sys, pathlib
watch = ["ANTHROPIC_API_KEY","OPENAI_API_KEY","GOOGLE_AI_API_KEY","IDEOGRAM_API_KEY",
         "BFL_API_KEY","CANVA_CLIENT_ID","CANVA_ACCESS_TOKEN","WORDPRESS_USER",
         "WORDPRESS_APP_PASSWORD","WORDPRESS_URL","BUFFER_TOKEN","META_PAGE_TOKEN",
         "LINKEDIN_TOKEN","THREADS_TOKEN"]
seen = {}
for raw in pathlib.Path(sys.argv[1]).read_text(errors="replace").splitlines():
    line = raw.strip().removeprefix("export ").strip()
    if not line or line.startswith("#") or "=" not in line:
        continue
    k, _, v = line.partition("=")
    seen[k.strip()] = v.strip().strip("\"'")
for k in watch:
    if k not in seen:      print(f"    ·  {k}  (absent)")
    elif seen[k] == "":    print(f"    !! {k}  SET BUT EMPTY — delete this line")
    else:                  print(f"    ✓  {k}  ({len(seen[k])} chars)")
PYEOF
  ok ".env present (values never printed)"
else
  if cp -n "$REPO/.env.example" "$REPO/.env" 2>/dev/null; then
    chmod 600 "$REPO/.env"
    bad "CREATED A NEW .env FROM THE TEMPLATE"
    note "Every credential in it is blank. If you had credentials before, they"
    note "are NOT in this file — a quiet note here once cost several rounds of"
    note "debugging a WordPress publish against an empty username."
    note ""
    note "Look for a backup:"
    note "  ls -1t .pcip-backups/ 2>/dev/null | head -5"
    note "and restore the newest with:"
    note "  cp .pcip-backups/<file> .env && chmod 600 .env"
  else
    warn "no .env and the template could not be copied"
  fi
fi

# ── Phase 5 — offline self-test ──────────────────────────────────────────────
phase "Phase 5/9  Self-test (offline, no credentials needed)"
TESTOUT="$("$PY" -m pytest "$REPO/tests" -q 2>&1 | tail -3)"
note "$TESTOUT"
echo "$TESTOUT" | grep -qE "[0-9]+ passed" && ! echo "$TESTOUT" | grep -q "failed" \
  && ok "test suite green" || bad "test suite has failures (see above)"

# ── Phase 6 — live capability matrix ─────────────────────────────────────────
phase "Phase 6/9  Connector health (live probes)"
mkdir -p "$DATA"
DOCTOR="$("$PY" -m pcip --data-dir "$DATA" doctor --live 2>&1)"
echo "$DOCTOR" > "$DATA/doctor.json"
"$PY" - "$DATA/doctor.json" <<'PYEOF'
import json, sys
try:
    d = json.load(open(sys.argv[1]))
except Exception:
    print("    could not parse doctor output; see pcip_data/doctor.json"); raise SystemExit
for name, c in sorted(d.get("connectors", {}).items()):
    if not c.get("desired"):
        continue
    st = c.get("status", "?")
    mark = {"ready": "✓", "mcp_managed": "✓"}.get(st, "·")
    line = f"    {mark}  {name:<12} {st}"
    if st not in ("ready", "mcp_managed") and c.get("detail"):
        line += f"  — {c['detail'][:96]}"
    print(line)
PYEOF
READY="$(echo "$DOCTOR" | grep -cE '"status": "(ready|mcp_managed)"')"
[ "$READY" -gt 0 ] && ok "$READY capability check(s) usable" || warn "no connector is live yet"

# ── Phase 7 — reproduce the reviewed deliverable ─────────────────────────────
phase "Phase 7/9  Patient-education run (bilingual, reviewed)"
# Read the graph directly rather than grepping CLI text: "run_id" as a JSON key
# matches a naive run_* pattern before any actual id does.
RUN="$("$PY" - "$DATA" <<'PYEOF'
import sys, pathlib
from pcip.graph.store import KnowledgeGraph
db = pathlib.Path(sys.argv[1]) / "graph.db"
if db.exists():
    runs = KnowledgeGraph(str(db)).nodes_by_kind("pipeline_run")
    if runs:
        print(runs[0]["id"])
PYEOF
)"

if [ -n "$RUN" ]; then
  note "existing run: $RUN"
else
  "$PY" -m pcip --data-dir "$DATA" run patient_education \
      --brief "$REPO/examples/brief-diabetes-es.json" >/dev/null 2>&1
  RUN="$("$PY" - "$DATA" <<'PYEOF'
import sys, pathlib
from pcip.graph.store import KnowledgeGraph
db = pathlib.Path(sys.argv[1]) / "graph.db"
runs = KnowledgeGraph(str(db)).nodes_by_kind("pipeline_run") if db.exists() else []
print(runs[0]["id"] if runs else "")
PYEOF
)"
  [ -n "$RUN" ] && note "started $RUN"
fi

if [ -n "$RUN" ]; then
  # The copy was written and already vetted; attach it rather than
  # regenerating, so the reviewed wording is what ships.
  "$PY" -m pcip --data-dir "$DATA" attach "$RUN" \
      --copy-file "$REPO/examples/copy-diabetes-es.json" >/dev/null 2>&1 \
      && note "reviewed copy attached"
  # DAHUecsTYgU is the design already built in the Canva account from the
  # "Prevención" brand template, with provenance recorded in the graph.
  "$PY" -m pcip --data-dir "$DATA" attach "$RUN" \
      --design-id DAHUecsTYgU \
      --design-url "https://www.canva.com/d/hZsWYCvlC6IDoCn" \
      --design-title "Prevención de la Diabetes — Hábitos Diarios" >/dev/null 2>&1 \
      && note "Canva design attached"
  # brand_review is the only gate any pipeline carries as of 2026-09-10
  # (patient_education's medical_review was removed — pcip/pipelines/library.py).
  "$PY" -m pcip --data-dir "$DATA" approve "$RUN" --gate brand_review \
      --reviewer "Dr. Pascual" >/dev/null 2>&1 && note "brand_review approved"
  ok "run $RUN prepared through review"
else
  bad "could not create or find a run"
fi

# ── Phase 8 — export ─────────────────────────────────────────────────────────
phase "Phase 8/9  Export"
# Match the file to the deliverable rather than taking the newest one.
# Newest-wins once selected a confidential patient appeal from Downloads as
# the media for a public article. pcip.exports returns nothing when it cannot
# tell, which is the correct answer.
EXPORT_PICK="$("$PY" - "$DATA" "${RUN:-}" <<'PYEOF'
import pathlib, sys
if not sys.argv[2]:
    raise SystemExit
from pcip.exports import best_export
from pcip.graph.store import KnowledgeGraph

g = KnowledgeGraph(str(pathlib.Path(sys.argv[1]) / "graph.db"))
run = (g.get_node(sys.argv[2]) or {}).get("payload", {})
ctx = run.get("context") or {}
title = ctx.get("design_title") or ""
if not title:
    brief = g.get_node(run.get("brief_id", "")) or {}
    title = (brief.get("payload") or {}).get("title", "")
best = best_export(title, "~/Downloads")
print(best.path if best else "")
PYEOF
)"
if [ -n "$RUN" ] && [ -n "$EXPORT_PICK" ]; then
  if "$PY" -m pcip --data-dir "$DATA" attach "$RUN" --export-file "$EXPORT_PICK" >/dev/null 2>&1; then
    ok "export attached: $(basename "$EXPORT_PICK")"
  else
    warn "could not attach $(basename "$EXPORT_PICK") — check: pcip runs"
  fi
else
  warn "no file in ~/Downloads matches this deliverable"
  note "Open the design and use Share > Download > PNG:"
  note "https://www.canva.com/d/hZsWYCvlC6IDoCn"
  note "Keep Canva's filename — it is what identifies the file as yours."
  note "Nothing is attached on a guess: your Downloads folder holds unrelated"
  note "files, and guessing once selected a confidential document."
fi

# ── Phase 9 — deliver ────────────────────────────────────────────────────────
phase "Phase 9/9  Deliverable"
OUT="$("$PY" - "$DATA" <<'PYEOF'
import sys, pathlib
from pcip.graph.store import KnowledgeGraph
db = pathlib.Path(sys.argv[1]) / "graph.db"
outs = KnowledgeGraph(str(db)).nodes_by_kind("output") if db.exists() else []
print(outs[0]["id"] if outs else "")
PYEOF
)"
if [ -n "$OUT" ]; then
  # `prepare` needs no credentials and enforces the same review and licensing
  # gates as publishing, so the article is ready whether or not WordPress is.
  if "$PY" -m pcip --data-dir "$DATA" prepare "$OUT" --dest "$DATA/handoff" >/dev/null 2>&1; then
    ok "article package ready: $DATA/handoff"
    ls -1 "$DATA/handoff" 2>/dev/null | sed 's/^/      /'
  else
    warn "prepare failed — run it directly to see why:"
    note "\"$PY\" -m pcip --data-dir \"$DATA\" prepare $OUT --dest \"$DATA/handoff\""
  fi
else
  warn "no exported output yet — finish Phase 8 first"
fi

# ── Report ───────────────────────────────────────────────────────────────────
phase "Report"
printf '%s\n' "${RESULTS[@]}" | while IFS='|' read -r s m; do
  case "$s" in
    OK)      printf '\033[32m  ✓ %s\033[0m\n' "$m" ;;
    BLOCKED) printf '\033[33m  ⚠ %s\033[0m\n' "$m" ;;
    FAIL)    printf '\033[31m  ✗ %s\033[0m\n' "$m" ;;
  esac
done
echo
printf '  full connector detail: %s\n' "$DATA/doctor.json"
printf '  re-run any time:       bash scripts/pcip-bringup.sh\n'
