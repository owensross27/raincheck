# 20 — Gap backfill from gtfsrt.io: recover the sleep-gap hours

**What to build:** A gap-fill job that recovers the hours the laptop archiver missed while
asleep, from gtfsrt.io's public keyless Parquet archive on GCS (inventory:
`storage.googleapis.com/download/storage/v1/b/parquet.gtfsrt.io/o/inventory.json?alt=media`;
data: `storage.googleapis.com/parquet.gtfsrt.io/<feed_type>/date=<date>/base64url=<b64>/data.parquet`,
b64 = base64url of the feed URL). Coverage verified live 2026-08-23: bus VP/TU/alerts and
all eight subway TU feeds + subway alerts, 2026-03-01 -> ~yesterday (1-2 day lag).

**Measured gaps (2026-08-23):** bus VP hour-dirs per day since capture began:
15th 8/24, 16th 8/24, 17th 24, 18th 24, 19th 11/24, 20th 14/24, 21st 18/24, 22nd 21/24 —
roughly 40% of live hours missing. Subway VP is NOT archived by gtfsrt.io (only TU); those
hours are unrecoverable — record and accept (subway TU carries the delay signal; noted for
the flood map's impact-signals ticket).

**Blocked by:** None. Sequencing: run once now for 08-15..today, then re-run after ticket
19's box is live to close the final seam; retire (or keep as the standing gap-repair tool —
ponytail says keep, it is the recovery path for any future outage).

**Status:** resolved

- [x] schema probe first (one day, one feed): map gtfsrt.io's Parquet columns onto the 05
      decoder's Bronze schema; every Bronze column must be derivable or explicitly NULL
      with a note. If their rows are per-entity snapshots, dedupe with the same
      header.timestamp rule as the archiver.
- [x] `make gapfill FEED= DATE=` (or one `gapfill` driver over a date range): downloads the
      day's parquet, extracts ONLY the missing hours (never overwrites hours the archiver
      captured — our capture wins), writes them as Bronze hour-dirs in the standard layout,
      marks provenance (`src=gtfsrt.io` column or a `_gapfill` marker file per hour-dir).
- [x] scope: bus vp/tu/alerts + subway_tu + subway_alerts, 2026-08-15 -> present; subway_vp
      excluded (unavailable, see above).
- [x] after fill: `make coldpush` and the hour-completeness check (19's check; if 19 has
      not landed, a one-off version here) show every closed day complete for the five
      recoverable feeds.
- [x] one runnable check: for one filled hour, row counts and key coverage are sane vs an
      adjacent archiver-captured hour (same feed, same day) — loud if the filled hour is
      empty or wildly off.

## Answer

Built `src/raincheck/gapfill.py` (`make gapfill` / `gapcheck` / `gapverify`, appended at
Makefile end) + `tests/test_gapfill.py` (13 offline tests against a file:// fake of the
GCS layout; mapper schemas censused against `archiver.flush` on the pb fixtures).

**Schema probe findings (live, 2026-08-23):** every gtfsrt.io file is one row group per
poll snapshot with `feed_timestamp` (= header.timestamp) and `fetch_timestamp` constant
per group and present in row-group stats — so the fill range-reads only the missing
hours' row groups, dedupes on header.timestamp and thins to the archiver's poll cadence
(their 20-30 s vs our 30-300 s), making filled hours materially equivalent to archiver
hours (gapverify ratios 0.85-1.2x on rows and distinct keys). TU comes pre-flattened per
StopTimeUpdate, alerts per informed_entity. Explicit NULLs with a note: subway TU's NYCT
extension (`train_id`, `direction`, `is_assigned`, `scheduled_track`, `actual_track`) is
not archived by gtfsrt.io. Provenance: `part-gapfill-<feed>.parquet` names + an empty
`_gapfill` marker per fully-filled hour; the fill never writes into an hour-dir holding
any non-gapfill part (verified post-run: zero archiver files modified).

