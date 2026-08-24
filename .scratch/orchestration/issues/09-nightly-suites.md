# 09 — The remaining nightly suites

**What to build:** The other invariants that run every night become named suites —
fill fidelity, the cold mirror, and schema eras — each with its placement stated: a gate
inside the DAG, or a post-run report. One trap to avoid: the map quotes a 0.85-1.2x
same-day band for fidelity, but that is a **measured result** from the backfill work, not
the threshold the module enforces (which is roughly an order of magnitude on rows and ~3x
on key coverage). A suite that expects tighter than the code makes the suite the real
gate and silently changes what passes.

**Blocked by:** 03 (remaining check producers), 08 (GX foundation).

**Status:** ready-for-agent

- [ ] A fidelity suite expects on the verifier's rows at the bands the module actually enforces — non-empty filled hour, row-count ratio and distinct-key coverage in band, archiver columns present as a typed superset
- [ ] It fails when a kind is inconclusive on a day that **has** both a filled and a captured hour — an inconclusive there means the pair-finding broke
- [ ] Tightening the band to the observed figure, if wanted, is raised as its own evidence-backed change to the module; this suite does not tighten it on the side
- [ ] A cold-mirror suite reports and never gates
- [ ] A schema-era suite expects column **presence**, not counts
- [ ] Each suite records its placement explicitly: in-DAG gate or post-run report
