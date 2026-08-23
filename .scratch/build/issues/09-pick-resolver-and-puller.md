# 09 — Pick resolver v2 and the historic-zip puller

**What to build:** For any archive service date and feed, the resolver names the Transitland version whose
schedule was in effect - by the pick code carried in that day's own VP trip_ids - and the
puller can fetch it by sha1, verify the bytes, land it in Bronze and register the Pick.
Resolution and grammar are testable offline against a frozen listing; the actual 24-zip pull
for the slice waits on ticket 13's grant (the download endpoint is 401 until then).
Spec: D; the one-zip proof script is the reference for download/verify.

**Blocked by:** 02

**Status:** resolved 2026-08-22

- [x] pick-code parsing handles the depot form (`<depot>_<pick>-<service>[-modifiers]-<start>_<route>_<run>`, split on the six-digit start token) and the MTA Bus Company form (`-..P<code>-`); unit tests cover -SDon/-BM modifiers and busco ids
- [x] resolver: for service date D and feed, among in-window versions whose trips carry the day's pick code, take the greatest fetched_at <= D+1; on a frozen listing fixture the Ida day resolves Brooklyn to 4b8dec91 (not c244b822) and 2023-09-29 to the D3 version; the resolver logs the exact trip_id match rate per resolved Pick (~98% right / ~0% wrong)
- [x] puller: downloads by sha1 with the .env key, asserts the sha1 of the bytes, lands `static/<feed>/<fetched_at date>.zip`, registers ref/picks; a 401 exits cleanly with the grant message; re-download metering headers are printed
- [x] listing calls use the free key and respect the published limits; no key in the repo or logs
- [x] the 24 slice downloads (C1, D1, C3, D3 x six feeds) are a documented `make picks WINDOW=` invocation that runs when 13 says approved

---

**Implementation comment (2026-08-22).** `raincheck.picks` (`make picks WINDOW=w1|w2`).
Grammar: `DEPOT_RE` / `BUSCO_RE` now live in picks.py with capture groups and
schedule.py's gate imports them (one grammar, two callers). "Whose trips carry the
day's code" is read off the listing before any bytes exist: a version carries code P
iff its `latest_calendar_date` lands within 21 days of P's next-pick boundary
(A->Apr 1, B->Jul 1, C->Sep 1, D->Jan 1 next year; year digit = year mod 10 resolved
to the latest year <= D's, so D1 on 2022-01-01 still means 2021Sep). Validated on the
real listing: the C1 zip ends 2021-09-04 ~ Sep 1 while the early-published D1 zip
(c244b822) ends 2022-01-01 ~ Jan 1 and is excluded; frozen fixture
`tests/fixtures/transitland-listing-2026-08-22.json`.

Measured while resolving both windows against real Bronze VP:

- **Special-service codes**: Columbus/IPD days carry a dominant `O<digit>` code
  (2021-10-11: 26,241 distinct O1 trips vs 3,472 D1; 2023-10-09: O3). data.ny.gov
  stamps those O1 service_ids with `bundle: 2021Sep`, i.e. the O trips live inside the
  regular pick zip, so `resolve_any` walks the day's codes by falling count instead of
  hard-failing on the dominant one. Proven on bytes: the Brooklyn D1 zip (5b7f197c,
  pulled free from Wayback, sha1-identical to Transitland's) matches 2021-10-11's VP
  9,508/9,508 = 1.000.
- **Match rate is sharper than the ~98/~0 target** (route-restricted distinct-id
  join): right zip on 2021-09-05 = 6,788/6,788 = 1.000; wrong zip on 2021-09-01 =
  0/10,182 = 0.000.
- **The slice needs 31 zips, not 24**: w1 = 13 (busco has a mid-pick D1 revision
  fetched 2021-09-24), w2 = 18 (every feed has the D3-published-early zip fetched
  08-30 plus its 09-18 revision; per-day resolution wants both since each was in
  effect for part of September). Every slice day resolves - no pick_gap in either
  window. Still well under the 500-download grant.
- 401 path live-verified end to end: `make picks WINDOW=w1` resolves the plan, prints
  the metering headers (`X-RateLimit-Limit-Minute: 600`, remaining 599), exits 2 with
  the grant message. Re-run when 13 says approved (ticket 16 takes it from there).

Puller idempotency: an already-landed zip re-hashes to the listed sha1 and skips the
download. Transitland zips get a `.tl.json` sidecar (listing row) and `ref.build_picks`
registers them with `source=transitland`.

Adversarial review (3 lenses, opus-verified; 3 confirmed / 3 refuted) forced three
fixes, all landed with regression tests: (1) resolve() now requires the winner's own
calendar to cover D - short snapshot publishes exist (bronx Dec-2020, 3-day calendar)
that end near a boundary and out-fetch the true zip; 159 wrong feed-days across the
full window without the clause, 0 changes to w1/w2; (2) api_get follows redirects
itself with the apikey stripped - urllib re-sends every header cross-host and the
download endpoint 302s to Azure blob storage (live-verified on the grant-free current
endpoint), so the default opener would have leaked the key the day the grant went
live; same fix applied to research/13-one-zip-proof.py; (3) the landed filename is
now parsed through date.fromisoformat (a hostile listing fetched_at could otherwise
escape the data root). Tests: `tests/test_picks.py` (26; suite 117).
