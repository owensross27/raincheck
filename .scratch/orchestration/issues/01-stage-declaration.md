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

**Status:** done — branch `orch01-stage-declaration`, ad060df. See the runbook's RUN LOG
entry (2026-08-24) for the shipped `daily.Stage` / `daily.STAGES` shape and the two notes
tickets 05/06 must honour.

- [x] Every nightly stage's name, entrypoint (make target or module), soft flag, fan-out axis and retry class live in one module-level declaration — `daily.STAGES`, a tuple of `Stage(name, entrypoint, retry, soft, fanout)`
- [x] The daily driver builds its step list from that declaration and names no stage inline — `steps()` expands it, `call()` binds each entrypoint by its own signature
- [x] `make daily` is behaviourally identical: same printed lines, same order, same exit sentence naming failed stages, `coldcheck` still soft — verified by DIFF, not by eye: the pre-refactor driver and this one under identical stubs and a seeded tmp root produce byte-identical stdout and exit sentence on a green run and on a red one (gapcheck + precip-cell failing)
- [x] Every existing test in the daily driver's test module passes **unmodified** — that is this ticket's gate, not a nice-to-have: `tests/test_daily.py` 16 -> 20, the diff on that file is append-only (+43, 0 deletions)
- [x] The existing "gapfill runs before gapcheck" assertion reads the declaration, so it covers both runtimes once the DAG exists — **read as an ADDITIONAL assertion.** The item above binds: the existing `test_gapfill_runs_before_gapcheck` is untouched (it still pins the driver's real make calls, which is what proves the declaration is wired to behaviour). The declaration-level assertion is a second test, `test_the_declaration_pins_gapfill_before_gapcheck`, and it is the one the DAG's structure test should reuse
- [x] No stage logic moves: the gap scan, the closed-service-date rule and the per-month precip expansion stay exactly where they are — `gaps()`, `closed_through()`, `months()`, `precip_months()`, `build()`'s day loop and its gold reduce are byte-identical
- [x] A test asserts every declared stage resolves to an entrypoint that exists — no dangling stage — `test_every_declared_stage_resolves_to_an_entrypoint`: `make:` refs are matched against the Makefile, `py:` refs must resolve to a callable

**Two caveats tickets 05/06 inherit:**

- **`gold` is deliberately NOT a declared stage.** In the driver it is the reduce inside
  `build()` over `months(built)`, so declaring it would give `make daily` a printed line
  it does not have today and break the behavioural-identity gate. Spec §3's mapping table
  lists it as a DAG task — split it out there, on the DAG side.
- **A declared fan-out axis is not an expansion.** `steps(ctx, axes)` maps a stage only if
  that runtime supplies items for its axis; `make daily` supplies `{"month": ...}` only,
  so `gapfill`/`gapverify` (axis `kind`) and `events` (axis `service_date`) stay single
  steps that fan out inside themselves. Ticket 06 supplies those two axes and gets pods
  without touching the declaration.
- One deliberate strengthening: the runtime now honours `soft` (a failing soft stage no
  longer joins the failed list). No observable change today — `coldcheck()` returns 0 on
  every path — and `test_a_soft_stage_that_fails_does_not_fail_the_job` pins it.
