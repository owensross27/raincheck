# 12 — Cutover: retire the 06:00 LaunchAgent

**What to build:** The nightly stops being a laptop's job. After seven clean shadow days
with two passing proofs each, the LaunchAgent is retired and the DAG becomes the single
owner — and the morning after gives the proofs shadowing structurally could not: the
mutating stages verified by their own checks, with exactly one writer running.

**Blocked by:** 11 (shadow mode and the parity gate).

**Status:** ready-for-agent

- [ ] Seven clean shadow days, two passing proofs each, recorded rather than remembered
- [ ] The 06:00 LaunchAgent is retired and the DAG owns the nightly, with exactly one writer against Bronze and the object store
- [ ] The morning after cutover: hour completeness green with the Mac stopped, cold mirror green after the push, and the 48 h live horizon verified by listing
- [ ] The retirement is added to the Mac decommission checklist in the cloud effort — this ticket does not open a second checklist
- [ ] Rollback is one `launchctl` command and is written down before the agent is booted out
- [ ] The daily make target stays runnable unchanged, so the escape hatch is real

## From orch 13's landing (2026-08-25, `orch13-showcase-surface`) — one line of yours

When a real nightly has run under your cutover, re-record the showcase's run so the public
surface stops showing a probe: `python -m raincheck.showcase --logs <dir> --label nightly`,
commit the `research/orch-13-run-<run_id>.json` it writes, `make showcase`,
`make publish FAMILY=showcase`. `--label nightly` is the only label that lets the page drop
its "this is not the fan-out at its declared width" caveat, and it drops it only when the
run's own `totals.widest_map` is five or more - which is measured from the logs, not typed.
