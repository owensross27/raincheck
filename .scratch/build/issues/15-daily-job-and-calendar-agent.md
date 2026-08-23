# 15 — Daily job and the 06:00 calendar agent

**What to build:** `make daily` builds every missing closed service day (events + leg_hours), refreshes the
current MRMS month and prunes the live tables, and a 06:00 America/New_York LaunchAgent runs
it so a day missed during sleep rebuilds itself. Spec: K.

**Blocked by:** 08, 11

**Status:** built — agent installed and verified on Ross's Mac

- [x] `daily` lists service_date= partitions under silver/events against Bronze-present dates (bounded, last 14 days) and runs `events DATE=` for each gap, then precip-hourly and precip-cell for src=mrms on the current month, then drops live date=/hour= dirs older than 48 h by name; running it twice does nothing the second time
      — `src/raincheck/daily.py` + `make daily`; second run 25 s, "0 service day(s) to build"
- [x] the StartCalendarInterval 06:00 America/New_York plist is installed (10:00Z clears Pass2's tail for the last service-day hour in both DST regimes) and a real run is verified in the log
      — `launchd/com.raincheck.daily.plist`, bootstrapped 2026-08-23; kickstart run green
      end to end in `data/logs/daily.log`
- [x] a test seeds two closed days and one built day under a temp root and asserts exactly the two gaps are built and the neighbour is untouched
      — `tests/test_daily.py` (10 tests, JVM-free); suite 209/209

## Scheduling note from ticket 20 (2026-08-23)

Order matters in the daily job: run `make gapfill` BEFORE `make gapcheck`. The newest
1-2 days legitimately fail gapcheck until gtfsrt.io publishes them (their lag) and the
fill lands — that exit 1 is actionable, not noise, and must not be allowlisted.
`gapfill.DEAD` (the dead-hour allowlist, 6efddaa) already keeps permanently-dead hours
from paging forever; entries are hand-added only, after probing gtfsrt.io shows zero
snapshots — never to quiet a failed fill.

## Implementation note (2026-08-23, agent)

`make daily` -> `python -m raincheck.daily`, a stage list, in this order:

    gapfill -> gapverify -> gapcheck -> coldpush -> coldcheck -> events(+gold) -> precip -> prune

The standing pieces run as their own make targets in a child process (`make -C <repo>
<target>`), so the Makefile stays the single place that knows JAVA_HOME, TZ=UTC and the
`.env` credentials — and `precip*.py` is called, never modified (ticket 11). Only the
events/gold build runs in-process, one Spark session for every gap day, and no session at
all on a day with no gaps.

**Every stage runs even when an earlier one failed**, and the job exits 1 naming the
failures. That is what makes ticket 20's ordering note liveable: gapcheck's exit 1 on the
newest day or two is real and reported (never allowlisted), but it must not cost the day's
build. Same reasoning inside the events loop — one poisoned service day is caught, logged
and skipped so the newer days still build.

`gaps()` is the only new logic worth its own name: the last 14 days (`WINDOW_DAYS`),
skipping today (a service day's last Legs land in the small hours of D+1, which is why
06:00 local works in both DST regimes), Bronze VP present, and either Silver partition
missing — so a run killed between the `leg_hours` and `events` writes rebuilds the day
rather than leaving it half-built. `gold` rolls only the months the built days touch;
`prune` is `stream.prune` (spec J's 48 h horizon, one implementation of it).

**coldcheck is the one soft stage.** Straight after a push it lists the parts the archiver
wrote during the sync (ticket 18's "expected drift"), so the job re-pushes once and
re-checks. What survives that is the EC2 box's own capture of the same window (ticket 19):
different bytes for an object that is present, which is overlap and not loss. It prints a
line pointing at `make coldgaps` — the check that can actually tell the two apart — and
never fails the job. `coldgaps` itself is deliberately NOT a stage here: it covers
`subway_vp`, which gtfsrt.io cannot backfill, so every Mac sleep gap would page forever.
It runs daily on the box (ticket 19's timer) and by hand from the Mac.

MRMS: `precip-hourly` then `precip-cell` for SRC=mrms, on the current UTC month — plus the
month just ended when today is the 1st, because Pass2's lag publishes a month's last hours
after that month's final daily run.

The agent runs `/usr/bin/make -C /Users/ross/raincheck daily` (not the module) so the
Makefile's environment block applies, and sets PATH to include `/opt/homebrew/bin`, where
the `aws` CLI that coldpush/coldcheck shell out to lives — launchd's default PATH has no
Homebrew. No `RunAtLoad`: catch-up is the calendar's job, and launchd coalesces the
intervals a sleeping Mac missed, which is the whole recovery story.

### Verified run (2026-08-23, via the installed agent)

`launchctl kickstart gui/$(id -u)/com.raincheck.daily`, log `data/logs/daily.log`:

    gapfill 4s -> gapverify 1s -> gapcheck 0s -> coldpush 8s -> coldcheck 4s
    7 service day(s) to build: 2026-08-15..19, 21, 22 (08-20 was already built, untouched)
    events ok in 1928s -> precip 2026-08 ok in 24s -> prune ok in 0s -> daily: OK

Left behind: `silver/{leg_hours,events}` for all eight live-era days,
`gold/cell_hour_speed/month=2026-08` and `gold/cell_hour_route/month=2026-08`,
`silver/precip_cell_hourly/src=mrms/month=2026-08`. A second `make daily` immediately
after: 25 s, "0 service day(s) to build", no JVM.

### Review fix: the service day is a local date (2026-08-23)

A three-lens adversarial review (19 agents) landed one high finding twice, from two
independent lenses: the gap window was dated off `utcnow() - 1 day`. launchd fires a
slept-through 06:00 interval **at wake, at whatever hour that is** — and `make daily` by
hand at 21:00 does the same thing — so between 20:00 local and midnight that subtraction
names the NY service day still on the road. `events.bronze_vp` reads `date IN (D, D+1)`
and exits only if BOTH are absent, so it would happily write Silver for a day missing its
whole evening, and `gaps()`'s existence test would then skip that day forever.

Fixed by `closed_through()`: the newest service day is local yesterday, or the day before
it when the run fires before 04:00 local (yesterday's tail is still out on the road until
~03:00). MRMS months stay UTC — that boundary is real and now commented at the call site.
Four parametrized cases pin it, including both DST regimes.

### Review fix: a day short of Bronze is deferred, not frozen short (2026-08-23)

The same review's second confirmed finding, and the sharper one. "Bronze-present" was
`any` part under `date=D`, but `events.bronze_vp` reads `date IN (D, D+1)` and a service
day's evening and late night live in the D+1 partition — measured on the real archive,
**31% of service day 2026-08-22's VP rows sit under `date=2026-08-23`, 10% of them in
hours 03-09Z alone**. Build a day while those hours are missing and `events` writes both
Silver partitions anyway; the done-test is bare existence, so the short day is permanent,
`gold` rolls it, and the board stays green. gapfill cannot save it either: its span ends
at `today - 1`, so on the morning that builds day D it structurally never touches D+1.

`gaps()` now also requires every Bronze hour the day is built from — all of D, plus D+1's
first `TAIL_H = 10` UTC hours (03:00 local in either DST regime) — using `gapfill`'s own
`missing_hours` marker convention, with `gapfill.DEAD` hours not counting against it. A
day short of Bronze prints a deferral line naming the hours and waits: gapfill runs first
in the same job, and the 14-day scan retries every morning, so the normal case costs one
morning and then builds complete. Checked against the real archive: all eight live-era
days report `unheld=0`, so this morning's build was already whole.

### Flagged, now fixed

`archiver.flush` writes each 10-min part straight to its final path
(`pq.write_table(table, out)`, no tmp + rename), while the daily build now reads *today's*
Bronze every morning — service day D reads `date=D` and `date=D+1`. A read that lands
mid-write sees a torn footer. Small window, real, and pre-existing (the slice reads live
partitions too); the fix is the two-line pattern `precip.hourly_mrms` already uses
(`out.with_name(out.name + ".tmp")` then `.replace(out)`). Fixed 2026-08-23 in
`src/raincheck/archiver.py` with exactly that pattern; `tests/test_archiver.py` pins it
(fails if flush writes into the final path), and the running daemon was kickstarted.
