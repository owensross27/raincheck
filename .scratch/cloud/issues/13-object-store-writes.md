# T13 — Writes to an object-store root

Status: done (2026-08-24)
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

---

## Close-out (2026-08-24)

Worktree `/Users/ross/raincheck-wt-cloud13`, branch `cloud13-object-store-writes`,
**based on `cloud12-data-root-r2` at `6dab8bc`** (cloud 12 is unlanded; the cloud 05
precedent). Own-module tests only; the full suite stays gate-only.

### What shipped

`paths.py` gained the WHOLE-OBJECT write half and nothing more:

| added | on a local root | on an object-store root |
|---|---|---|
| `RemotePath.write_bytes` / `write_text` | (Path's own) | one `put_object` - atomic |
| `RemotePath.touch` | (Path's own) | an empty object; no mtime semantics |
| `RemotePath.mkdir` | (Path's own) | **no-op** - there are no directories |
| `paths.move(src, dst)` | `shutil.move` | server-side copy + delete; refuses to cross |
| `paths.rmtree(p)` | `shutil.rmtree`, missing-ok | recursive prefix delete |
| `paths.rmdir_if_empty(p)` | `rmdir` under suppress | no-op (an empty prefix cannot exist) |
| `paths.read_table(p)` | `pq.read_table` | `pq.read_table(..., filesystem=s3fs)` |
| `paths.cached_listing(root)` | no-op passthrough | ONE recursive listing for the block |

Converted call sites: **`events.one_file`** (`shutil.move`/`shutil.rmtree` ->
`paths.move`/`paths.rmtree`; two lines), **`events.loaded_picks` / `warn_unloaded`**
(`pq.read_table` -> `paths.read_table`), **`gapfill.fill_day`** (the part is serialised to
a buffer and written as one object; the `_gapfill` marker is unchanged and still last),
**`stream.prune`**, and **`checks.write` with NO edit at all** - it was already
Path-method-only, so converting `mkdir` + `write_text` converted the whole check surface
with it. `daily.gaps()` opens a `cached_listing` scope.

### Atomicity: ordering, not a lock

cloud 09's frozen pattern, unchanged. A PUT is atomic and nothing here is
read-modify-write, so the only thing that had to be true is the ORDER:

- **gapfill**: every `part-gapfill-*.parquet` is PUT before any `_gapfill` marker.
  `missing_hours()` treats a marker-less hour as still missing, so an interrupted fill
  leaves debris the next run overwrites; a marker written first would retire an hour that
  was never filled.
- **`one_file`**: the whole partition is complete under `.staging/` (which `daily.gaps()`
  never looks at) before the ONE copy publishes `part-00000.parquet` - the exact object
  `gaps()` tests for. Interrupted before that copy, the day reads UNBUILT. Cleanup is last
  and cannot un-publish.

### Still refusing, deliberately

`replace`/`rename` above all (an object store has no rename - that IS the atomicity
problem), plus `unlink`/`rmdir`/`iterdir`/`read_text`/`read_bytes`/`stat`/`open`/`is_dir`/
`is_file`/`resolve`/`relative_to`/`with_name`/`samefile`. So these keep failing loudly on
a remote root: **`precip_live`** (out of scope by contract - `tmp.replace(out)` +
`shutil.rmtree`), **`export.write`** and **`live_export`** (`tmp.replace`),
**`stream.receipt`** (`tmp.replace`), **`archiver.flush`** (`tmp.replace`, and it runs on
the capture box's local disk by design), **`features`/`flood_*`/`ref`/`picks`/`nbp`/
`precip`/`schedule`** (`pq.write_table` to a path, which refuses via `__getattr__`), and
the **four other copies of the one_file dance** (`ref.py:96`, `schedule.py:162`,
`precip.py:236`, `flood_obs.py:456`) - each now a two-line conversion, but none of them
verified end-to-end here, so none of them claimed.

### `prune`: CONVERTED (the written decision)

`stream.py` already writes `live/` over s3a, so retention that only ran on the Mac would
let an R2 `live/` grow without bound - and the horizon comparison was always on NAMES, so
only the two POSIX calls had to move. `live/`-on-R2 is therefore unpinned FOR THE STREAM
HALF ONLY: `precip_live` still writes `live/precip_cell` with POSIX-only calls and stays
out by contract, so a fully shared `live/` is still one ticket away.

### The listing bill

Measured against the real bucket, not estimated. `daily.gaps()` over its real 14-day
window: **1,960 store list calls / 231.1 s -> 1 call / 22.4 s**, byte-identical day list.
The whole root is 35,658 objects in one call / 17.1 s. Fidelity checked directly: 31 of
the 1,080 distinct patterns `gaps()` issues, answered cached vs fresh against the live
bucket, **0 mismatches** (14 of them non-empty, so not vacuous). The cache is scoped and
NOT write-through - a write inside an open scope drops it - which keeps gapfill's
scan-to-write race check able to see an external writer.

### Two defects found by actually running it

1. **The s3a credentials provider has never existed.** `spark.py` configured
   `org.apache.hadoop.fs.s3a.auth.EnvironmentVariableCredentialsProvider`, an AWS-SDK-v2
   spelling absent from hadoop-aws 3.3.4 (what pyspark 3.5.3 requires and what the image
   bakes). It fails at s3a OPEN time with `ClassNotFoundException`, never at config time,
   so it shipped green through cloud 03, cloud 12 and the wave-2 gate. Fixed to the v1
   spelling `com.amazonaws.auth.EnvironmentVariableCredentialsProvider`; still the env
   provider, so no key reaches a config line. **This means no Spark job in this repo had
   ever touched R2 before today** - cloud 12's smoke was DuckDB httpfs, which uses its own
   credential chain.
2. **The Mac's Maven fallback carried no s3a jars.** `PACKAGES` listed sedona/geotools/
   kafka; the image baked hadoop-aws + aws-java-sdk-bundle via `RAINCHECK_JARS` and
   `jars_baked()` never checked them. New `S3A_PACKAGES`, added by the same
   `AWS_ENDPOINT_URL` switch that configures s3a (so a local-root run does not resolve
   300 MB of AWS SDK), and `jars_baked()` now checks all five.

### Acceptance, measured

- `events 2026-08-20` built END-TO-END onto `s3a://raincheck-bronze` from the Mac:
  `silver/leg_hours/service_date=2026-08-20/part-00000.parquet` (2,476,573 B),
  `silver/events/service_date=2026-08-20/part-00000.parquet` (53,970,809 B, **1,469,145
  rows, 0 pick_gap** - the schedule join ran over s3a), `silver/events_view.sql` (1,194 B,
  via `write_text`), and `.staging/` swept empty afterwards.
- `parity.compare('s3a://.../silver/events/service_date=2026-08-20', <local same-day
  build>)` -> **EQUAL**, 1,469,145 rows both sides, sha `0d688fc2…` both sides.
  `leg_hours` likewise **EQUAL**, 117,034 rows, sha `cb3a6f77…`.
- `daily.gaps()` on the remote root, closed 2026-08-20: 13 days remain and **2026-08-20 is
  gone**.
- Marker-last is pinned by driving the REAL `gapfill.fill_day` onto a fake store and
  asserting the store's own write log; the interrupted case (data present, marker absent)
  reads UNBUILT through the real `missing_hours`. **Mutation round, 5 mutations on a
  copied source tree, pristine control last: all 5 caught** (marker-first 1 fail; move
  that copies nothing 2; rmtree that sweeps nothing 2; `*` allowed to cross `/` 1; cache
  not dropped on write 1; control 26 passed).
- Cloud 12's refusal pin stays green, **narrowed by exactly five names** and the narrowing
  is documented in `tests/test_paths.py` itself.

### State changes made to shared infrastructure

- `silver/{trips,trip_stops,stops,service_days}` synced Mac -> `raincheck-bronze`
  (24 objects / 35 MB / 3.5 s). Both destination prefixes were measured EMPTY and a
  `--dryrun` was read first; zero overwrites. These are build INPUTS a cluster build pod
  needs in the bucket regardless - without them the remote build degrades to `pick_gap`
  rows and proves much less.
- The three `silver/` output objects listed above.

### One thing that is easy to get wrong

Comparing the R2 build against the Mac's EXISTING `silver/events/service_date=2026-08-20`
reported DIFFERS (1,469,145 vs 1,354,911 rows) and it was not a writer bug: that partition
was built 2026-08-22 20:19, and **16 gapfill parts landed in date=2026-08-20 / 2026-08-21
afterwards**. A stale artifact is not a parity counterpart - build the comparison side.
