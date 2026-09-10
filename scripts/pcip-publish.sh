#!/usr/bin/env bash
#
# Publish the finished deliverable to WordPress.
#
#   bash scripts/pcip-publish.sh            # draft (safe, reversible)
#   bash scripts/pcip-publish.sh --live     # publish for real
#   bash scripts/pcip-publish.sh --replace  # retract what is live, publish this
#
# Finds the output itself, checks credentials before touching the network,
# publishes, and — when live — verifies the article actually resolves on the
# public site and records the publication in the knowledge graph.
#
# No arguments to memorise and no shell quoting to get wrong: every id and URL
# is looked up rather than pasted.
#
set -uo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO" || exit 1
PY="$REPO/.venv/bin/python"; [ -x "$PY" ] || PY="$(command -v python3)"
DATA="${PCIP_DATA_DIR:-$REPO/pcip_data}"
LIVE=0
REPLACE=0
case "${1:-}" in
    --live)    LIVE=1 ;;
    # Retract what is live and publish this in its place, in one step.
    # Splitting it into "retract, then publish" meant the retract got skipped
    # and the duplicate guard blocked the publish — correctly, and uselessly.
    --replace) LIVE=1; REPLACE=1 ;;
esac

ok()   { printf '\033[32m  ✓ %s\033[0m\n' "$*"; }
bad()  { printf '\033[31m  ✗ %s\033[0m\n' "$*"; }
warn() { printf '\033[33m  ⚠ %s\033[0m\n' "$*"; }
info() { printf '    %s\n' "$*"; }
hdr()  { printf '\n\033[1m━━━ %s ━━━\033[0m\n' "$*"; }

# ── 1. Credentials ───────────────────────────────────────────────────────────
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

hdr "1/5  Credentials"
MISSING="$("$PY" - <<'PYEOF'
from pcip.config import load_config
cfg = load_config()
missing = [n for n, v in (("WORDPRESS_USER", cfg.wordpress_user),
                          ("WORDPRESS_APP_PASSWORD", cfg.wordpress_app_password))
           if not v]
print(" ".join(missing))
PYEOF
)"
if [ -n "$MISSING" ]; then
    bad "not set: $MISSING"
    info ""
    info "Where each key actually stands (no values shown):"
    "$PY" - <<'PYEOF' || true
import os, pathlib

from pcip.config import _REPO_ROOT

files = [p for p in (pathlib.Path.cwd() / ".env", _REPO_ROOT / ".env")
         if p.is_file()]
seen = {str(p) for p in files}
print(f"      .env files found: {', '.join(seen) or 'NONE'}")

for key in ("WORDPRESS_USER", "WORDPRESS_APP_PASSWORD"):
    shell = os.environ.get(key)
    in_file = []
    for f in files:
        for raw in f.read_text(errors="replace").splitlines():
            line = raw.strip().removeprefix("export ").strip()
            if line.startswith(f"{key}=") or line.startswith(f"{key} ="):
                in_file.append(len(line.split("=", 1)[1].strip().strip("\"'")))
    if shell is None:
        shell_state = "not in the shell environment"
    elif shell == "":
        shell_state = "EXPORTED AS EMPTY in this shell — this shadows the file"
    else:
        shell_state = f"exported in this shell ({len(shell)} chars)"
    if not in_file:
        file_state = "absent from .env"
    elif all(n == 0 for n in in_file):
        file_state = f"in .env but EMPTY ({len(in_file)} line(s))"
    else:
        file_state = f"in .env, {max(in_file)} chars ({len(in_file)} line(s))"
    print(f"      {key}:")
    print(f"        file  : {file_state}")
    print(f"        shell : {shell_state}")
PYEOF
    info ""
    info "If a key shows EXPORTED AS EMPTY, that shell variable is the problem."
    info "Clear it and re-run — no need to re-enter anything:"
    info "    unset WORDPRESS_USER WORDPRESS_APP_PASSWORD"
    info "    bash scripts/pcip-publish.sh"
    info ""
    info "If a key is absent from .env, add it:"
    for KEY in $MISSING; do
        info "    bash scripts/pcip-set-key.sh $KEY"
    done
    info ""
    info "The Application Password comes from:"
    info "  https://wp.passqual.com/wp-admin/profile.php  →  Application Passwords"
    info "Keep its spaces exactly as WordPress shows them."
    exit 1
fi
ok "WordPress credentials present"

