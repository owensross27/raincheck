#!/usr/bin/env bash
# Cloud ticket 08 / spec section 8: the monthly bill review. Reads Cost Explorer for one
# month of `Project=raincheck-cloud` spend, prints one dated markdown entry (per-service
# lines, run rate, delta against the $130 envelope), and with --append writes it into
# 08-cost-guardrails.md so drift is caught in a month rather than a quarter.
#
# $130 is a HARD-LOOK line, never an auto-stop: a crossing exits 1 and stamps the entry
# `Decision: REQUIRED - not yet recorded`. `--check` re-reads the recorded entries and
# fails while any crossing still carries that stamp, so a crossing cannot continue
# silently either -- the module test runs --check against the real ticket file.
#
# A tag filter only sees resources Cost Explorer has already attributed to the tag.
# Freshly activated tags take up to 24 h to populate (measured 2026-08-24: tag Active,
# tagged total $0, account total $103.18). That is `could not check`, not `under
# budget`, so it exits 2 the way `coldgaps.sh` does -- never rendered as ok or as fail.
#
#   scripts/cloud-bill-review.sh [YYYY-MM] [--append]   (default: last closed month)
#   scripts/cloud-bill-review.sh --check
# Exit: 0 ok - 1 HARD LOOK / undecided crossing - 2 INCONCLUSIVE (could not check)
# Env: optional RAINCHECK_AWS (stub hook), RAINCHECK_BILL_TICKET (ticket file override).
set -euo pipefail

# Frozen, not configurable: moving the line by env var is exactly the silent drift this
# guards against. $130 = spec section 8's hard-look line (raised from $100 by Ross
# 2026-08-23 on ticket 01's measured ~$121.5/mo); $210 = the aws-account-total backstop.
ENVELOPE=130
BACKSTOP=210
TAG_KEY=Project
TAG_VALUE=raincheck-cloud
UNRECORDED="REQUIRED - not yet recorded"

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TICKET="${RAINCHECK_BILL_TICKET:-$ROOT/.scratch/cloud/issues/08-cost-guardrails.md}"
AWS="${RAINCHECK_AWS:-aws}"

MONTH=""
APPEND=0
CHECK=0
for a in "$@"; do
  case "$a" in
    --append) APPEND=1 ;;
    --check)  CHECK=1 ;;
    [0-9][0-9][0-9][0-9]-[0-9][0-9]) MONTH="$a" ;;
    *) echo "usage: $(basename "$0") [YYYY-MM] [--append] | --check" >&2; exit 2 ;;
  esac
done

# --check: every recorded HARD LOOK entry must carry a decision that is not the stamp.
if [ "$CHECK" = 1 ]; then
  [ -f "$TICKET" ] || { echo "bill-review: no ticket file at $TICKET" >&2; exit 2; }
  if awk -v un="$UNRECORDED" -v envelope="$ENVELOPE" '
        /^### bill / { m = $3; order[++n] = m; next }
        m == "" { next }
        /^Verdict: HARD LOOK/ { hard[m] = 1 }
        /^Decision:/ { dec[m] = substr($0, 11) }
        END {
          bad = 0
          for (i = 1; i <= n; i++) {
            mm = order[i]
            if (!hard[mm]) continue
            d = dec[mm]; gsub(/^[ \t]+|[ \t]+$/, "", d)
            if (d == "" || index(d, un)) {
              print "bill-review: " mm " crossed $" envelope " with no recorded decision"
              bad = 1
            }
          }
          exit bad
        }' "$TICKET"
  then
    echo "bill-review: every recorded crossing has a decision"
    exit 0
  fi
  echo "bill-review: a crossing of \$$ENVELOPE is recorded with no decision -- shrink the" >&2
  echo "  streaming driver, drop the third node, or take the downscale path, then write it" >&2
  echo "  into the entry's Decision: line. \$$ENVELOPE is a hard look, not an auto-stop." >&2
  exit 1
fi

TODAY=$(date -u +%F)
if [ -z "$MONTH" ]; then
  MONTH=$(awk -v t="$TODAY" 'BEGIN{ split(t, p, "-"); m = p[2] + 0 - 1; y = p[1] + 0
                                    if (m == 0) { m = 12; y-- }
                                    printf "%04d-%02d", y, m }')
