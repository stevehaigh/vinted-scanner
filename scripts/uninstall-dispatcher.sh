#!/bin/sh
# Stop the Mac from dispatching scan runs, and remove the launchd agent.
#
# Standalone on purpose: it hardcodes the label rather than reading anything
# from the repo, so you can run it on a machine that has no checkout. Safe to
# run twice, and safe to run when nothing is installed.
#
#   scripts/uninstall-dispatcher.sh              # stop and remove the agent
#   scripts/uninstall-dispatcher.sh --purge-log  # also delete the log file
#   scripts/uninstall-dispatcher.sh --status     # report, change nothing
set -eu

LABEL="com.stevehaigh.vinted-scanner-dispatch"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
LOG="$HOME/Library/Logs/vinted-scanner-dispatch.log"
DOMAIN="gui/$(id -u)"

PURGE_LOG=no
STATUS_ONLY=no
for arg in "$@"; do
  case "$arg" in
    --purge-log) PURGE_LOG=yes ;;
    --status) STATUS_ONLY=yes ;;
    # Print the header comment, stopping at the first line that is not one.
    -h|--help) sed -n '2,/^[^#]/p' "$0" | sed '$d; s/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown option '$arg' (try --help)" >&2; exit 2 ;;
  esac
done

[ "$(uname -s)" = "Darwin" ] || { echo "this only makes sense on macOS" >&2; exit 1; }

is_loaded() { launchctl print "$DOMAIN/$LABEL" >/dev/null 2>&1; }

report() {
  if is_loaded; then echo "  agent   : LOADED"; else echo "  agent   : not loaded"; fi
  if [ -f "$PLIST" ]; then echo "  plist   : $PLIST"; else echo "  plist   : absent"; fi
  if [ -f "$LOG" ]; then
    echo "  log     : $LOG ($(wc -c <"$LOG" | tr -d ' ') bytes)"
  else
    echo "  log     : absent"
  fi
}

if [ "$STATUS_ONLY" = yes ]; then
  echo "$LABEL"
  report
  exit 0
fi

echo "before:"
report

# Boot out by label first: that works even when the plist file has already been
# deleted, which is the state a half-finished uninstall leaves behind. Then by
# path, for older macOS where the label form is not accepted.
launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
[ -f "$PLIST" ] && launchctl bootout "$DOMAIN" "$PLIST" 2>/dev/null || true
# Pre-Catalina fallback. Harmless when bootout already did the job.
launchctl unload -w "$PLIST" 2>/dev/null || true

rm -f "$PLIST"
[ "$PURGE_LOG" = yes ] && rm -f "$LOG"

echo "after:"
report

if is_loaded; then
  echo >&2
  echo "the agent is still loaded. Something re-registered it, or it is installed" >&2
  echo "in a different domain. Try:  launchctl print $DOMAIN/$LABEL" >&2
  exit 1
fi

echo
echo "done - this Mac will no longer dispatch scan runs."
[ "$PURGE_LOG" = no ] && [ -f "$LOG" ] && echo "log kept at $LOG (--purge-log removes it)"
exit 0
