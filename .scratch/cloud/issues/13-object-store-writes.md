# T13 — Writes to an object-store root

Status: open
Type: task
Blocked by: 12 (NOT yet on master — base your worktree on branch
`cloud12-data-root-r2`, the cloud 05 precedent for building on an unlanded
prerequisite, and SAY SO in your RUN LOG entry)
Owns: the writer seam — the work cloud 12 was explicitly barred from touching
and FILED FORWARD with no owner (its RUN LOG entry, 2026-08-24). Chartered by
Ross 2026-08-24. This file is the spec.

## Why this ticket exists

Cloud 12 made READS work on an R2 root and made every unconverted operation
REFUSE loudly (`RemotePath` raises rather than lies). But every WRITER is
POSIX-shaped, so cluster build pods still write ephemeral staging volumes and
their output dies with the pod. This is now the single gate in front of the
Mac hand-over chain: **orch 11 (wave 6) cannot shadow the Mac's nightly until
the cluster writes somewhere durable**; `live/`-on-R2 and unpinning `prune`
hang off it; and it is cloud 10's real remaining code precondition.

## The measured ground (cloud 12's inventory — consume, do not redo)

- 315 root-derived call sites across 35 modules; the WRITE-shaped ones:
  `.mkdir()` 35 · `.write_text()` 12 · `.replace()` 9 · plus `shutil.move` /
  `shutil.rmtree` inside `events.one_file` and `prune`.
- Spark writes already go through `df.write.parquet(str(...))` and work on an
  s3a root — the gap is the POSIX dance AROUND them (staging dirs, atomic
  renames, markers) and the pure-Python writers (gapfill markers, live
  writers, checks batches).
- `refpull` + `r2-build` + `ref/` in the bucket all EXIST (cloud 12 addendum),
  and the Mac's cold creds can write `raincheck-bronze` — so end-to-end
  verification needs no [YOU] item.

## Work

- Convert the writer seam so a stage can WRITE an R2 root, without forking any
  stage module (standing rule). The hard part is not the bytes, it is
  ATOMICITY: object stores have no rename, so `tmp.replace(out)` and
  "`_gapfill` marker written last" need store-shaped equivalents. cloud 09's
  live pair already froze the pattern for this repo — WRITE THE DATA FIRST,
  THE MARKER/META LAST, and a reader treats a missing marker as unbuilt. Use
  that shape; do not invent a lock.
- The refusal default STAYS for whatever you do not convert: an unconverted
  writer on a remote root must keep raising — a silent half-write is the exact
  lie cloud 12 exists to prevent. Convert deliberately, site by site, and say
  in your entry which sites remain refusing and why that is safe.
- **`precip_live` is STILL OUT** (unmodified contract, POSIX-only by design —
  its cluster story is a shared-volume/live-sharing decision that is not
  yours). `live_loop`/`live_export` writers are in scope only if the
  conversion is genuinely shared plumbing, not a fork.
- Mind the listing bill: cloud 12 measured `daily.gaps()` at 164 store calls
  on a 1-day window (the per-hour POSIX loop shape) and left a `ponytail:`
  note in paths.py naming the upgrade (cache one recursive listing per root).
  A BUILD on an R2 root will multiply that — if your conversion makes a stage
  hammer listings, take the cached-listing upgrade as part of this ticket and
  measure before/after.
- `prune` on a remote root: unpin it or explicitly re-scope it (a written
  decision either way — "prune stays local-only because X" is an acceptable
  outcome; silence is not).

## Acceptance

- One real stage (events for one Service date is the canonical shape) builds
  END-TO-END onto an R2 root from the Mac: write, then
  `parity.compare('s3a://...', <local build of the same day>)` reports EQUAL
  (content equality, never bytes), then `daily.gaps()` on the remote root no
  longer lists that day — the read-write loop closed by the two tools that
  already exist.
- The marker-last ordering is pinned by a test that fails when the order
  flips, and the interrupted-write case (data present, marker absent) reads
  as UNBUILT, mutation-checked.
- Unconverted writers still refuse on a remote root (test keeps cloud 12's
  refusal pin green).
- Forward-context: cloud 10's and orch 11's summary lines updated to name
  this ticket's completion entry as their gate; the FILED-FORWARD line in
  cloud 12's ticket file marked owned.
- Own-module tests only; the full suite stays gate-only.
