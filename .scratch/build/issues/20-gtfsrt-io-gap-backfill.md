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

**Status:** ready-for-agent

- [ ] schema probe first (one day, one feed): map gtfsrt.io's Parquet columns onto the 05
      decoder's Bronze schema; every Bronze column must be derivable or explicitly NULL
      with a note. If their rows are per-entity snapshots, dedupe with the same
      header.timestamp rule as the archiver.
- [ ] `make gapfill FEED= DATE=` (or one `gapfill` driver over a date range): downloads the
      day's parquet, extracts ONLY the missing hours (never overwrites hours the archiver
      captured — our capture wins), writes them as Bronze hour-dirs in the standard layout,
      marks provenance (`src=gtfsrt.io` column or a `_gapfill` marker file per hour-dir).
- [ ] scope: bus vp/tu/alerts + subway_tu + subway_alerts, 2026-08-15 -> present; subway_vp
      excluded (unavailable, see above).
- [ ] after fill: `make coldpush` and the hour-completeness check (19's check; if 19 has
      not landed, a one-off version here) show every closed day complete for the five
      recoverable feeds.
- [ ] one runnable check: for one filled hour, row counts and key coverage are sane vs an
      adjacent archiver-captured hour (same feed, same day) — loud if the filled hour is
      empty or wildly off.