**Run results (2026-08-24 UTC):** 354 hours recovered — vp 61, tu 62, alerts 78,
subway_tu 76 (x8 feeds = 608 parts), subway_alerts 77. Every closed day 08-15..08-21 is
24/24 for all five kinds except gtfsrt.io's own dead hours (zero snapshots at source,
unrecoverable, listed so nobody mistakes them for a fill bug): **subway_alerts 08-15
hours 07 and 12; subway_alerts 08-16 hour 13**. Window completeness 08-15..21: 837/840
hour-slots = 99.6%. 08-22 was unpublished at run time (their 1-2 day lag): vp/tu/
subway_tu missing 04,06,10; alerts +14,15; subway_alerts +14,15,18 — no markers written,
so a plain `make gapfill` re-run closes it once published (the standing gap-repair path;
kept per ponytail, also the recovery tool for any future outage).

**08-22 seam closed (2026-08-23 13:30Z re-run):** gtfsrt.io published it; a plain
`make gapfill` recovered 19 more hours (vp 3, tu 3, alerts 5, subway_tu 3, subway_alerts
5) with no other change — the re-run path works as designed, and these parts carry the
canonical post-10 schema (verified on disk). Totals now **373 hours / 926 parts**,
archive 4.3 GB. gapverify OK on all five kinds, coldpush + coldcheck OK (remote proven).
**Final window completeness 08-15..08-22: 956/960 = 99.6%**, the only misses being
gtfsrt.io's four dead hours: **subway_alerts 08-15 h07, 08-15 h12, 08-16 h13, 08-22 h18**
(zero snapshots at source — unrecoverable, not a fill bug). Every other kind x day in the
window is 24/24.

**Wild-data cases handled (tests pin both):** one snapshot/day can carry an all-NULL
`fetch_timestamp` (skipped with a counted note); stats-absent row groups fall back to
reading just the two timestamp columns. Discovered in passing: live vp parts
08-15..08-22 lack `schedule_relationship` (the daemon ran pre-ticket-07 code until the
08-23 restart) — vp Bronze has two part schemas independent of this fill; gapverify
therefore requires archiver-columns ⊆ filled-columns rather than equality.

**Era note (post ticket-10 merge, session wind-down):** ticket 10 extended the bus
decoders (vp +`header_ts`; tu +`direction_id`,`trip_delay_s`,`trip_ts`,`header_ts`).
The mappers now emit those shapes (all four derivable from gtfsrt.io columns; census
tests green against the merged decoders), so future fills write the canonical schema.
The 886 parts filled in the first run carry the pre-10 shapes (the 40 parts of the 08-22
re-run carry the new one) — era-consistent with their same-day archiver parts, readable
by union-by-name, verified and durable, so they were left in place rather than refilled.
To refill them to the new shape later (optional): delete `part-gapfill-*.parquet` +
`_gapfill` markers for 08-15..08-21, then `make gapfill`, `make gapverify`,
`make coldpush`. Handed to the schema-era reconcile task (vp+tu, all three eras).

**Standing use:** `make gapfill` after any capture outage, then
`make gapcheck && make gapverify && make coldpush && make coldcheck`. It is a no-op for
hours already captured or already filled, so it is safe to re-run at any time; gtfsrt.io
lags 1-2 days, so the newest day usually needs a second pass.

**Dead-hour allowlist (`gapfill.DEAD`):** the four source-dead hours are listed in code so
`gapcheck` exits 0 on them — otherwise a scheduled run pages forever on holes nothing can
fill. They are still printed (`[dead at source: 07,12]`), never hidden, and gapcheck says
`stale DEAD entry` if a listed hour ever turns up, so the list cannot rot silently. Add an
entry ONLY after probing gtfsrt.io and confirming zero snapshots for that hour — never to
quiet a fill that merely failed. Note the check still exits 1 for the newest 1-2 days
until their fill lands; that is correct (it is actionable), so run `gapfill` before
`gapcheck` in any job.

## Era-scope correction (2026-08-23, schema-era session read-only audit; supersedes dd88f38)

The claim note dd88f38 is stale in three places — verified state:
- duck.table union_by_name fix: LANDED (143a00a), including BOTH vp era tests
  (DuckDB + Spark bronze_vp mixed-schema hour-pair).
- Actual refill scope is 123 old-shape parts (vp 61 + tu 62, dates 08-15..21), not
  886: alerts/subway_tu/subway_alerts are single-shape with zero drift (their decoders
  never changed in 07/10) — refilling them would be wasted I/O. The 6 canonical parts
  are the 08-22 seam run.