# ── 2. The deliverable ───────────────────────────────────────────────────────
hdr "2/5  Deliverable"
OUT="$("$PY" - "$DATA" <<'PYEOF'
import sys, pathlib
from pcip.graph.store import KnowledgeGraph
db = pathlib.Path(sys.argv[1]) / "graph.db"
outs = KnowledgeGraph(str(db)).nodes_by_kind("output") if db.exists() else []
print(outs[0]["id"] if outs else "")
PYEOF
)"
if [ -z "$OUT" ]; then
    bad "no exported output found in $DATA"
    info "Run the pipeline first:  bash scripts/pcip-bringup.sh"
    exit 1
fi
# Is a newer run still in flight? Publishing here would ship the previous
# run's deliverable while the one being reviewed is unfinished — which is
# exactly what happened: a completed PDF from an earlier run was selected
# while the current run sat at a review gate with nothing exported.
INFLIGHT="$("$PY" - "$DATA" "$OUT" <<'PYEOF'
import pathlib, sys
from pcip.graph.store import KnowledgeGraph
data, out_id = sys.argv[1], sys.argv[2]
g = KnowledgeGraph(str(pathlib.Path(data) / "graph.db"))
runs = g.nodes_by_kind("pipeline_run", limit=50)
waiting = [r for r in runs
           if (r["payload"].get("status") or "") in ("awaiting_review",
                                                     "awaiting_handoff")]
if not waiting:
    raise SystemExit
run = waiting[0]["payload"]
# Does that run already own this output? Then it is not stale.
produced = {dst for _, dst in g.neighbors(run["id"], "produced")}
if out_id in produced:
    raise SystemExit
step = next((s.get("step") for s in run.get("steps", [])
             if s.get("status") in ("awaiting_review", "awaiting_handoff")), "?")
print(f"{run['id']}|{run.get('status')}|{step}")
PYEOF
)"
if [ -n "$INFLIGHT" ]; then
    R="$(printf '%s' "$INFLIGHT" | cut -d'|' -f1)"
    ST="$(printf '%s' "$INFLIGHT" | cut -d'|' -f2)"
    STEP="$(printf '%s' "$INFLIGHT" | cut -d'|' -f3)"
    bad "a newer run is still in progress — refusing to publish an older deliverable"
    info "run $R is $ST at: $STEP"
    info "The output above ($OUT) came from an EARLIER run. Publishing it now"
    info "would ship the previous version while the new one is unfinished."
    info ""
    info "Finish the current run first:"
    info "  bash scripts/pcip-next.sh"
    exit 1
fi
ok "output: $OUT"
"$PY" - "$DATA" "$OUT" <<'PYEOF'
import sys, pathlib
from pcip.graph.store import KnowledgeGraph
g = KnowledgeGraph(str(pathlib.Path(sys.argv[1]) / "graph.db"))
n = g.get_node(sys.argv[2]) or {}
p = n.get("payload", {})
print(f"    title : {p.get('name','?')}")
print(f"    file  : {p.get('local_path','(none)')}")
PYEOF

# ── 3. Publish ───────────────────────────────────────────────────────────────
if [ "$LIVE" = "1" ]; then
    hdr "3/5  Publishing LIVE"
    warn "this publishes to the public site"
else
    hdr "3/5  Publishing as DRAFT"
    info "nothing becomes public; re-run with --live when it looks right"
fi

# Print the resolved target before sending. Three rounds were lost to
# inferring where the request went from the error it came back with.
"$PY" - <<'PYEOF'
from pcip.config import env_shadowing, load_config

shadowed = env_shadowing()
cfg = load_config()
print(f"    origin      : {cfg.wordpress_url}")
print(f"    REST base   : {cfg.wordpress_url}/wp-json/wp/v2")
print(f"    public site : {cfg.wordpress_public_site}")
print(f"    transport   : {cfg.wordpress_transport}")
if shadowed:
    print()
    print("    \033[33m⚠ these are exported in your shell and OVERRIDE .env:\033[0m")
    for key, (shell_len, file_len) in sorted(shadowed.items()):
        print(f"        {key}: shell {shell_len} chars, .env {file_len} chars")
    print("    If the values above look wrong, that is why. Clear them:")
    print("        unset " + " ".join(sorted(shadowed)))
PYEOF

if [ "$REPLACE" = "1" ]; then
    info ""
    info "--replace: retracting what is currently live for this output first"
    RET="$("$PY" -m pcip --data-dir "$DATA" retract "$OUT" \
           --reason "replaced by a new publish" 2>&1)"
    RET_STATUS=$?
    COUNT="$(printf '%s' "$RET" | grep -c '"status": "retracted"' || true)"
    if [ "$RET_STATUS" -ne 0 ]; then
        # A failed retract must stop here. Continuing publishes a second copy
        # beside the one that was meant to be withdrawn, and the duplicate
        # guard then reports that as the problem — which it is not.
        bad "retract failed — not publishing"
        printf '%s\n' "$RET" | sed 's/^/    /'
        exit 1
    fi
    if [ "${COUNT:-0}" -gt 0 ]; then
        ok "retracted $COUNT existing post(s) — their slugs are free again"
    elif printf '%s' "$RET" | grep -q "nothing published"; then
        info "nothing was live for this output; publishing fresh"
    else
        bad "retract returned nothing recognisable — not publishing"
        printf '%s\n' "$RET" | sed 's/^/    /'
        exit 1
    fi
    printf '\n'
