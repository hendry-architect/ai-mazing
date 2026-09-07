#!/usr/bin/env bash
#
# Read-only reconnaissance of your own WordPress hosts.
#
#   bash scripts/pcip-site-audit.sh
#
# Every request is an ordinary GET to a site you control. Nothing is written,
# nothing is uploaded, no real credential is ever sent — the auth probe uses a
# deliberately wrong password, because the point is to read WordPress's error
# code, not to log in.
#
# Answers three questions:
#   1. Is the Authorization header reaching PHP? (the publishing blocker)
#   2. Is anything sensitive being served that should not be?
#   3. What is auth_test.php, and is it reachable from the internet?
#
set -uo pipefail

HOSTS="${*:-wp.passqual.com passqual.com}"
UA="PCIP-site-audit"
CURL=(curl -sS -m 20 --max-redirs 3 -A "$UA")

hdr()  { printf '\n\033[1m━━━ %s ━━━\033[0m\n' "$*"; }
ok()   { printf '\033[32m    ✓ %s\033[0m\n' "$*"; }
warn() { printf '\033[33m    ⚠ %s\033[0m\n' "$*"; }
bad()  { printf '\033[31m    ✗ %s\033[0m\n' "$*"; }
info() { printf '      %s\n' "$*"; }

# status | content-type | length, without downloading a large body.
# Pipe-separated because content_type itself contains spaces
# ("text/html; charset=UTF-8"), which breaks whitespace splitting.
probe() {
    "${CURL[@]}" -o /dev/null -w '%{http_code}|%{content_type}|%{size_download}' "$1" 2>/dev/null \
        || echo "000|unreachable|0"
}
field() { printf '%s' "$1" | cut -d'|' -f"$2"; }

for HOST in $HOSTS; do
  hdr "$HOST"

  # ── 1. Is the host answering at all? ───────────────────────────────────────
  ROOT="$(probe "https://$HOST/")"
  CODE="$(field "$ROOT" 1)"
  if [ "$CODE" = "000" ]; then
    bad "cannot reach https://$HOST/ — skipping the rest for this host"
    continue
  fi
  info "root responds: HTTP $CODE"

  # ── 2. The publishing blocker ──────────────────────────────────────────────
  # A deliberately wrong password. WordPress's own error code distinguishes
  # "I never saw a credential" from "I saw it and it was wrong" — which is
  # exactly the difference between a stripped header and a working one.
  AUTH="$("${CURL[@]}" -u "pcip-audit-probe:deliberately-wrong-password" \
          "https://$HOST/wp-json/wp/v2/users/me" 2>/dev/null)"
  case "$AUTH" in
    *rest_not_logged_in*)
        bad "Authorization header NOT reaching PHP (rest_not_logged_in)"
        info "WordPress received no credential at all — the header is stripped." ;;
    *incorrect_password*|*invalid_username*|*invalid_application_password*)
        ok  "Authorization header IS reaching PHP"
        info "WordPress read the credential and rejected the fake one. Correct." ;;
    *rest_no_route*|*"404"*)
        warn "no REST route here — this host may not serve the WordPress API" ;;
    "")  warn "empty response from the REST API" ;;
    *)   warn "unexpected REST response:"
         info "$(printf '%s' "$AUTH" | head -c 200)" ;;
  esac

  # ── 3. auth_test.php — what is it, and is it public? ───────────────────────
  AT="$(probe "https://$HOST/auth_test.php")"
  ATCODE="$(field "$AT" 1)"
  case "$ATCODE" in
    200)
        warn "auth_test.php is PUBLICLY REACHABLE (HTTP 200)"
        info "type: $(field "$AT" 2)   bytes: $(field "$AT" 3)"
        info "unauthenticated output:"
        "${CURL[@]}" "https://$HOST/auth_test.php" 2>/dev/null \
            | head -c 400 | sed 's/^/        /'
        echo
        info "NOTE: this is the file's OUTPUT, not its source. Read the source"
        info "in SiteGround File Manager before deciding what it is."

        # ── The decisive test ──────────────────────────────────────────────
        # This probe reports the raw header as PHP sees it, which isolates the
        # one variable WordPress's error code cannot: whether the header
        # survives the web server at all. rest_not_logged_in is consistent
        # with a stripped header AND with WordPress declining it for its own
        # reasons; this is not.
        AUTHED="$("${CURL[@]}" -u "header-probe:not-a-real-password" \
                  "https://$HOST/auth_test.php" 2>/dev/null)"
        SEEN="$(printf '%s' "$AUTHED" | grep -i '^Authorization:' | head -1)"
        VALUE="$(printf '%s' "$SEEN" | cut -d: -f2- | tr -d ' \r')"
        printf '\n'
        if [ -n "$VALUE" ]; then
            ok  "PHP DOES receive the Authorization header"
            info "PHP sees: ${VALUE:0:12}…  (a Basic credential arrived intact)"
            info "So the web server is NOT the problem — the header survives."
            info "If WordPress still says rest_not_logged_in, the cause is"
            info "inside WordPress: application passwords disabled, a security"
            info "plugin refusing Basic auth, or REST auth filtered."
        else
            bad "PHP does NOT receive the Authorization header"
            info "The credential was sent and is gone before PHP runs."
            info "Confirmed at the web-server layer, not inferred from"
            info "WordPress's error code."
        fi ;;
    403|401)
        ok  "auth_test.php exists but is access-restricted (HTTP $ATCODE)" ;;
    404)
        ok  "auth_test.php is not served from the web root here" ;;
    000)
        warn "could not probe auth_test.php" ;;
    *)  warn "auth_test.php returned HTTP $ATCODE" ;;
  esac

  # ── 4. Files that must never be served ─────────────────────────────────────
  # .backup / .bak / .old are not PHP extensions, so a web server hands them
  # out as plain text — database credentials included.
  for F in wp-config.backup wp-config.php.bak wp-config.php.save wp-config.old \
           .env .htaccess debug.log wp-config.php~; do
    R="$(probe "https://$HOST/$F")"
    RC="$(field "$R" 1)"
    SZ="$(field "$R" 3)"
    case "$SZ" in ''|*[!0-9]*) SZ=0 ;; esac
    if [ "$RC" = "200" ] && [ "$SZ" -gt 0 ]; then
      bad "EXPOSED: https://$HOST/$F  (HTTP 200, ${SZ} bytes)"
      info "if this contains credentials, rotate them and block the file"
    fi
  done
  ok "checked for exposed config/backup files (only failures are printed above)"

  # ── 5. Routine hardening observations ──────────────────────────────────────
  X="$(probe "https://$HOST/xmlrpc.php")"
  [ "$(field "$X" 1)" = "200" ] && warn "xmlrpc.php is open (common brute-force target)"

  U="$("${CURL[@]}" "https://$HOST/wp-json/wp/v2/users" 2>/dev/null | head -c 120)"
  case "$U" in
    *'"id"'*) warn "user list is public at /wp-json/wp/v2/users (enumerable logins)" ;;
  esac
