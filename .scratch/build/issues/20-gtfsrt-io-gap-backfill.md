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