- The one REAL remaining hole: no TU era test (direction_id, trip_delay_s, trip_ts,
  header_ts). events.tu_rows/baselines set mergeSchema=true so likely safe, unverified.
Recommendation on record: skip the cosmetic refill; add the TU era test when a session
next has budget. Refill go/no-go stays Ross's call.

## Scope amendment: 167-day bus-history backfill (2026-08-23, measured; IN PROGRESS)

> Progress: March, April and May COMPLETE and verified in R2 (chunk logs below).
> Remaining: 2026-06-01..08-14. Verify chunks with `scripts/backfill-verify.py`, NOT
> `make gapverify` - see the April log for why gapverify cannot see this range.

`START = date(2026, 8, 15)` was "capture began", a deliberate scope line, not a source
limit. Probing gtfsrt.io shows far more history exists for our feeds, so this amends the
scope to 2026-03-01..2026-08-14 (167 days), bus only (vp/tu/alerts). Subway history is
explicitly OUT of scope pending a separate go.

**Source retention: append-only, nothing ages out.** Measured 2026-08-23 by listing the
public bucket: 231 contiguous date partitions bucket-wide (2026-01-04..08-22), but MTA
bus vp/tu only from 2026-03-01. Those differing start dates rule out a rolling window -
a retention policy would cut every feed at the same date. Feeds archived per day grows
monotonically (5 on 01-04 -> 18 on 08-22) with ZERO feeds dropped, so 2026-01-04 is the
service's genesis and 2026-03-01 is when they onboarded the MTA bus feed. No deletion
observed in 8 months; no published SLA found, and wholesale service death remains an
unquantified risk.

**Measured cost** (one full pilot day, 2026-03-01, all 24 hours, already on disk):
- vp 24 parts / 37.9 MB / 3.47M rows; tu 24 parts / 127.5 MB / 28.5M rows
- 165.4 MB/day -> **27.6 GB Bronze for 167 days**, ~6.3B rows, ~12,000 parts
- **207 GB to download** from gtfsrt.io (1.24 GB/day mean over four sampled days)
- runtime ~8 s/day for vp; whole range plausibly 1-2 h wall clock
- R2 at $0.015/GB-month: ~32 GB total archive = **~$0.50/month**, upload ops negligible

**Blocker 1 (FIXED, a9cb8be):** gtfsrt.io grew service_alerts 20 -> 50 columns mid-2026;
historical files have no direction_id column and the mapper raised KeyError, aborting the
day. Now NULL-filled. vp/tu source schemas verified stable across ten sampled dates
spanning the whole range, so no mid-run crash risk there.

