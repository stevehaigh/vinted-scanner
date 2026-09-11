#!/bin/sh
# Make a Mac trigger the scan workflow every few minutes.
#
# GitHub throttles `schedule:` triggers on quiet repos to a run every few
# hours, but a `workflow_dispatch` starts within seconds. This installs a
# launchd agent that runs `gh workflow run scan.yml` on an interval, so the
# Mac does the timing and GitHub still does the scanning, committing and
# emailing. The cron in scan.yml stays as a backstop for when the Mac is off.
#
#   scripts/install-dispatcher.sh            # every 5 minutes
#   scripts/install-dispatcher.sh 120        # every 2 minutes
#   scripts/install-dispatcher.sh --uninstall
#
# Needs `gh` installed and signed in (`gh auth login`) as the user running it.
set -eu

REPO="stevehaigh/vinted-scanner"
LABEL="com.stevehaigh.vinted-scanner-dispatch"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
LOG="$HOME/Library/Logs/vinted-scanner-dispatch.log"
DOMAIN="gui/$(id -u)"

if [ "${1:-}" = "--uninstall" ]; then
  launchctl bootout "$DOMAIN" "$PLIST" 2>/dev/null || true
  rm -f "$PLIST"
  echo "removed $LABEL"
  exit 0
fi

INTERVAL="${1:-300}"
case "$INTERVAL" in
  ''|*[!0-9]*|0*) echo "interval must be a positive whole number of seconds, not '$INTERVAL'" >&2; exit 1;;
esac
GH="$(command -v gh)" || { echo "gh is not installed (brew install gh)" >&2; exit 1; }
"$GH" auth status >/dev/null 2>&1 || { echo "gh is not signed in: run 'gh auth login'" >&2; exit 1; }

mkdir -p "$(dirname "$PLIST")" "$(dirname "$LOG")"
cat > "$PLIST" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>$GH</string>
    <string>workflow</string><string>run</string><string>scan.yml</string>
    <string>--repo</string><string>$REPO</string>
  </array>
  <key>StartInterval</key><integer>$INTERVAL</integer>
  <key>RunAtLoad</key><true/>
  <key>StandardOutPath</key><string>$LOG</string>
  <key>StandardErrorPath</key><string>$LOG</string>
</dict>
</plist>
PLIST

# bootout first so re-running the script picks up a new interval.
launchctl bootout "$DOMAIN" "$PLIST" 2>/dev/null || true
launchctl bootstrap "$DOMAIN" "$PLIST"
echo "installed $LABEL: dispatching scan.yml every ${INTERVAL}s, log at $LOG"
