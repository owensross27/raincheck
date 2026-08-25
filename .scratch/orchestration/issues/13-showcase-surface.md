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


## Forward context from frontend 06 — the showcase has a front door (2026-08-25)

Landed on branch `frontend06-discovery-contract` (`8bd82db`).

**Link the contract; do not restate it.** `files/index.json` on the public host is the
machine-readable read contract — every family with its keys, content type per key, schema
pointer, cadence, writer, `Cache-Control` and gate state, the version stamps, and
`contract`, an integer a consumer refuses on. `docs/read-api-contract.md` is its human
half. Your walkthrough links both. A hand-written second copy of the family table drifts
from the generated one on the first landing, and the generated one is derived from
`publish.FAMILIES` so it cannot.

**Your `docs/**` family is already IN that contract** — a TREE family, `public,
max-age=300`, written by "the GX checkpoint's Data Docs task [orch 08]". The file names
inside the tree are yours to make and adding them owes no contract bump. What WOULD be
breaking is renaming the `docs/` prefix or moving the family, which turns
`tests/test_publish.py::test_the_contract_integer_covers_the_surface_a_consumer_binds_to`
red and demands a bump.

**Nothing is published yet** — `raincheck-public` does not exist. That is a [YOU] item in
STATUS, not your blocker to solve.
