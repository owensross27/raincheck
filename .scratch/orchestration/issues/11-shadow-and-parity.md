# 11 — Shadow mode and the parity gate

**What to build:** The DAG runs beside the LaunchAgent for a shadow period and proves it
builds the same data — **into a shadow data root**, with the mutating stages disabled.
Shadowing against the live tree would mean two writers on one Bronze, which is a data
event, not an experiment. Parity is content equality (row counts plus a sha over sorted
rows per partition), never bytes: byte-identity holds only within one JVM session, and a
DAG run is by construction a different session than the LaunchAgent's.

**Blocked by:** 05 (the nightly DAG), 06 (fan-out) — so the shadow tests the shape that
will actually run. **External:** the shared parity module declared by the cloud effort.

**Status:** ready-for-agent

- [ ] The shadow DAG writes to a shadow data root and never touches the live Silver, Gold or live prefixes
- [ ] The fill, the cold push and the live-table prune are disabled in shadow mode, and the run says so rather than silently skipping them
- [ ] Parity is content equality per partition, computed by the shared parity module; if it has not landed from the cloud effort, build it to that interface — never a second implementation
- [ ] The gate names which partitions differ and how, and refuses to certify a day where a partition exists on one side only
- [ ] Each shadow day records **two independent proofs**: per-partition content equality, and outcome equality between the two runtimes' check rows
- [ ] The ticket states in writing which stages shadowing cannot prove — the three mutating ones — and how they get proven after cutover
