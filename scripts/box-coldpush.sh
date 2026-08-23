#!/usr/bin/env bash
# Ticket 19: hourly push of the box's Bronze capture to R2, then prune what is verified
# remote. Push mirrors `make coldpush` (one-way `aws s3 sync`, never deletes remote).
# Prune keeps a small rolling local buffer: only files older than RAINCHECK_PRUNE_MIN
# (default 360 min) that a size-only dryrun no longer lists (present remotely at matching
# size) are deleted; static/etags.json (conditional-GET state) and STOPPED_BUDGET (the
# loud-stop marker) are never pruned. An old file still unverified is a STUCK failure
# (exit 1, the systemd unit goes red); if pushes fail outright the sync exits non-zero,
# nothing is pruned, and the archiver's RAINCHECK_BRONZE_GB stop eventually fires.
# aws prints dryrun sources cwd-relative, so we run from ROOT and compare exact
# ROOT-relative paths line for line — never substrings, never absolute.
# Env: RAINCHECK_COLD_{BUCKET,ENDPOINT,KEY_ID,SECRET}, RAINCHECK_ARCHIVE_ROOT;
#      optional RAINCHECK_AWS (aws binary), RAINCHECK_PRUNE_MIN.
set -euo pipefail

ROOT="${RAINCHECK_ARCHIVE_ROOT:?set RAINCHECK_ARCHIVE_ROOT}/archive"
DEST="s3://${RAINCHECK_COLD_BUCKET:?set RAINCHECK_COLD_BUCKET}/archive"
ENDPOINT="${RAINCHECK_COLD_ENDPOINT:?set RAINCHECK_COLD_ENDPOINT}"
AWS="${RAINCHECK_AWS:-aws}"
PRUNE_MIN="${RAINCHECK_PRUNE_MIN:-360}"
export AWS_DEFAULT_REGION=auto  # R2 rejects real AWS region names (ticket 18)
export AWS_ACCESS_KEY_ID="${RAINCHECK_COLD_KEY_ID:?set RAINCHECK_COLD_KEY_ID}"
export AWS_SECRET_ACCESS_KEY="${RAINCHECK_COLD_SECRET:?set RAINCHECK_COLD_SECRET}"

[ -d "$ROOT" ] || { echo "box-coldpush: $ROOT does not exist yet (archiver not started?)"; exit 0; }
cd "$ROOT"

"$AWS" s3 sync . "$DEST" --endpoint-url "$ENDPOINT" --no-progress

# anything a size-only dryrun would still upload is NOT verified remote — never prune it
pending=$("$AWS" s3 sync . "$DEST" --endpoint-url "$ENDPOINT" --size-only --dryrun --no-progress \
  | sed -n 's/^(dryrun) upload: \(.*\) to s3:.*$/\1/p' | sed 's|^\./||')  # v2 prefixes ./, v1 does not

pruned=0 stuck=0
while IFS= read -r f; do
  f="${f#./}"
  [ -n "$f" ] || continue
  if printf '%s\n' "$pending" | grep -qxF -- "$f"; then
    stuck=$((stuck + 1)); echo "box-coldpush: STUCK unverified after ${PRUNE_MIN}m: $ROOT/$f" >&2
  else
    rm -- "$f"; pruned=$((pruned + 1))
  fi
done < <(find . -type f -mmin +"$PRUNE_MIN" ! -name etags.json ! -name STOPPED_BUDGET)
find . -mindepth 1 -type d -empty -delete
echo "box-coldpush: pushed; pruned $pruned verified file(s) older than ${PRUNE_MIN}m"
[ "$stuck" -eq 0 ] || { echo "box-coldpush: STUCK — $stuck old file(s) not verified remote" >&2; exit 1; }
