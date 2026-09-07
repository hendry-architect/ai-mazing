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

TMP="$(mktemp)"
grep -v "^[[:space:]]*\(export[[:space:]]\+\)\?${KEY}=" "$ENVFILE" > "$TMP" 2>/dev/null
printf '%s=%s\n' "$KEY" "$VALUE" >> "$TMP"
mv "$TMP" "$ENVFILE"
chmod 600 "$ENVFILE"

printf '✓ %s saved to .env (%d characters)\n' "$KEY" "${#VALUE}"
unset VALUE
echo
echo "next:  bash scripts/pcip-bringup.sh"
