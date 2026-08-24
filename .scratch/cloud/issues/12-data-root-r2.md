# T12 — The R2 data root and `ref/` delivery

Status: done (2026-08-24)
Type: task
Blocked by: none (T3 landed at the wave-2 gate; this ticket was chartered by Ross
2026-08-24 after the gate flagged the work as unowned)
Owns: the data-root seam — the one gap between "both engines are wired for R2" and
"a cluster pod actually reads or writes R2 tables". No spec § exists; this file is
the spec.

## Why this ticket exists

Cloud 03 wired BOTH engines for R2 (s3a in `spark.py` when `AWS_ENDPOINT_URL` is
set; DuckDB httpfs in `parity.py`) and both take explicit string roots. But
`paths.data_root()` returns a `Path`, and `Path("s3a://bucket/x")` collapses to
`s3a:/bucket/x` — so no stage can be POINTED at R2, cluster pods write their
ephemeral staging volumes, `live/` cannot be shared across pods, and `prune` stays
pinned. STATUS carried it as "[YOU] decide where it lands"; it lands here. It
blocks: `live/`-on-R2, unpinning `prune`, cloud 05's real behaviour, and cloud 10's
decommission (a Mac retired while builds write emptyDirs loses every build).

## Work

- Let the data root be an object-store URL without breaking the local case. The
  BARRED fix is recorded in KNOWN TRAPS: a `Path` subclass that re-expands on
  `__str__` leaves `.exists()`/`.glob()`/`.rglob()` answering about the LOCAL
  filesystem, after which `daily.gaps()` sees every service day as unbuilt and
  rebuilds the lot, silently. Whatever shape you pick (string root + helper seam is
  the lazy candidate), every path-consuming call site must either work identically
  on both root kinds or refuse loudly on the remote kind — never lie.
- Touch `paths.py` plus the join sites only; do NOT fork a stage module (the
  standing rule from cloud 03). Inventory the call sites first — `data_root()`
  consumers, `.exists()`/`.glob()` on root-derived paths — and publish the count in
  your RUN LOG entry so the next session knows the blast radius was measured, not
  guessed.
- **`precip_live` is explicitly OUT.** It writes with `mkdir`/`Path.replace`/
  `shutil.rmtree` and reads with `Path.glob` — POSIX-only — and cloud 05's contract
  is that it runs UNMODIFIED. Its R2 story (or shared-volume story) is a later
  decision; do not let this ticket grow it. TRAPS carries the full mechanism and
  the measured price of the emptyDir meanwhile (25x cold-start multiplier).
- **`ref/` delivery — the second half, same ticket.** Pods read `<root>/ref/*`
  (9 tables, 27 MB, gitignored, NOT rebuildable while `make picks` is
  401-blocked). Settle the mechanism in-session and record it: bake `ref/` into
  the image at build time (27 MB on a 3.26 GB image; `ref` changes rarely and
  `assets_version` is the drift canary; needs a build-context escape since ref/ is
  gitignored) vs an init-container pull from the cold bucket (needs the [YOU]
  `ref/` copy into R2 to have happened, and the `r2-build` token). Either way the
  live read path must be the SAME `<root>/ref` the Mac uses — no second path
  abstraction.
- Verification is runnable from the Mac TODAY: parity already reads the live
  bucket with the Mac's cold credentials (cloud 03 verified
  `compare('s3a://raincheck-bronze/archive/vp/date=2026-08-20', <local>)` EQUAL in
  22 s), so an end-to-end "stage reads an R2 root" proof needs no new token.

## Acceptance

- A stage module, unmodified, reads a table through an R2 data root from the Mac
  (own-module test + one real-root smoke against `raincheck-bronze`, read-only).
- `daily.gaps()` behaviour on a remote root is PINNED by a test that fails if
  `.exists()`-style checks silently answer about the local disk (the trap's exact
  failure mode, mutation-checked).
