# T11 — `raincheck.parity`: the content-equality seam

Status: done (branch cloud11-parity, a167b5c; landed to master at the wave-1 gate
2026-08-24; +9 tests in tests/test_parity.py)
Type: task
Blocked by: none
Owns: spec Testing Decisions, new seam 4.

## Close-out (2026-08-24, recorded by the wave-1 gate from the session's RUN LOG entry —
## the implementing session logged there but never marked this file)

- Shipped: `parity.digest(root) -> {partition: (rows, sha)}` — per-partition row count +
  sha256 over each row's md5 taken in HASH order; `parity.compare(a, b) -> Report`
  (`.ok/.only_in_a/.only_in_b/.differing/.matching/.lines()`), naming DIFFERS / MISSING ON
  A / MISSING ON B and never dropping a partition; CLI `python -m raincheck.parity A B`,
  rc 0 equal / 1 differ / 2 INCONCLUSIVE (unreadable root OR corrupt parquet — duckdb.Error
  is caught, so bad data never renders as "differ").
- Reads with DuckDB, not Spark: JVM-free, digests whatever wrote the files, and streams
  (fetchmany) so a millions-row Silver partition never materializes.
- The footer fact is now MEASURED here, not just cited: two separate JVM sessions writing
  identical rows produced different parquet bytes and an equal digest (side B written from
  a subprocess Spark session — newSession() would share the JVM and prove nothing).
- DuckDB SQL cannot carry control chars in quoted literals: the row separator / NULL
  marker are chr(31)/chr(30) SQL calls. NULL is marked, not skipped, so
  ('a',NULL) != (NULL,'a'). An unpartitioned root digests as one partition named "";
  empty partition = (0, parity.EMPTY).
- LIMIT: local paths only — no S3/R2 listing. If a gate must digest R2 directly, cloud 03
  adds remote listing to THIS module; never fork it.

**Do this early.** Tickets 03, 04 and 10 all block on it, and it is the only one of the
twelve that is plain Python plus Spark — no cluster required to write or test it.

## Why it is its own ticket

Three consumers need the same answer to "are these two builds the same?": the cluster
parity gate (03), the capture-placement gate (04), and the Mac decommission gate (10).
One module, one seam. Burying it inside 03 would hide that 04 and 10 depend on it.

## Interface

- A **digest over a partitioned table** returning, per partition, the row count and a sha
  over its sorted rows.
- A **comparison** that names which partitions differ and how.

## Why not bytes

Byte comparison is wrong here and would fail on correct builds: parquet-mr permutes footer
encoding order across JVM sessions (~27 bytes, data pages identical) [F01, T02], and a
cluster run is by construction a different session than `make daily`.

## Tests

- the same data written by two different Spark sessions digests **equal** — the footer
  permutation case that byte comparison fails;
- a single changed value changes the digest;
- row order and column order do not change the digest;
- a partition present on one side and absent on the other is **reported loudly**, never
  skipped;
- an empty partition is distinguishable from a missing one.

Prior art: `tests/test_daily.py` (stub the make targets and the Spark build, run the driver
for real, JVM-free where possible).
