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

## Inherited from orchestration 03 (landed 2026-08-24, b37a761)

Both of this ticket's non-fidelity suites now have their producers shipped — expect on
these rows, do not re-derive the checks.

- **Cold mirror**: check `coldcheck`, columns `CORE + ("kind", "differing")`, **one row
  per top-level `archive/` prefix**, read off disk — the row set grows with a new kind,
  so expect on the shape, not on a fixed kind list. `differing` is **NULL, never 0**, on
  every could-not-check path (aws non-zero, unconfigured, nothing local to mirror, no
  `archive/` at all). Reports, never gates — that placement is unchanged.
- **Schema eras**: check `eras`, columns `CORE + ("reader", "kind", "day", "era_cols",
  "missing")`, **four rows every run** — subjects `duck vp`, `spark vp`, `duck tu`,
  `spark tu`. Expect on `missing == ""` (column PRESENCE). A row whose `day` is NULL is
  INCONCLUSIVE: no date dir mixed part schemas, so the run could not tell a union reader
  from a narrow one, and it must not read as a pass. `eras.ERA_COLS` is the one home for
  the column names — expect through it, never a restated list.
- **This ticket also decides the era check's placement.** `make eras` exists; it is not
  in `daily.STAGES` today (adding it moves daily's printed stage list).
- Reading the batch: `make <check>` returns 0 or 2 for everything, because GNU make
  exits 2 on any recipe failure. Use the module or the persisted rows.