**Blocker 2 (OPEN, needs Ross):** the archiver's `RAINCHECK_BRONZE_GB` is the 10 GB
default (no .env override) and `bronze_bytes()` counts every byte under archive/.
Archive is 4.5 GB; +27.6 GB = ~32 GB trips `STOPPED_BUDGET` and **halts live capture**
within the hour, which would open the very gaps this tool exists to close. Disk is also
tight: 40 GB free, so a full local materialisation leaves ~8 GB headroom. Options:
(a) raise RAINCHECK_BRONZE_GB past ~35 (his config, his call);
(b) fill -> gapverify -> coldpush -> prune per chunk (ticket 19's push-then-prune), local
    stays under budget and R2 becomes the durable home per ticket 18 - but this DELETES
    local historical Bronze after a verified push;
(c) keep the range cold-only.
Nothing is filled beyond the 2026-03-01 pilot day until this is decided.

**Provenance:** unchanged - part-gapfill-<feed>.parquet + `_gapfill` markers, archiver
hours never overwritten (there are none before 08-15, but the assertion stays), canonical
post-ticket-10 mappers throughout. Note `check()` still defaults to START, so gapcheck
will not verify backfilled days until START moves or --date is passed.

### Chunk log: March 2026 COMPLETE (2026-08-23)

Ross picked option **(b) chunked push-then-prune** on 2026-08-23 (answered directly in
the backfill session; re-confirmed via the orchestrator). Historical Bronze is pushed to
R2 and pruned locally per chunk; R2 is its durable home, per ticket 18.

**March verified in R2** - vp/tu/alerts each 744 parts + 744 `_gapfill` markers over
744 hours = 31 days x 24 h, no gaps. 1.60 + 5.50 + 0.01 = **7.11 GB**. `coldcheck` clean.
Local March parts remaining: 0. Archive returned to 4.4 GB; `STOPPED_BUDGET` never
appeared and live capture was never interrupted.

**Projection corrected: ~38.3 GB, not 27.6 GB.** The 27.6 figure came from a single
pilot day (2026-03-01, 165 MB) which was a light service day. A full month measures
**229 MB/day**, so 167 days lands near 38 GB (~$0.64/month at R2's $0.015/GB-month).
Download volume scales similarly - the 207 GB figure is likewise a floor.

**Two operational gotchas worth keeping:**
1. `RAINCHECK_BRONZE_GB=10` is 10e9 BYTES = **9.31 GiB**, but `du` reports GiB. Comparing
   them directly overstates headroom ~7%. A full month fills ~9.6 GiB peak if pruning
   waits for the chunk to finish - i.e. it trips the budget and halts capture mid-chunk.
   The fix is to prune CONCURRENTLY with the fill, not after it.
2. Concurrent pruning is safe only if gated on the `_gapfill` marker: `fill_day` touches
   markers only after a day fully succeeds, so a marker proves the part is complete and
   not mid-write. Files written after the sync snapshot show as not-yet-remote and are
   simply kept for the next pass - that is expected during a concurrent pass, NOT a
   failure (box-coldpush.sh may treat unverified as fatal because it only considers
   files older than PRUNE_MIN; that assumption does not hold here). The authoritative
   gate is `coldcheck` once filling has stopped.

**Queued follow-ups (not done here):**
- Per-date pruned-to-cloud markers, required IF `START` ever moves backwards or `check()`
  grows a date argument - otherwise gapcheck would see the pruned range as wholly missing
  and could re-pull ~38 GB. Not reachable today: `check(root)` takes no date argument.
- Ticket 15 residual: gapfill's default span ends at today-1, so the newest service day's
  tail hours under `date=D+1` can only fill the following morning; daily.py defers that
  day loudly (0908a9e) - correct but one morning late. Optional: let the daily job pass a
  span covering today.
- Expect a benign `coldcheck` soft-path warn in daily.log most mornings until this
  backfill finishes; 94aebc now names concurrent gapfill as a cause.

### Chunk log: April 2026 COMPLETE (2026-08-23)

Taken over mid-run after the owning session died. **Verified in R2 by
`scripts/backfill-verify.py 2026-04-01 2026-04-30`, rc=0:**

    OK  vp      719/720 hours (+1 dead at source)  parts_missing=0 markers_missing=0
    OK  tu      720/720 hours                      parts_missing=0 markers_missing=0
    OK  alerts  720/720 hours                      parts_missing=0 markers_missing=0

4318 objects / **6.84 GB** (vp 1.55, tu 5.28, alerts 0.01). Local April parts remaining: 0.
Archive ended 4.42 GiB against the 9.31 GiB budget; `STOPPED_BUDGET` never appeared and
live capture was never interrupted. March re-verified clean afterwards (2232/2232).

**Dead at source: vp 2026-04-27 h04.** Probed before believing it: h03 tapers to 107
snapshots, h04 has ZERO, h05 has 4, h06+ back to ~120 - a gtfsrt.io outage near
03:50-05:00Z. It thinned tu and alerts the same way but left them 8 and 4 snapshots in
h04, so both still fill 24/24 and are correctly NOT listed as dead. Recorded in
`backfill-verify.DEAD`, deliberately NOT in `gapfill.DEAD`: `check()` iterates from
`START` (2026-08-15), so a pre-START key never matches, and
`test_dead_entries_are_well_formed` rejects one precisely because an inert entry looks
like protection it is not. Add it there if and when START moves back.

**Three bugs found and fixed, all in the fill/prune interaction.** The push/prune half
must run CONCURRENTLY with the fill (March's lesson), and everything below is a
consequence of that concurrency. Two were in the `/tmp` originals AND in my first
hardened copy:

1. **The marker deleted its own gate** (`scripts/backfill-prune.py`). The sweep iterated
   every non-pending file in a marked hour, and `_gapfill` is a file never in `pending`,
   so any pass with a part still uploading unlinked the marker; the next pass's marker
   gate then skipped that hour forever and the part became unprunable. General invariant,
   now in the code: *a completion marker living inside the directory a sweep iterates
   must be excluded from that sweep, or it eventually deletes its own gate.*
2. **The marker pruned before it was ever uploaded** (8fc3cb4). A marker is written when
   its day completes, which can land AFTER a pass's pending snapshot was taken - so it
   is absent from `pending`, looks verified, and is deleted having never reached R2.
   Local is then pruned and the record that the hour was ever filled is gone for good.
   The marker is now held back exactly like a part.
3. **Cleanup rmdir'd hour-dirs a fill had just created** (fb51c81). `fill_day` does
   `mkdir(parents=True)` then writes, so an empty hour-dir may be one a fill is about to
   write into. Only hour-dirs a pass emptied itself are removed now - those held a
   marker, so they cannot be mid-fill.

Also fixed: drain mode exited if it sampled the gap between a driver's feeds
(vp -> tu -> alerts), leaving the rest filling with nothing draining - the exact failure
that stranded April. Now needs two consecutive idle checks (d0117ae).

**Damage and repair.** `tu` 2026-04-17 and 2026-04-28 both ended in R2 missing hour 23
and most markers; both were filled while a concurrent pruner ran (the `/tmp` script, and
my drain before fix 2). gtfsrt.io has 120 snapshots for h23 on both days, so the hour was
always fillable. Fixes 1 and 2 fully explain the missing markers.

> **Hour 23 root cause — found in May, recorded here because the evidence is April's.**
> This chunk could not explain the missing h23 and said so; the guess on record was fix 3
> (the empty-hour-dir race). **That guess was wrong.** May A reproduced the symptom with
> the diagnostic April lacked: `vp 2026-05-14` h23 absent from R2 while the fill log said
> `filled 24/24` - so the part was written locally and deleted before it ever uploaded.
>
> The prune treated *not in `pending`* as *verified remote*. It is not. A file created
> AFTER the listing ran was never a candidate for that listing, so its absence proves
> nothing. `fill_day` writes hour 23 last and only THEN touches the day's markers, so h23
> is the part most likely to appear between a pass's listing and its prune. **The hour is
> not special; its position in the write order is** - which is why April lost h23 twice
> and never h07. Fixed by stamping the listing's start time and holding anything at or
> newer than it (27aa035). Fix 3 remains correct and stays closed, but it was not this.

Repair for both: a **full-day** re-fill (`gapfill --feed tu --date <day>`), which works
only because local was already pruned - `missing_hours` then sees all 24 as missing and
`fill_day` marks all 24. A targeted re-fill would NOT work: `fill_day` marks only hours
filled in that run, so filling just h23 would mark h23 alone and leave 22 hours markerless
forever. Both days now 24/24 parts and markers.

**`make gapverify` CANNOT validate this backfill.** `verify()` compares a filled hour
against an archiver-captured hour ON THE SAME DAY; 2026-03-01..08-14 predates live
capture, so no such pair exists and it falls through to the first day that has both -
always an August day - then prints OK without having looked at the backfill at all.
Running it after a chunk is worse than not running it, because the OK reads as coverage.
Use `scripts/backfill-verify.py <LO> <HI>` instead: it censuses R2 (the only copy once a
chunk is pruned) and names every missing hour and every hour lacking its part or marker.
It is what caught both torn days.

**Trap: local day-count LIES during a concurrent drain.** April alerts looked like "19 of
30 days, died at day 20". It was 30 days filled with 11 already pruned. The measure is the
union of local and R2; a local count alone makes a healthy chunk look dead. This is also
how to tell done-vs-died when a driver's stdout is gone.

**Measured rates (April, useful for scheduling the rest):** vp ~10 s/day, tu ~1.8 min/day,
alerts ~4 s/day - about 65 min per month wall-clock, dominated entirely by tu. Download
~1.5 GB/day. Concurrent draining held the archive between 4.4 and 4.9 GiB the whole run,
never above 5 GiB, so budget headroom was never the binding constraint once pruning kept
pace.

**Still open:** May 1 - Aug 14. Source confirmed present for the whole span (probed
05-01, 05-15, 05-31, 06-15, 07-15, 08-14: vp ~130-215 MB/day, tu ~800-1255, alerts 20-58).
Run one chunk at a time - two concurrent chunks under the ORIGINAL `/tmp` script shared
`/tmp/pending.txt`, where one actor overwrites the other's verified-remote list and the
other then deletes local files it never proved remote. `scripts/backfill-chunk.sh` uses a
per-run mktemp file, but sequential remains the tested path.

### Chunk log: May 2026 COMPLETE (2026-08-23)

Run as two half-month chunks with `scripts/backfill-chunk.sh` in full mode (one process
owning fill AND concurrent drain, so a chunk cannot reach the fill-only state that
stranded April). **Verified in R2, rc=0:**

    OK  vp      744/744 hours                      parts_missing=0 markers_missing=0 zero_byte_parts=0
    OK  tu      744/744 hours                      parts_missing=0 markers_missing=0 zero_byte_parts=0
    OK  alerts  737/744 hours (+7 dead at source)  parts_missing=0 markers_missing=0 zero_byte_parts=0

**6.42 GB.** Local May parts remaining: 0. Archive ended 4.43 GiB against the 9.31 GiB
budget, peaking 5.18 GiB mid-chunk. `STOPPED_BUDGET` never appeared. Chunk A ran 23 min,
chunk B 19 min - a half-month is ~20 min, so the remaining span is hours, not days.

**Chunk A found the hour-23 root cause** that April could only guess at. See the
correction box in the April section: the prune read *not in `pending`* as *verified
remote*, which is false for any file created after the listing ran. Fixed in 27aa035.
**Chunk B then verified clean on its first pass with no short last-hour, which was the
agreed criterion for calling that class closed.**

**Dead at source: alerts 2026-05-28, hours 04, 05, 06, 08, 09, 11, 13.** The fill said
`filled 17/24` and 24 - 7 = 17, so fill and source agree exactly. alerts is event-driven
at a 300 s cadence, and that day is sparse throughout (several hours hold 1-2 snapshots),
so a quiet day can legitimately leave whole hours unstored. **Expect more of these in
alerts specifically** - and probe each rather than assuming from this one.

**`scripts/backfill-probe.py <kind> <day>` makes that probe a command** rather than a good
intention. It reads only Parquet footers and derives the hour exactly as `fill_day` does,
prints snapshots per hour plus a paste-ready DEAD entry, and exits 1 only when real dead
hours exist. Its most useful answer is the negative one: probing `vp 2026-05-14` showed
all 24 hours with ~120 snapshots, which is what turned that day's missing h23 from "maybe
the source" into a confirmed prune bug.

**Three more fixes, all found by re-reviewing my own code before it ran unattended:**

1. **A failed remote listing would have deleted everything** (9958619). `push_prune` built
   its verified-remote list from a `--dryrun` whose exit status it ignored. The prune
   deletes everything NOT in that list, so an empty list means "delete every marked file
   in range", and a network blip or dead endpoint produces exactly that. Measured: a dead
   endpoint returns rc=1 and 0 lines. The listing's exit status now gates the prune.
   The contract is also stated at the deletion site in `backfill-prune.py`, because
   nothing there said whose job that check was.
2. **`backfill-verify` counted objects and ignored size** (2127efd). A truncated or
   zero-byte part verified OK - the same false-OK class as gapverify. Parts must now carry
   bytes; markers stay exempt since `_gapfill` is legitimately empty.
3. **Each pass synced the whole archive** (aafe00f) - 20k objects, 25 GB, to verify at most
   a half-month. Now scoped to the chunk's own month prefixes. Verified against a synthetic
   tree, because a filter matching NOTHING looks identical to "everything uploaded" and
   feeds the same empty list that item 1 is about.

**Running total: 2026-03-01..05-31 complete and verified** (March 7.11 GB, April 6.84 GB,
May 6.42 GB). R2 holds 20,739 objects / 25.1 GB overall, about $0.38/month at
$0.015/GB-month. Remaining: 2026-06-01..08-14, source pre-flighted (273 files across
91 days x 3 feeds, none missing, none suspiciously small).