fi

ARGS=(-m pcip --data-dir "$DATA" publish "$OUT" --channel wordpress)
[ "$LIVE" = "1" ] && ARGS+=(--live)

RESULT="$("$PY" "${ARGS[@]}" 2>&1)"
STATUS=$?
printf '%s\n' "$RESULT" | sed 's/^/    /'
if [ $STATUS -ne 0 ]; then
    bad "publish failed — see the message above"
    # Match on what the failure actually was. An earlier version matched "403"
    # anywhere, which fired on a proxy error and told the operator to re-enter
    # a password that was never the problem — a confident wrong hint is worse
    # than none.
    case "$RESULT" in
        *"Application Password"*|*"XML-RPC fault 403"*)
            info "The site rejected the credentials. Re-add the Application"
            info "Password, keeping its spaces exactly as WordPress shows them:"
            info "  bash scripts/pcip-set-key.sh WORDPRESS_APP_PASSWORD" ;;
        *"XML-RPC"*disabled*|*"does not expose"*)
            info "XML-RPC looks disabled. Check Wordfence:"
            info "  Wordfence → All Options → search 'XML-RPC'" ;;
        *WORDPRESS_URL*|*"never reached the REST API"*)
            info "WORDPRESS_URL is pointing at the wrong host. Set it to the"
            info "WordPress origin, not the reader-facing site:"
            info "  bash scripts/pcip-set-key.sh WORDPRESS_URL"
            info "  (value: https://wp.passqual.com)" ;;
        *ProxyError*|*"Max retries exceeded"*|*"Connection refused"*|*Timeout*)
            info "This is a network failure reaching the site, not an"
            info "authentication problem. Check your connection and retry." ;;
        *rest_not_logged_in*|*"Authorization header"*)
            info "REST cannot authenticate on this host, and the XML-RPC"
            info "fallback did not take over. Confirm XML-RPC is enabled:"
            info "  bash scripts/pcip-site-audit.sh wp.passqual.com" ;;
    esac
    exit 1
fi
TRANSPORT="$(printf '%s' "$RESULT" | sed -n 's/.*"transport": *"\([a-z]*\)".*/\1/p' | head -1)"
ok "published via ${TRANSPORT:-unknown} transport"

# ── 4. Verify ────────────────────────────────────────────────────────────────
hdr "4/5  Verify"
URL="$(printf '%s' "$RESULT" | sed -n 's/.*"url": *"\([^"]*\)".*/\1/p' | head -1)"
if [ "$LIVE" != "1" ]; then
    info "draft — nothing to verify publicly yet"
    info "review it at https://wp.passqual.com/wp-admin/edit.php"
elif [ -z "$URL" ]; then
    warn "no public URL in the response"
else
    info "waiting for the public site to pick it up (ISR, ~60s)…"
    CODE=000
    for _ in 1 2 3 4 5 6 7 8; do
        CODE="$(curl -sS -m 15 -o /dev/null -w '%{http_code}' "$URL" 2>/dev/null || echo 000)"
        [ "$CODE" = "200" ] && break
        sleep 10
    done
    if [ "$CODE" = "200" ]; then
        ok "LIVE: $URL"
    else
        warn "$URL returned HTTP $CODE"
        info "The post may still be publishing, or the slug may differ."
        info "Check https://wp.passqual.com/wp-admin/edit.php"
    fi
fi

# ── 5. Record ────────────────────────────────────────────────────────────────
hdr "5/5  Distribution record"
"$PY" - "$DATA" "$OUT" <<'PYEOF'
import sys, pathlib
from pcip.config import load_config
from pcip.graph.store import KnowledgeGraph
from pcip.publish.router import PublishRouter
cfg = load_config()
g = KnowledgeGraph(str(pathlib.Path(sys.argv[1]) / "graph.db"))
for pub in PublishRouter(cfg, g).where_did_it_go(sys.argv[2]):
    where = pub.get("url") or pub.get("external_id") or "?"
    how = (pub.get("metadata") or {}).get("transport", "?")
    print(f"    {pub['channel']:<10} {pub['status']:<10} via {how:<7} {where}")
PYEOF
printf '\n'
