# 01 — Stage contract as one declaration

**What to build:** The nightly stage contract — the order, which stages are soft, which
fan out and over what, and each stage's retry class — becomes one declaration that a
runtime builds its steps from, instead of a step list written inline in the daily
driver's `main()`. Running `make daily` behaves exactly as it does today. This is the
prefactor that lets the DAG orchestrate the same contract without a second
hand-maintained copy of it; stage order here is load-bearing (gapfill strictly before
gapcheck, because the newest 1-2 days legitimately lag gtfsrt.io's publish), and two
copies is how that note gets lost in one of them.

**Blocked by:** None — can start immediately.

**Status:** ready-for-agent

- [ ] Every nightly stage's name, entrypoint (make target or module), soft flag, fan-out axis and retry class live in one module-level declaration
- [ ] The daily driver builds its step list from that declaration and names no stage inline
- [ ] `make daily` is behaviourally identical: same printed lines, same order, same exit sentence naming failed stages, `coldcheck` still soft
- [ ] Every existing test in the daily driver's test module passes **unmodified** — that is this ticket's gate, not a nice-to-have
- [ ] The existing "gapfill runs before gapcheck" assertion reads the declaration, so it covers both runtimes once the DAG exists
- [ ] No stage logic moves: the gap scan, the closed-service-date rule and the per-month precip expansion stay exactly where they are
- [ ] A test asserts every declared stage resolves to an entrypoint that exists — no dangling stage
