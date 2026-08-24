# T10 — Mac decommission gate

Status: open
Type: task
Blocked by: 03, 05, 06, 09, 11
Owns: spec §10.

## Work

A **T19-style fail-closed checklist per remaining Mac daemon** — `precip-live`, `daily`,
the export loop. Each retires only on:

- proven cluster parity by **content equality** (`raincheck.parity`, ticket 11),
- **two independent proofs per day**,
- **seven clean days**, matching T19,
- an explicit acknowledgement that **the Mac backstop is gone** — so unlike T19, there is
  nothing behind this gate if it is wrong.

Every failure mode fails **closed**: unreachable cluster or unreadable evidence means the
gate is not met and the Mac daemon keeps running. Follow `scripts/cutover.sh`'s shape,
including its two-independent-proofs reasoning about what one source can forge.

The Mac ends as a **dev checkout, not a runtime**.

## Also in scope: T16 submit-or-close

The Interline/Transitland grant, outstanding since 2026-08-16, is **submitted or closed by
2026-09-30**, defaulting to its recorded fallback (archive-era Delay columns NULL) [T16].
A date, not a someday.

## Tests

New shell gates follow `tests/test_cloud_scripts.py`'s pattern: stub binaries on `PATH`,
run the script in a subprocess with `cwd=/` to prove cwd-independence. **Stub `kubectl`
the way that file stubs `aws`, copying real tool output verbatim** — a wrong-format stub
has kept a data-loss bug green in this repo before.

The cutover gates themselves are **evidence, not tests**, and are not claimed as test
coverage.