fi
Y=${MONTH%-*}; M=${MONTH#*-}
START="$MONTH-01"
NEXT=$(awk -v y="$Y" -v m="$M" 'BEGIN{ m = m + 1; if (m == 13) { m = 1; y++ }
                                      printf "%04d-%02d-01", y, m }')
DIM=$(awk -v y="$Y" -v m="$M" 'BEGIN{ split("31 28 31 30 31 30 31 31 30 31 30 31", d, " ")
                                      n = d[m + 0]
                                      if (m + 0 == 2 && (y % 4 == 0 && (y % 100 != 0 || y % 400 == 0))) n = 29
                                      print n }')

# Cost Explorer's end is exclusive; today's own spend is partial, so a mid-month review
# covers closed days only and the run rate scales those days to the whole month.
END="$NEXT"
if [ "$NEXT" \> "$TODAY" ]; then END="$TODAY"; fi
if [ "$END" \> "$START" ]; then :; else
  echo "bill-review: $MONTH has no closed days yet (start $START, today $TODAY)" >&2; exit 2
fi
if [ "$END" = "$NEXT" ]; then DAYS="$DIM"; else DAYS=$(( ${END##*-} - 1 )); fi

errf=$(mktemp); trap 'rm -f "$errf"' EXIT
ce() {  # any aws/auth/network failure is `could not check` (2), never a verdict
  "$AWS" ce "$@" --output text 2>"$errf" || {
    echo "bill-review: aws ce error (NOT a spend verdict):" >&2; cat "$errf" >&2; exit 2; }
}

TAGS=$(ce get-tags --time-period "Start=$START,End=$END" --tag-key "$TAG_KEY" --query 'Tags')
ACCOUNT=$(ce get-cost-and-usage --time-period "Start=$START,End=$END" --granularity MONTHLY \
            --metrics UnblendedCost --query 'ResultsByTime[0].Total.UnblendedCost.Amount')
SERVICES=$(ce get-cost-and-usage --time-period "Start=$START,End=$END" --granularity MONTHLY \
            --metrics UnblendedCost \
            --filter "{\"Tags\":{\"Key\":\"$TAG_KEY\",\"Values\":[\"$TAG_VALUE\"]}}" \
            --group-by "Type=DIMENSION,Key=SERVICE" \
            --query 'ResultsByTime[0].Groups[].[Keys[0],Metrics.UnblendedCost.Amount]')

TAGGED=$(printf '%s\n' "$SERVICES" | awk -F'\t' '{ s += $2 } END { printf "%.2f", s + 0 }')
RUNRATE=$(awk -v t="$TAGGED" -v d="$DAYS" -v m="$DIM" 'BEGIN{ printf "%.2f", t / d * m }')
DELTA=$(awk -v r="$RUNRATE" -v e="$ENVELOPE" 'BEGIN{ printf "%+.2f", r - e }')
ACCOUNT=$(awk -v a="$ACCOUNT" 'BEGIN{ printf "%.2f", a + 0 }')

# INCONCLUSIVE beats every other verdict: with no tag data the $0 total is an artefact,
# and reading it as `under envelope` is the failure this whole ticket exists to prevent.
case "	$TAGS	" in
  *"	$TAG_VALUE	"*) SEEN=1 ;;
  *) SEEN=0 ;;
esac

if [ "$SEEN" = 0 ]; then
  RC=2; VERDICT="INCONCLUSIVE - Cost Explorer has no \`$TAG_KEY=$TAG_VALUE\` data for $MONTH"
  DECISION="n/a - re-run once the tag populates (up to 24 h after activation)"
elif awk -v t="$TAGGED" -v r="$RUNRATE" -v e="$ENVELOPE" 'BEGIN{ exit !(t >= e || r >= e) }'; then
  RC=1; DECISION="$UNRECORDED"
  if awk -v t="$TAGGED" -v e="$ENVELOPE" 'BEGIN{ exit !(t >= e) }'
    then VERDICT="HARD LOOK - actual \$$TAGGED crossed the \$$ENVELOPE line"
    else VERDICT="HARD LOOK - run rate \$$RUNRATE crosses the \$$ENVELOPE line ($DAYS/$DIM days in)"
  fi
else
  RC=0; VERDICT="OK"; DECISION="n/a"
fi

entry() {
  printf '\n### bill %s -- reviewed %s\n\n' "$MONTH" "$TODAY"
  printf '| line | $ |\n|---|---|\n'
  printf '%s\n' "$SERVICES" | awk -F'\t' 'NF == 2 { printf "| %s | %.2f |\n", $1, $2 }'
  printf '| **tagged total (%s of %s days)** | **%s** |\n' "$DAYS" "$DIM" "$TAGGED"
  printf '\nRun rate %s/mo against the $%s envelope: %s. Account total %s (backstop $%s).\n' \
         "$RUNRATE" "$ENVELOPE" "$DELTA" "$ACCOUNT" "$BACKSTOP"
  printf 'Verdict: %s\n' "$VERDICT"
  printf 'Decision: %s\n' "$DECISION"
}

if [ "$APPEND" = 1 ]; then
  if grep -q "^### bill $MONTH " "$TICKET" 2>/dev/null; then
    echo "bill-review: $MONTH is already recorded in $TICKET -- edit it by hand" >&2; exit 2
  fi
  entry >> "$TICKET"
  echo "bill-review: $MONTH appended to $TICKET -- $VERDICT"
else
  entry
fi
exit "$RC"
