#!/usr/bin/env bash
# One chunk of the ticket-20 backfill: fill + CONCURRENT marker-gated push/prune.
#
# Derived from the proven /tmp/chunk_fill.sh + /tmp/chunk_push_prune.sh pair, with two
# changes that matter:
#   1. ONE process owns both halves, so the chunk can never end up in the fill-only state
#      that stranded April (fill racing ahead with nothing draining behind it).
#   2. The pending-verification list is per-run (mktemp), not the shared /tmp/pending.txt.
#      Two concurrent push/prune actors sharing that path can have one overwrite the
#      other's list, after which a prune deletes local files it never proved remote.
#      That is silent data loss; a private path removes it.
#
# Usage: chunk.sh <LO> <HI> [drain]
#   chunk.sh 2026-05-01 2026-05-15          fill + concurrent push/prune
#   chunk.sh 2026-04-01 2026-04-30 drain    push/prune only, for a fill someone else owns
set -uo pipefail
LO=$1; HI=$2; MODE=${3:-full}
DATA=/Users/ross/raincheck/data
ROOT="$DATA/archive"
SRC=/Users/ross/raincheck/src
PY=/Users/ross/raincheck/.venv/bin/python
PRUNE_PY="$(cd "$(dirname "$0")" && pwd)/backfill-prune.py"
PENDING=$(mktemp "/tmp/rc-pending-${LO}-XXXXXX")
trap 'rm -f "$PENDING"' EXIT

cd /Users/ross/raincheck || exit 1
set -a; . ./.env; set +a
export AWS_DEFAULT_REGION=auto
export AWS_ACCESS_KEY_ID="$RAINCHECK_COLD_KEY_ID" AWS_SECRET_ACCESS_KEY="$RAINCHECK_COLD_SECRET"
DEST="s3://${RAINCHECK_COLD_BUCKET}/archive"

say() { echo "[$(date -u +%H:%M:%S)Z] $*"; }

# Live capture must never halt. If the archiver ever trips its budget, stop adding to the
# archive immediately rather than filling into an already-stopped capture.
budget_tripped() { [ -e "$DATA/STOPPED_BUDGET" ]; }

fill() {
  for f in vp tu alerts; do
    if budget_tripped; then say "ABORT fill: STOPPED_BUDGET present"; return 1; fi
    say "fill $f $LO..$HI"
    RAINCHECK_ARCHIVE_ROOT="$DATA" PYTHONPATH="$SRC" "$PY" -m raincheck.gapfill fill \
      --feed "$f" --date "$LO:$HI" 2>&1 | grep -vE "no missing hours" | tail -20
    rc=${PIPESTATUS[0]}
    [ "$rc" -eq 0 ] || { say "FILL FAILED $f rc=$rc"; return 1; }
  done
  say "fill complete"
}

push_prune() {
  cd "$ROOT" || return 1
  aws s3 sync . "$DEST" --endpoint-url "$RAINCHECK_COLD_ENDPOINT" --no-progress >/dev/null 2>&1
  aws s3 sync . "$DEST" --endpoint-url "$RAINCHECK_COLD_ENDPOINT" --size-only --dryrun --no-progress 2>/dev/null \
    | sed -n 's/^(dryrun) upload: \(.*\) to s3:.*$/\1/p' | sed 's|^\./||' > "$PENDING"
  "$PY" "$PRUNE_PY" "$LO" "$HI" "$PENDING" "$ROOT"
  say "archive now $(du -sh "$ROOT" | cut -f1)"
  cd /Users/ross/raincheck || return 1
}

say "=== chunk $LO..$HI ($MODE) start ==="
if [ "$MODE" = "drain" ]; then
  # Someone else owns the fill. Drain behind it until their fill process is gone.
  while pgrep -f 'raincheck\.gapfill fill' >/dev/null; do
    say "--- drain pass (foreign fill still running) ---"
    push_prune
    sleep 180
  done
  FILLRC=0
else
  fill & FILLPID=$!
  while kill -0 "$FILLPID" 2>/dev/null; do
    sleep 180
    say "--- concurrent push/prune pass ---"
    push_prune
  done
  wait "$FILLPID"; FILLRC=$?
fi
say "fill side finished rc=$FILLRC; final drain"
push_prune
push_prune          # second pass catches files uploaded during the first
say "=== chunk $LO..$HI done (rc=$FILLRC) ==="
exit "$FILLRC"