- The `ref/` delivery mechanism is decided, implemented, and recorded in this
  file, with the pod-visible path identical to the Mac's.
- KNOWN TRAPS' `paths.data_root()` bullet and STATUS's [YOU] paths item are
  updated to point here; cloud 05's and cloud 10's files get the forward-context
  note.
- Own-module tests only; the full suite stays gate-only (one-suite rule).


## Close-out (2026-08-24, branch `cloud12-data-root-r2`)

**What shipped.** `paths.data_root()` returns a `Path` for a local root and a
`RemotePath` for an object-store one (`s3a://` or `s3://`). `RemotePath` inherits
NOTHING - that is the whole design. It joins and stringifies like a Path, so every
`str(root / "silver" / t)` reaches the engines unchanged; it answers `exists()`,
`glob()` and `rglob()` against the STORE; and every other Path operation raises
`NotImplementedError` naming the root. The default is refusal, so an operation nobody
thought about cannot silently answer about the local disk - which is what the barred
`Path` subclass would have done. `paths.as_root()` replaces `Path(root)` at the join
sites, and `duck.connect()` now configures httpfs from `AWS_ENDPOINT_URL` (the same one
switch `spark.py`'s s3a branch reads), which is what lets a DuckDB stage follow an R2
root with no fork. `parity.remote` is now paths' definition re-exported - one answer to
"is this root an object store".

**Blast radius, MEASURED not guessed** (AST walk over `src/raincheck/*.py`, tainting
`data_root()` and every `root` parameter through assignment, `/`, `Path()` and f-strings):
**35 modules, 315 root-derived sites - 151 filesystem predicates, 99 stringify/interpolate,
65 pure path ops.** `.exists()` 43, `.mkdir()` 35, `.glob()` 19, `.write_text()` 12,
`.replace()` 9, `.rglob()` 6. The 99 stringify sites keep working; the 151 predicates
either work against the store (exists/glob/rglob) or refuse.

**READS work; WRITES refuse. This is the honest scope and it is narrower than the
ticket's framing.** Every writer here is POSIX-shaped (`one_file()` uses
`mkdir` + `shutil.move` + `rmtree`; Spark writes go through `df.write.parquet(str(...))`
on s3a and never touch `RemotePath` at all), and forking stage modules was barred. A
half-emulated write path is worse than none, so `mkdir`/`replace`/`write_*` raise. That
means **`live/`-on-R2 and unpinning `prune` are NOT unblocked by this ticket** - they
need a writer change, which is a separate ticket. What IS unblocked: a root can now BE an
R2 URL, no root-derived check lies, and read-only stages run against the real bucket.

**Real-root smoke, read-only against `raincheck-bronze`** (Mac cold credentials,
`RAINCHECK_ARCHIVE_ROOT=s3a://raincheck-bronze`):

| what | result |
|---|---|
| `eras.duck_columns(root, "vp", "2026-08-20")` - a stage module, unmodified | 15 columns, 15.5 s |
| rows in that Bronze partition, via `duck.table` | **5,597,465**, 35.0 s |
| `daily.gaps(root, 2026-08-20)` (1-day window) | `['2026-08-20']` - correct, silver/ is empty in the bucket - 18.9 s, **164 store list calls** |
| `(root/"archive"/"vp").rglob("*.parquet")` | 7,806 objects, 4.9 s, 1 call |
| `(root/"ref"/"assets").exists()` | `False` - and that is true, ref is not in the bucket |
| `mkdir` / `write_text` / `is_dir` / `replace` / `iterdir` | all `NotImplementedError`, 0 store calls |

The 164 calls are the POSIX loop shape (`gapfill.missing_hours()` asks per hour, per
marker), not the listing - one `rglob` over 7,806 objects is a single call. Recorded as a
`ponytail:` note in `paths.py` with the upgrade path (cache one recursive listing per
root) for whoever needs a build to run off an R2 root.

