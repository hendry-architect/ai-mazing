#!/usr/bin/env bash
#
# Install the Mon/Wed/Fri launchd job. Fills in the two placeholders in the
# plist with this machine's real paths (they can't be known ahead of time —
# every clone lives somewhere different) and loads it.
#
#   bash scripts/pcip-schedule-install.sh            # install
#   bash scripts/pcip-schedule-install.sh --uninstall
#
set -uo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST="$HOME/Library/LaunchAgents/com.passqual.pcip.schedule.plist"

if [ "${1:-}" = "--uninstall" ]; then
  launchctl unload "$DEST" 2>/dev/null
  rm -f "$DEST"
  echo "removed $DEST — the Mon/Wed/Fri schedule will not fire again."
  exit 0
fi

if [ "$(uname)" != "Darwin" ]; then
  echo "error: launchd is macOS-only. On Linux, install the equivalent" \
       "systemd timer or cron entry for scripts/pcip-scheduled-post.sh yourself."
  exit 1
fi

mkdir -p "$(dirname "$DEST")"
sed -e "s#REPLACE_WITH_REPO_PATH#$REPO#g" \
    -e "s#REPLACE_WITH_HOME_PATH#$HOME#g" \
    "$REPO/scripts/com.passqual.pcip.schedule.plist" > "$DEST"

launchctl unload "$DEST" 2>/dev/null    # clean reload if already installed
launchctl load "$DEST"

echo "installed → $DEST"
echo "runs Mon/Wed/Fri at 08:00 (fires at next wake if asleep at that time)."
echo
echo "verify it's loaded:"
echo "  launchctl list | grep com.passqual.pcip.schedule"
echo
echo "run it right now without waiting for Monday:"
echo "  launchctl start com.passqual.pcip.schedule"
echo
echo "watch it happen:"
echo "  tail -f \"$REPO/pcip_data/schedule/logs\"/*.log"
