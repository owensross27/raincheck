#!/usr/bin/env bash
# Ticket 19 cutover: retire the Mac LaunchAgent once the box has proven itself.
#
# Gate (all must hold, else nothing is touched and this exits 1). Each of the 7 days needs
# TWO independent proofs, because either one alone can be wrong:
#   - the bucket is complete for that day (box's raincheck-coldgaps journal, "coldgaps: OK")
#   - the BOX ITSELF flushed 6 kinds x 24 hours that day (its raincheck-archiver journal).
#     The bucket alone can lie: the Mac still captures locally, so one manual `make coldpush`
#     would fill a box gap in the bucket and turn coldgaps green. The box's own journal is
#     the half the Mac cannot forge.
# Plus: the box's archiver is active right now and no raincheck unit is failed - a spotless
# history and a dead box must not retire the backup.
# Both journals live on the box and are persistent there. Every failure mode fails CLOSED
# (unreachable box, unreadable journal -> gate not met, Mac agent keeps running).
#
# Only com.raincheck.archiver is retired. com.raincheck.precip-live STAYS: the box does
# not capture precip (ticket 11, MRMS), so booting that out would silently end that feed.
#
#   scripts/cutover.sh --status     show gate progress, change nothing
#   scripts/cutover.sh              enforce the gate, then retire the Mac agent
#
# Reversible: launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.raincheck.archiver.plist
set -euo pipefail

FIRST_DAY="${RAINCHECK_CUTOVER_FIRST_DAY:-2026-08-24}"  # first FULL box day (first push 08-23 14:30 UTC)
DAYS="${RAINCHECK_CUTOVER_DAYS:-7}"
BOX_HOST="${RAINCHECK_BOX_HOST:-44.218.135.197}"
BOX_USER="${RAINCHECK_BOX_USER:-ubuntu}"
KEY="${RAINCHECK_BOX_SSH_KEY:-$HOME/.ssh/lewis-signs-dev.pem}"
LABEL=com.raincheck.archiver
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"

STATUS_ONLY=0
[ "${1:-}" = "--status" ] && STATUS_ONLY=1

ssh_box() { ssh -i "$KEY" -o BatchMode=yes -o ConnectTimeout=10 "$BOX_USER@$BOX_HOST" "$@"; }
day_plus() {  # $1 = YYYY-MM-DD, $2 = offset in days; GNU || BSD
  date -u -d "$1 + $2 day" +%F 2>/dev/null || date -u -j -v+"$2"d -f %Y-%m-%d "$1" +%F
}

echo "cutover: gate = $DAYS clean coldgaps days from $FIRST_DAY, box $BOX_USER@$BOX_HOST"

journal=$(ssh_box 'sudo journalctl -u raincheck-coldgaps --no-pager' 2>/dev/null) || {
  echo "cutover: cannot read the box's coldgaps journal - box unreachable? Nothing changed." >&2
  exit 2
}

# The bucket alone can lie: the Mac still captures locally, and one manual `make coldpush`
# from it would fill a box gap in the bucket and turn coldgaps green. So a day also has to
# be clean in the BOX's own archiver journal - 6 kinds x 24 hours of flushes, the same
# granularity coldgaps checks. An empty window writes no part (archiver.py "if not rows"),
# so this never demands more than coldgaps does.
KINDS_RE='vp|tu|alerts|subway_tu|subway_vp|subway_alerts'
FULL_DAY=144  # 6 kinds x 24 hours
boxhours=$(ssh_box "sudo journalctl -u raincheck-archiver --no-pager -o cat |
  grep -oE 'archive/($KINDS_RE)/date=[0-9-]+/hour=[0-9]{2}' | sort -u" 2>/dev/null) || boxhours=""

clean=0 missing=""
for i in $(seq 0 $((DAYS - 1))); do
  d=$(day_plus "$FIRST_DAY" "$i")
  in_bucket=no
  printf '%s\n' "$journal" | grep "coldgaps: OK" | grep -qF -- "$d" && in_bucket=yes
  n=$(printf '%s\n' "$boxhours" | grep -cF "/date=$d/" || true)
  if [ "$in_bucket" = yes ] && [ "$n" -eq "$FULL_DAY" ]; then
    echo "  clean   $d  (bucket OK, box journal $n/$FULL_DAY kind-hours)"
    clean=$((clean + 1))
  else
    echo "  UNPROVEN $d  (bucket OK: $in_bucket, box journal $n/$FULL_DAY kind-hours)"
    missing="$missing $d"
  fi
done

# a proven-clean history is worthless if the box is broken right now
health=ok
ssh_box 'systemctl is-active --quiet raincheck-archiver.service' || health="archiver not active"
failed=$(ssh_box 'systemctl list-units "raincheck*" --state=failed --no-legend --no-pager' 2>/dev/null || true)
# list-units indents its rows, so awk (which skips leading blanks) not cut
[ -z "$failed" ] || health="failed unit(s): $(printf '%s' "$failed" | awk '{print $1}' | tr '\n' ' ')"

echo "cutover: $clean/$DAYS clean days; box health: $health"

if [ "$clean" -lt "$DAYS" ] || [ "$health" != ok ]; then
  [ -z "$missing" ] || echo "cutover: GATE NOT MET - unproven day(s):$missing" >&2
  [ "$health" = ok ] || echo "cutover: GATE NOT MET - box health: $health" >&2
  echo "cutover: nothing changed; the Mac agent keeps running as backup." >&2
  exit 1
fi

if [ "$STATUS_ONLY" = 1 ]; then
  echo "cutover: gate MET - re-run without --status to retire the Mac agent."
  exit 0
fi

if ! launchctl print "gui/$(id -u)/$LABEL" >/dev/null 2>&1; then
  echo "cutover: $LABEL is already not loaded - nothing to do."
  exit 0
fi

launchctl bootout "gui/$(id -u)/$LABEL"
sleep 1
if launchctl print "gui/$(id -u)/$LABEL" >/dev/null 2>&1; then
  echo "cutover: bootout did not take - $LABEL is still loaded" >&2
  exit 1
fi

echo "cutover: DONE $(date -u +%F) - $LABEL retired; the box is now the sole capture."
echo "cutover: com.raincheck.precip-live left running (box does not capture precip)."
echo "cutover: undo with  launchctl bootstrap gui/\$(id -u) $PLIST"
echo "cutover: record this date in .scratch/build/issues/19-cloud-capture-runner.md (Cutover)."
