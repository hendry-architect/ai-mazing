#!/usr/bin/env bash
#
# Put one credential into .env safely.
#
#   bash scripts/pcip-set-key.sh ANTHROPIC_API_KEY
#
# Reads the value without echoing it, so the secret never appears on screen or
# in shell history. Replaces any existing line for that key rather than
# appending a second one, and refuses an empty value — an empty
# ANTHROPIC_API_KEY= is worse than an absent one, because it outranks every
# other credential source and produces an authentication error that looks
# nothing like "you left this blank".
#
set -uo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENVFILE="$REPO/.env"
KEY="${1:-}"

if [ -z "$KEY" ]; then
  echo "usage: bash scripts/pcip-set-key.sh <KEY_NAME>"
  echo
  echo "common key names:"
  echo "  ANTHROPIC_API_KEY        copy generation (required)"
  echo "  OPENAI_API_KEY           image generation"
  echo "  GOOGLE_AI_API_KEY        Imagen / Veo"
  echo "  WORDPRESS_USER           your WordPress login on wp.passqual.com"
  echo "  WORDPRESS_APP_PASSWORD   Application Password (not your login password)"
  exit 1
fi

case "$KEY" in
  [A-Z_]*) : ;;
  *) echo "error: '$KEY' is not a valid environment variable name"; exit 1 ;;
esac

[ -f "$ENVFILE" ] || { touch "$ENVFILE"; echo "created $ENVFILE"; }
chmod 600 "$ENVFILE"

printf 'Paste the value for %s (it will not be shown), then press Return: ' "$KEY"
VALUE=""
# Read from the terminal so a redirected stdin cannot silently supply the
# value, but fall back to stdin where there is no controlling terminal (CI, a
# container, `bash script < file`) instead of failing with an unbound variable.
# `[ -r /dev/tty ]` tests the node, not whether it can be opened — it passes
# inside a container with no controlling terminal. Actually try the open.
if : < /dev/tty 2>/dev/null; then
  IFS= read -rs VALUE < /dev/tty || true
else
  IFS= read -rs VALUE || true
fi
echo

# Trim whitespace a paste often carries; a stray newline or space silently
# corrupts a token in ways that are painful to diagnose later.
VALUE="$(printf '%s' "$VALUE" | tr -d '\r\n' | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')"

if [ -z "$VALUE" ]; then
  echo "nothing pasted — $ENVFILE was not changed"
  exit 1
fi

# Rewrite in Python rather than grep. The previous version used BRE with \+
# and \?, which GNU grep accepts and the BSD grep shipped with macOS does not
# — so on a Mac it removed nothing, the old line survived, and the new value
# was merely appended below it. Combined with a loader that took the first
# occurrence, a key that had just been saved read back as unset.
REMOVED="$(KEY="$KEY" VALUE="$VALUE" ENVFILE="$ENVFILE" python3 <<'PYEOF'
import os, pathlib, re

key, value = os.environ["KEY"], os.environ["VALUE"]
path = pathlib.Path(os.environ["ENVFILE"])
pattern = re.compile(r"^\s*(?:export\s+)?" + re.escape(key) + r"\s*=")

kept, removed = [], 0
for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
    if pattern.match(line):
        removed += 1
    else:
        kept.append(line)

while kept and not kept[-1].strip():
    kept.pop()
kept.append(f"{key}={value}")
path.write_text("\n".join(kept) + "\n", encoding="utf-8")
print(removed)
PYEOF
)"
chmod 600 "$ENVFILE"

printf '✓ %s saved to .env (%d characters)\n' "$KEY" "${#VALUE}"
if [ "${REMOVED:-0}" -gt 0 ] 2>/dev/null; then
    printf '  (replaced %s earlier line(s) for this key)\n' "$REMOVED"
fi

# Prove it round-trips through the loader the platform actually uses, rather
# than trusting that writing the file was enough.
if ! KEY="$KEY" python3 - <<'PYEOF'
import os, sys
sys.path.insert(0, os.getcwd())
try:
    from pcip.config import load_dotenv
except Exception:
    sys.exit(0)                      # not runnable from here; writing succeeded
os.environ.pop(os.environ["KEY"], None)
load_dotenv()
sys.exit(0 if os.environ.get(os.environ["KEY"]) else 1)
PYEOF
then
    printf '\033[31m  ✗ saved, but PCIP still cannot read %s back\033[0m\n' "$KEY"
    printf '    Check .env for another line assigning it.\n'
    exit 1
fi
printf '  verified: PCIP reads it back\n'
unset VALUE
echo
echo "next:  bash scripts/pcip-bringup.sh"
