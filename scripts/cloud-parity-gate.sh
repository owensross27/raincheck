#!/usr/bin/env bash
# Cloud ticket 03 / spec section 3: the events parity gate, and the T17 backfill's trigger.
#
# Parity is CONTENT equality - row counts plus a sha over sorted rows per partition, which
# is exactly what `python -m raincheck.parity` computes. NEVER bytes: parquet-mr permutes
# footer encoding order across JVM sessions (~27 bytes, data pages identical) [F01, T02],
# and a cluster run is by construction a different session than `make daily`, so a byte
# comparison fails on genuinely correct builds. This script adds no comparison logic of
# its own; it records the verdict and answers one question about the record.
#
# THE T17 TRIGGER IS THE POINT. "The backfill is the first thing the cluster is trusted
# with, and not before it is trusted" is a sentence, and a sentence does not stop a
# 7-year, 2,278-file submit. So the pass is WRITTEN DOWN here, and --backfill-allowed
# re-reads the record: scripts/cloud-spark-submit.sh refuses the backfill until it exits 0.
#
#   scripts/cloud-parity-gate.sh CLUSTER_ROOT MAC_ROOT [--record]
#   scripts/cloud-parity-gate.sh --backfill-allowed
# Either root may be local or an R2 prefix (s3://bucket/silver/events); the cluster's build
# lands in R2 and the Mac's on disk, which is the whole comparison.
# Exit: 0 equal / allowed - 1 differ / not yet allowed - 2 INCONCLUSIVE (could not check)
# Env: optional RAINCHECK_PARITY_TICKET (ticket file override), RAINCHECK_PYTHON.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TICKET="${RAINCHECK_PARITY_TICKET:-$ROOT/.scratch/cloud/issues/03-spark-on-k8s.md}"
PY="${RAINCHECK_PYTHON:-$ROOT/.venv/bin/python}"
[ -x "$PY" ] || PY=python3
MARK="Parity gate record"
PASS="PASS"

if [ "${1:-}" = "--backfill-allowed" ]; then
  # A recorded PASS, and nothing else, opens the backfill. Absent file, absent section and
  # a section with only failures all read the same way: not yet trusted.
  if [ -f "$TICKET" ] && grep -q "^- .*$PASS" "$TICKET" 2>/dev/null; then
    echo "parity-gate: the events parity gate has passed - T17 backfill allowed"
    grep "^- .*$PASS" "$TICKET" | tail -1
    exit 0
  fi
  echo "parity-gate: NO recorded parity PASS in $TICKET - the T17 backfill stays shut." >&2
  echo "             Run the gate against a real cluster build first; the backfill is the" >&2
  echo "             first thing the cluster is trusted with, and not before." >&2
  exit 1
fi

[ $# -ge 2 ] || { echo "usage: $(basename "$0") CLUSTER_ROOT MAC_ROOT [--record]" >&2; exit 2; }
CLUSTER="$1"; MAC="$2"; RECORD=0
[ "${3:-}" = "--record" ] && RECORD=1

echo "parity-gate: $CLUSTER  vs  $MAC"
OUT="$("$PY" -m raincheck.parity "$CLUSTER" "$MAC" 2>&1)"
RC=$?
printf '%s\n' "$OUT"

# rc 2 is INCONCLUSIVE - "could not check" - and is never rendered as a pass or a failure,
# so it is never recorded either: recording it would let an unreadable side open T17.
case "$RC" in
  0) VERDICT="$PASS" ;;
  1) VERDICT="DIFFER" ;;
  *) echo "parity-gate: INCONCLUSIVE - nothing recorded" >&2; exit 2 ;;
esac

if [ "$RECORD" -eq 1 ]; then
  grep -q "## $MARK" "$TICKET" 2>/dev/null || printf '\n## %s\n\n' "$MARK" >> "$TICKET"
  printf -- '- %s %s: `%s` vs `%s` (%s)\n' "$(date -u +%Y-%m-%d)" "$VERDICT" \
    "$CLUSTER" "$MAC" "$(printf '%s' "$OUT" | tail -1)" >> "$TICKET"
  echo "parity-gate: recorded $VERDICT in $TICKET"
fi
exit "$RC"
