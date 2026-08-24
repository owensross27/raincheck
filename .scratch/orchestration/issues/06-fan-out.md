# 06 — Fan-out

**What to build:** The independent work runs in parallel. One task per Service date for
the events build, one per feed kind for the fill and its verifier, and the monthly rollup
stays a single reduce behind the mapped days — it is not mappable and is not mapped. The
measured case this exists for: a 7-day catch-up that ran serially in one session in
1928 s, ~275 s/day at steady state.

**Blocked by:** 05 (the nightly DAG).

**Status:** ready-for-agent

- [ ] The events build maps over the Service dates the gap scan returns, one pod per day
- [ ] The fill and its verifier map over the five recoverable feed kinds (disjoint Bronze prefixes, safe to parallelise)
- [ ] The monthly rollup is a single non-mapped reduce over the months the **successfully built** days touched — a failed day cannot pull its month into Gold
- [ ] The cold push runs only after every mapped fill has finished
- [ ] An expansion to zero days is a clean skip and the run stays green — a morning with no gaps is not an alert
- [ ] A killed mapped events task is safe to re-run (dynamic partition overwrite is already configured in the session factory)
- [ ] The structure test asserts the three mapped stages are mapped and the rollup is not
