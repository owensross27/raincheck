#!/usr/bin/env bash
# Ticket 19: hour-completeness check for one closed UTC day in the R2 bucket — every
# live-capture kind must show all 24 hour= dirs under archive/<kind>/date=<day>/.
# Loud on any gap and exits 1; an aws/auth/network error is exit 2 (never reported as a
# capture gap); when RAINCHECK_ARCHIVE_ROOT is set, a local STOPPED_BUDGET marker also
# fails loudly — the archiver's budget stop exits 0, so this daily check is what turns
# it red on the box. Doubles as the box's daily health check (raincheck-coldgaps.timer).
# Runs anywhere with aws + the cold-storage env:
#   scripts/coldgaps.sh [YYYY-MM-DD]     (default: yesterday UTC)
# Env: RAINCHECK_COLD_{BUCKET,ENDPOINT,KEY_ID,SECRET}; optional RAINCHECK_AWS,
#      RAINCHECK_ARCHIVE_ROOT (enables the budget-marker check).
set -euo pipefail

DAY="${1:-$(date -u -d yesterday +%F 2>/dev/null || date -u -v-1d +%F)}"  # GNU || BSD
KINDS="vp tu alerts subway_tu subway_vp subway_alerts"
BUCKET="${RAINCHECK_COLD_BUCKET:?set RAINCHECK_COLD_BUCKET}"
ENDPOINT="${RAINCHECK_COLD_ENDPOINT:?set RAINCHECK_COLD_ENDPOINT}"
AWS="${RAINCHECK_AWS:-aws}"
export AWS_DEFAULT_REGION=auto  # R2 rejects real AWS region names (ticket 18)
export AWS_ACCESS_KEY_ID="${RAINCHECK_COLD_KEY_ID:?set RAINCHECK_COLD_KEY_ID}"
export AWS_SECRET_ACCESS_KEY="${RAINCHECK_COLD_SECRET:?set RAINCHECK_COLD_SECRET}"

gaps=0
marker="${RAINCHECK_ARCHIVE_ROOT:-}/archive/STOPPED_BUDGET"
if [ -n "${RAINCHECK_ARCHIVE_ROOT:-}" ] && [ -f "$marker" ]; then
  echo "COLDGAPS: capture is STOPPED over budget ($marker: $(cat "$marker"))"
  gaps=1
fi

errf=$(mktemp)
trap 'rm -f "$errf"' EXIT
for kind in $KINDS; do
  # empty prefix: aws s3 ls exits 1 with empty stderr = every hour missing (a real gap);
  # anything on stderr (auth, endpoint, network) is an infra error, not a gap
  listing=$("$AWS" s3 ls "s3://$BUCKET/archive/$kind/date=$DAY/" --endpoint-url "$ENDPOINT" 2>"$errf") || listing=""
  if [ -s "$errf" ]; then
    echo "coldgaps: aws error for $kind (NOT a capture gap):" >&2
    cat "$errf" >&2
    exit 2
  fi
  # An hour prefix holding ONLY gapfill's `_dead` marker (hour proven dead at source,
  # synced up by coldpush) still lists as `PRE hour=NN/` and counts as held below.
  # Tolerated on purpose: a dead-at-source hour is not a capture gap, which is what this
  # check pages on - but know that this non-recursive listing cannot tell data from
  # marker, so "24/24" here does not by itself mean 24 hours of rows.
  have=$(printf '%s\n' "$listing" | sed -n 's/.*hour=\([0-9][0-9]\).*/\1/p')
  missing=""
  for h in $(seq -w 0 23); do
    case "$have" in *"$h"*) ;; *) missing="$missing $h" ;; esac
  done
  if [ -n "$missing" ]; then
    echo "COLDGAPS $DAY $kind: missing hour(s):$missing"
    gaps=1
  else
    echo "coldgaps $DAY $kind: 24/24"
  fi
done
if [ "$gaps" -ne 0 ]; then echo "coldgaps: GAP — see above (s3://$BUCKET/archive, day $DAY)"; exit 1; fi
echo "coldgaps: OK — $DAY complete for all 6 kinds"
