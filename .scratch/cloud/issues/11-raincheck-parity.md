# T11 — `raincheck.parity`: the content-equality seam

Status: open
Type: task
Blocked by: none
Owns: spec Testing Decisions, new seam 4.

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
