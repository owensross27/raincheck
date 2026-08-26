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
