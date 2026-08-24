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

## Forward context from cloud 12 (2026-08-24, `cloud12-data-root-r2`)

**The paths precondition is HALF closed - read the halves before starting the checklist.**

CLOSED: `paths.data_root()` can now hold an object-store root (`s3a://raincheck-bronze`),
and no root-derived check lies about it. Read-only stages run against the real bucket from
the Mac today - `eras.duck_columns` read a Bronze partition's schema through an R2 root,
`duck.table` counted 5,597,465 rows in it, `daily.gaps()` answered from the STORE, and
every POSIX operation refused with `NotImplementedError` instead of answering about local
disk. Pinned, mutation-checked, in `tests/test_paths.py`.

**STILL OPEN, and it is this ticket's actual precondition: WRITES.** A build pod pointed at
an R2 root now fails loudly at its first `mkdir` rather than writing an emptyDir - honest,
but not writing to R2 either. `raincheck-stage` / `raincheck-spark` therefore still write
`/staging` (emptyDir), so **"a Mac retired while builds write ephemeral staging loses every
build" is still true.** Closing it needs a ticket that changes the WRITERS
(`events.one_file`'s `mkdir` + `shutil.move` + `rmtree`, and the Spark write path), which
cloud 12 was explicitly barred from doing (no stage-module forks). Do not read cloud 12's
RUN LOG entry as clearance for this ticket's checklist.

**`ref/` archival:** cloud 12 decided and implemented the delivery mechanism (a `refpull`
initContainer pulling from the private bucket - never baked into a git-sha-tagged image),
so the remaining step is the [YOU] one-liner that puts `ref/` in the bucket:
`aws s3 sync data/ref s3://raincheck-bronze/ref --endpoint-url "$RAINCHECK_COLD_ENDPOINT"`.
Until that runs, `ref/` still exists only on the Mac and retiring it still deletes the
project.
