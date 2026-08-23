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
DATA=${RAINCHECK_BACKFILL_DATA:-/Users/ross/raincheck/data}   # overridable so the
                                                             # prune guard is testable
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

# Sync only the month prefixes this chunk touches, instead of walking the whole archive
# every 180 s to verify at most a half-month of it. Correct because the prune is already
# structurally confined to [LO,HI]: a pending list covering the chunk's months is exactly
# the list it consults. Live-capture dates are outside these prefixes, so a pass no longer
# touches them at all - the 06:00 daily job and the EC2 box push those.
SCOPE=(--exclude "*")
for _k in vp tu alerts; do
  for _m in $(printf '%s\n%s\n' "${LO:0:7}" "${HI:0:7}" | sort -u); do
    SCOPE+=(--include "$_k/date=$_m-*")
  done
done

# Live capture must never halt. If the archiver ever trips its budget, stop adding to the
# archive immediately rather than filling into an already-stopped capture.
budget_tripped() { [ -e "$DATA/STOPPED_BUDGET" ]; }

fill() {
  for f in vp tu alerts; do
    if budget_tripped; then say "ABORT fill: STOPPED_BUDGET present"; return 1; fi
    say "fill $f $LO..$HI"
    # No tail: keep every line the fill emits. When April's two torn days had to be
    # diagnosed, the driver's output had been truncated and then died with its session,
    # so why hour 23 went missing could not be reconstructed. The per-day "filled N/24"
    # lines are the record of what actually happened; a chunk log is cheap, a lost one
    # is not. Only the "no missing hours" no-op spam is dropped.
    RAINCHECK_ARCHIVE_ROOT="$DATA" PYTHONPATH="$SRC" "$PY" -m raincheck.gapfill fill \
      --feed "$f" --date "$LO:$HI" 2>&1 | grep -vE "no missing hours"
    rc=${PIPESTATUS[0]}
    [ "$rc" -eq 0 ] || { say "FILL FAILED $f rc=$rc"; return 1; }
  done
  say "fill complete"
}

push_prune() {
  cd "$ROOT" || return 1
  budget_tripped && say "CRITICAL: STOPPED_BUDGET present - live capture has halted"
  aws s3 sync . "$DEST" --endpoint-url "$RAINCHECK_COLD_ENDPOINT" "${SCOPE[@]}" \
    --no-progress >/dev/null 2>&1

  # The prune deletes anything NOT in this listing, so an empty listing means "delete
  # everything marked". A failed dryrun (network blip, expired creds, endpoint down)
  # produces exactly that empty file, and the prune would then delete local parts it
  # never proved remote - with local pruned and R2 never written, that is real data loss.
  # So the listing's exit status gates the prune: no proof, no deletion.
  # Stamp BEFORE the listing starts. Anything written at or after this instant cannot be
  # in the listing, so its absence from the pending set proves nothing and the prune must
  # keep it. Without this, hour 23 - the last part a day writes before its markers appear
  # - gets deleted having never been uploaded.
  local snap; snap=$(date +%s)
  local raw="$PENDING.raw"
  if ! aws s3 sync . "$DEST" --endpoint-url "$RAINCHECK_COLD_ENDPOINT" "${SCOPE[@]}" \
        --size-only --dryrun --no-progress > "$raw" 2>/dev/null; then
    say "SKIP prune: remote listing failed, nothing proven remote (keeping all local)"
    rm -f "$raw"; cd /Users/ross/raincheck || return 1
    return 1
  fi
  sed -n 's/^(dryrun) upload: \(.*\) to s3:.*$/\1/p' "$raw" | sed 's|^\./||' > "$PENDING"
  rm -f "$raw"

  "$PY" "$PRUNE_PY" "$LO" "$HI" "$PENDING" "$ROOT" "$snap"
  say "archive now $(du -sh "$ROOT" | cut -f1)"
  cd /Users/ross/raincheck || return 1
}

say "=== chunk $LO..$HI ($MODE) start ==="
if [ "$MODE" = "drain" ]; then
  # Someone else owns the fill. Drain behind it until their fill is really finished.
  # "Finished" needs two consecutive idle checks, not one: a driver looping over feeds
  # (vp -> tu -> alerts) leaves a gap of a second or two between them with no gapfill
  # process alive, and a single check can land in that gap and quit with two feeds still
  # to come. Two checks a sleep apart cannot both land in a gap that short.
  idle=0
  while [ "$idle" -lt 2 ]; do
    if pgrep -f 'raincheck\.gapfill fill' >/dev/null; then idle=0; else idle=$((idle + 1)); fi
    say "--- drain pass (foreign fill running; idle checks: $idle/2) ---"
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
