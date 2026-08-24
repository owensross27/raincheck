# 13 — The showcase surface

**What to build:** The portfolio view: Data Docs, a rendered DAG graph, a run summary and
a short written walkthrough, published as **static artifacts** — because the cluster has
no inbound path from the internet, so the Airflow UI is reachable by port-forward only
and cannot be the thing anyone is shown. Plus the one recorded run that demonstrates the
fan-out rather than asserting it.

**Blocked by:** 06 (fan-out), 08 (GX foundation).

**Status:** ready-for-agent

- [ ] Data Docs, a rendered DAG graph, a run summary and a written walkthrough publish to the public static host — never to the Bronze bucket
- [ ] Nothing in the portfolio view requires cluster access
- [ ] No published artifact contains feed payload; the no-payload rule on check rows is what guarantees it for the Data Docs
- [ ] One recorded run has an events map at least five Service dates wide, with its per-task durations exported
- [ ] The serial baseline is stated next to it — 1928 s for a 7-day catch-up in one session, ~275 s/day at steady state — so the improvement has a denominator
