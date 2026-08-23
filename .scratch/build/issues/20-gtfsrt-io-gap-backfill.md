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

## Scope amendment: 167-day bus-history backfill (2026-08-23, measured, NOT YET RUN)

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
