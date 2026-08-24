# 02 — Check-result rows and the third outcome

**What to build:** The gap checks stop being exit codes with print statements and start
returning rows. Each row names what was checked, the outcome (`ok` / `fail` /
`inconclusive`), and the measurements behind the verdict. The CLI prints the same lines
it prints today and exits 0/1/2 on an aggregation rule. This is the seam the DAG branches
on and the suites validate, and it fixes a live bug on the way: the fill verifier
currently returns 0 when it finds no filled/captured hour pair to compare — a check that
verified nothing reports OK.

**Blocked by:** None — can start immediately.

**Status:** done — branch `orch02-check-result-rows`, 6a43e84. See the runbook's RUN LOG
entry (2026-08-24) for the shipped `raincheck.checks` signatures.

- [x] The hour-completeness check returns one row per feed kind x closed day, carrying hours held, fillable misses, DEAD-covered misses and any stale DEAD entry
- [x] The fill verifier returns one row per feed kind, carrying the pair it compared, row counts, distinct-key coverage and the schema verdict
- [x] A verify run that found no filled/captured pair on any day yields exactly one
  `inconclusive` row and can never yield `ok` — **read as PER KIND** (the item above
  binds: one row per feed kind, always), so an all-kinds run on a tree with no pairs
  anywhere returns five inconclusive rows and rc 2, and a single-kind run returns one
- [x] Printed output is unchanged for every state that already produces a line
- [x] Aggregation: rc is 1 if any row failed, else 2 if any row is inconclusive, else 0 — an inconclusive alongside a failure is still 1, because a known gap outranks a not-run check
- [x] The row column set is declared and carries no feed payload — counts, dates, kinds, hour labels, ratios and shas only
- [x] Each run's rows persist under the data root so a later suite has a batch and a summary has a source
- [x] Tests: a real fillable gap yields `fail`; a DEAD-only miss yields `ok` with the dead hours still reported; a DEAD entry whose hour is present yields `fail`; nothing to compare yields `inconclusive`; every aggregation case
- [x] A test asserts the batch's column set equals the declared one and contains no payload column