**A trap found while building it, now pinned by a test:** DuckDB's `glob()` returns a
WILDCARD-FREE pattern VERBATIM without touching the store - `glob('s3://bucket/nope')`
returns one row. An `exists()` written the obvious way would therefore say yes to
everything: the exact class of lie this ticket exists to prevent. `_store_glob()` refuses
a wildcard-free pattern, and `exists()` lists the PARENT and tests membership. One
wildcard anywhere makes DuckDB list and verify (`date=2026-08-2*/hour=00/part-NOPE.parquet`
-> 0 rows), which is what `glob()` relies on.

**The pin is mutation-checked in-suite.** `test_the_barred_path_subclass_fails_the_pin_above`
builds the barred `Path` subclass and runs `daily.gaps()` through it against the same
fixtures: both answers come off the local decoy and both are the OPPOSITE of the store's.
If that test ever stops failing the barred variant, the pin above has stopped
discriminating.

### `ref/` delivery: DECIDED - pull from the private bucket, never bake

`src/raincheck/refpull.py` (`python -m raincheck.refpull`), wired as an **initContainer**
on the four POSIX-rooted pods: `precip-live`, `raincheck-stream`, and both `build.yaml`
PodTemplates (`raincheck-stage`, `raincheck-spark`). It writes the SAME `<root>/ref` the
Mac uses; there is no second path abstraction, and a pod whose root is already the object
store gets a printed no-op from the same initContainer.

Baking was rejected for a reason that is not taste: **the image tag is a git sha and its
tags are immutable, so a 27 MB dataset that lives in no commit would make two builds of
one sha differ in content.** The Dockerfile already states the principle - "neither a
credential nor a data root is baked in". `ref` is data. Baking would also not have avoided
a pod-start step: the root is an emptyDir at `/data`, so an image layer at some other path
still has to be copied or linked into it.

`ref/src` is skipped: 23 of the 27 MB, the raw GTFS zips `ref` is BUILT from, read by
nothing outside `ref.py`. What a pod actually reads (assets, cell_pixel, cell_zone, cells,
zones, calendar, grids, picks) is **~4 MB**. The table list is read FROM THE BUCKET, never
declared in the module, so a table added by a later `make ref` travels on its own; what was
skipped is printed, never silent. Throughput proxy measured Mac -> R2 2026-08-24: s3fs
recursive get 5.5 MB in 0.39 s = 14 MB/s, so ~0.3 s for the ~4 MB - against a 0.70 s
steady-state tick, on a 300 s period.

`raincheck-live` deliberately has NO refpull init: it carries the SERVE token by design
(cloud 09 - one Secret, one ServiceAccount, and `raincheck-public` must never be the
archive bucket), and `live_loop` already catches a missing `ref/assets` as a thinner panel
rather than a stop. Pinned by `test_every_posix_rooted_pod_pulls_ref_before_it_starts`.

**It is DARK until two [YOU] steps land**, and it fails loudly at the initContainer rather
than as a `FileNotFoundError` halfway through a stage:

1. copy `ref/` into the private bucket - this session stayed read-only against
   `raincheck-bronze` by instruction, so the one line is Ross's:
   `aws s3 sync data/ref s3://raincheck-bronze/ref --endpoint-url "$RAINCHECK_COLD_ENDPOINT"`
   (with `RAINCHECK_COLD_KEY_ID`/`_SECRET` in `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY`
   and `AWS_DEFAULT_REGION=auto`). This also closes STATUS's "losing that disk loses the
   project" item - `ref/` stops existing on exactly one machine.
2. mint `r2-build` (the standing token item).

### Tests

`tests/test_paths.py` (29) + `tests/test_refpull.py` (5) + 2 rows on
`tests/test_cluster_manifests.py` (47 -> **49**) = **+36**. Own-module set run green:
323 passed / 0 failed / 0 skipped in 137 s over the 16 files touching these modules.
