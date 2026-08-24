# T12 — The R2 data root and `ref/` delivery

Status: open
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
