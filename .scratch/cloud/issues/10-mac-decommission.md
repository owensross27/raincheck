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
**CORRECTED AT THE WAVE-6 GATE (PART 2, 2026-08-26) — THAT ONE-LINER HAS RUN. `ref/` IS IN
THE BUCKET AND THE MIRROR WAS COMPARED OBJECT BY OBJECT, NOT ASSUMED:** `s3://raincheck-bronze/ref/`
holds **16 objects / 28,079,794 B** and `data/ref` holds the same 16 names at the same 16 sizes
(a name+size diff of both listings is EMPTY). The sentence this replaces — "`ref/` still exists
only on the Mac and retiring it still deletes the project" — was stale from cloud 12's addendum
onward and is retired.
**WHAT IS STILL TRUE, AND IT IS A DIFFERENT RISK: `ref/` CANNOT BE REBUILT, ONLY RESTORED.**
`make picks` is 401-blocked (re-confirmed by orch 10), so R2 + this Mac are the only two copies
and there is no third path back if both go. That is why the Interline grant's **HARD DATE
2026-09-30** is a [YOU] item and why `data/ref` (27 MB) is on the NEVER-DELETE list even though
it is backed up. Restoring is `aws s3 sync s3://raincheck-bronze/ref data/ref --endpoint-url
"$RAINCHECK_COLD_ENDPOINT"`.


---

## MUST — GET THE DATA ROOT OFF THIS MAC (filed by the WAVE 6 GATE, PART 2, 2026-08-26)

**THE DRIVER IS ROSS'S, IN HIS OWN WORDS (2026-08-25): "we have no space on the computer —
ensure we are only using S3 or R2 when pulling data locally."** This is not a tidiness note.
The disk hit **100% / 253 MiB free of 228 GiB** during the wave-6 gate's PART 1, which is what
stopped Docker Desktop, which cost the wave its image build and its Kafka broker (7 tests
unrun until PART 1's addendum recovered them).

**THE REDIRECT MACHINERY ALREADY EXISTS AND IS NOT THE BLOCKER.** `paths.data_root()`
(`src/raincheck/paths.py:65`) honours `RAINCHECK_ARCHIVE_ROOT`, and `paths.remote()`
(`src/raincheck/paths.py:46`) resolves an object-store root — both landed with cloud 12 and are
mutation-checked in `tests/test_paths.py`. **The ONLY thing keeping the root on this Mac is the
four writers that still refuse a remote root, plus GX Data Docs. The five line references,
RE-READ AND RE-PINNED ON MASTER `39beac4` AT THIS GATE so nobody re-greps for them** (the
wave-5/6 ledgers cite the block-start lines; these are the exact `shutil` pairs):

| file | exact lines | what it does |
| --- | --- | --- |
| `src/raincheck/ref.py` | **96-97** (block from :94 `mkdir`) | `shutil.move` + `shutil.rmtree` |
| `src/raincheck/schedule.py` | **162-163** (block from :160) | `shutil.move` + `shutil.rmtree` |
| `src/raincheck/precip.py` | **236-237** (block from :234; a third `rmtree` at :73) | `shutil.move` + `shutil.rmtree` |
| `src/raincheck/flood_obs.py` | **456-457** (block from :454) | `shutil.move` + `shutil.rmtree` |
| `src/raincheck/gx.py` | **782-786** | `if paths.remote(root) is not None: raise ValueError("gxcheck: Data Docs are POSIX-only …")` |

**DO NOT START THIS AT A GATE, AND THE WAVE-6 GATE DID NOT: a half-converted root is worse than
an unconverted one.** It is cloud 10's writer scope, it needs its own tests, and the four
writers are the `one_file` sibling shape — convert them together or not at all.

**WHAT THE WAVE-6 GATE ALREADY DID, so this ticket does not redo it:** `data/archive` (**6.24
GiB**) was RECLAIMED after `python -m raincheck.daily coldcheck` was re-run and wrote batch
**`data/checks/check=coldcheck/run=20260826T015952Z.jsonl` — 11 rows, every one `ok`,
`differing: 0`** — and the R2 mirror was inventoried at **37,034 objects / 43.71 GB**, a strict
superset of the local 12,607 / 6.24 GiB. `data/` went **11.94 GB -> 5.70 GB**.

**THE TWO THINGS THAT RECLAIM MEASURED, WHICH THIS TICKET INHERITS:**
1. **`cold.kinds(root)` (`src/raincheck/cold.py:35-40`) READS THE LOCAL DISK**, so with
   `data/archive` gone `make coldcheck` now reports **ONE INCONCLUSIVE row — "no local Bronze
   under /Users/ross/raincheck/data/archive to mirror", rc 2** (verified at the gate). That is
   the module's own guard working and NOT a false OK — but note the direction: **the check
   proves local ⊆ remote, so once local is empty it is vacuously true.** A prefix that
   disappears locally is invisible to it, not a gap. If the durable root becomes R2, this check
   needs a new question or it measures nothing.
2. **THE RECLAIM IS SELF-REVERSING ON THIS MAC AND THE LAUNCHAGENTS ARE WHY.**
   `com.raincheck.archiver` is LIVE (`launchctl list` -> pid, `KeepAlive`) and writes new hours
   into `data/archive` continuously; `com.raincheck.daily` fires at **06:00 local** and runs
   `gapfill`, whose **`START = date(2026, 8, 15)`** (`src/raincheck/gapfill.py:40`) makes it
   re-download every hour from 2026-08-15 to yesterday from gtfsrt.io's public GCS Parquet
   archive. Measured split of the 6.24 GiB deleted: **2021 backfill 1.24 GB · 2023 backfill
   1.29 GB · 2026 live window 2.73 GB · undated (precip grids, flood, static) 1.41 GB.** Only
   the **2.73 GB** 2026 slice is inside gapfill's horizon, so **~2.7 GB regrows overnight and
   ~3.5 GB stays reclaimed** unless the agents are stopped or `START` moves. **Stopping them is
   Ross's call, not a ticket's** (`launchctl bootout gui/$(id -u)/com.raincheck.daily`), and
   moving `START` would silently disable gap recovery — NAMED here, NOT taken.

**NEVER DELETE, and this is a hard list:** `data/ref` (27 MB — mirrored, but **not rebuildable**;
`make picks` is 401-blocked and the Interline grant's hard date is **2026-09-30**),
`data/live`, `data/checks`, `data/checkpoints` (tiny, and live state). `silver` / `gold` /
`snapshots` / `alt` are DERIVED and rebuildable but cost the **1928 s serial baseline** to
rebuild — reclaim only under real disk pressure, and say so if you do.