done

# ── 6. Is there a route that avoids this host's web server entirely? ────────
# WordPress.com's public API proxies to a Jetpack-connected site. Requests go
# to WordPress.com, not to this host's Apache/nginx, so a stripped
# Authorization header cannot affect them — there is nothing on the server to
# fix. Worth knowing before editing any server file.
hdr "Alternate publishing route (no server changes)"
for HOST in $HOSTS; do
  JP="$("${CURL[@]}" "https://public-api.wordpress.com/rest/v1.1/sites/$HOST" 2>/dev/null)"
  case "$JP" in
    *'"unknown_blog"'*|*'"not_found"'*|*'"authorization_required"'*)
        info "$HOST — not reachable via WordPress.com public API"
        info "  (Jetpack not connected, or the site is private)" ;;
    *'"ID"'*|*'"id"'*)
        SITEID="$(printf '%s' "$JP" | sed -n 's/.*"ID":[ ]*\([0-9]*\).*/\1/p' | head -1)"
        ok  "$HOST IS connected to WordPress.com (site ID ${SITEID:-unknown})"
        info "PCIP can publish through this route with WORDPRESS_COM_TOKEN and"
        info "never touch the origin server. This bypasses the stripped header"
        info "entirely — there is nothing to fix on the host." ;;
    "") info "$HOST — no response from the WordPress.com API" ;;
    *)  info "$HOST — unrecognised response:"
        info "  $(printf '%s' "$JP" | head -c 160)" ;;
  esac
done

hdr "What this cannot tell you"
cat <<'EOF'
    HTTP cannot show you the SOURCE of a PHP file — only what it prints.
    To read auth_test.php and .htaccess you still need SiteGround
    File Manager (or SSH). This audit tells you which files are worth
    opening first, and whether anything is exposed right now.
EOF
