#!/usr/bin/env bash
#
# Copy credentials from another .env into this repo's .env.
#
#   bash scripts/pcip-merge-env.sh "/path/to/other/.env"
#
# Only fills gaps. A key already carrying a value here is never overwritten,
# and a key whose value is empty in the source is never copied — an empty
# assignment outranks nothing and produces an authentication error that looks
# nothing like "this one is blank", which has cost this project real debugging
# time more than once.
#
# Reports key names only. Values are never printed, and never appear in shell
# history, so this is safe to run in a shared terminal.
set -uo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TARGET="$REPO/.env"
SOURCE="${1:-}"

if [ -z "$SOURCE" ]; then
  echo "usage: bash scripts/pcip-merge-env.sh <path to the other .env>"
  echo
  echo "find candidates with:"
  echo "  find ~ -maxdepth 6 -name .env -not -path '*/node_modules/*' 2>/dev/null"
  exit 1
fi

if [ ! -f "$SOURCE" ]; then
  echo "error: no file at $SOURCE"
  exit 1
fi

[ -f "$TARGET" ] || { touch "$TARGET"; echo "created $TARGET"; }
cp "$TARGET" "$TARGET.bak.$(date +%Y%m%d%H%M%S)"
chmod 600 "$TARGET" "$TARGET".bak.* 2>/dev/null

SOURCE="$SOURCE" TARGET="$TARGET" python3 <<'PYEOF'
import os
import pathlib
import re

LINE = re.compile(r"^([A-Z][A-Z0-9_]*)=(.*)$")


def parse(path):
    """Last assignment wins, matching how the loader reads a file."""
    values = {}
    for line in pathlib.Path(path).read_text(encoding="utf-8").splitlines():
        match = LINE.match(line.strip())
        if match:
            values[match.group(1)] = match.group(2).strip().strip("'\"")
    return values


source = parse(os.environ["SOURCE"])
target_path = pathlib.Path(os.environ["TARGET"])
target = parse(target_path)

added, kept, empty = [], [], []
for key, value in sorted(source.items()):
    if not value:
        empty.append(key)
    elif target.get(key):
        kept.append(key)
    else:
        added.append(key)

lines = target_path.read_text(encoding="utf-8").splitlines()
# Replace a present-but-empty key in place; append the genuinely new ones, so
# the file keeps its own comments and grouping instead of being regenerated.
for key in list(added):
    for i, line in enumerate(lines):
        if LINE.match(line.strip()) and line.strip().split("=", 1)[0] == key:
            lines[i] = f"{key}={source[key]}"
            break
    else:
        lines.append(f"{key}={source[key]}")

target_path.write_text("\n".join(lines).rstrip("\n") + "\n", encoding="utf-8")

def report(label, keys):
    print(f"{label:<28}{', '.join(keys) if keys else '(none)'}")

report("copied in:", added)
report("already set, left alone:", kept)
report("empty in source, skipped:", empty)
PYEOF

chmod 600 "$TARGET"
echo
echo "verify with:  python -m pcip doctor --live"
