# 09 — Pick resolver v2 and the historic-zip puller

**What to build:** For any archive service date and feed, the resolver names the Transitland version whose
schedule was in effect - by the pick code carried in that day's own VP trip_ids - and the
puller can fetch it by sha1, verify the bytes, land it in Bronze and register the Pick.
Resolution and grammar are testable offline against a frozen listing; the actual 24-zip pull
for the slice waits on ticket 13's grant (the download endpoint is 401 until then).
Spec: D; the one-zip proof script is the reference for download/verify.

**Blocked by:** 02

**Status:** ready-for-agent

- [ ] pick-code parsing handles the depot form (`<depot>_<pick>-<service>[-modifiers]-<start>_<route>_<run>`, split on the six-digit start token) and the MTA Bus Company form (`-..P<code>-`); unit tests cover -SDon/-BM modifiers and busco ids
- [ ] resolver: for service date D and feed, among in-window versions whose trips carry the day's pick code, take the greatest fetched_at <= D+1; on a frozen listing fixture the Ida day resolves Brooklyn to 4b8dec91 (not c244b822) and 2023-09-29 to the D3 version; the resolver logs the exact trip_id match rate per resolved Pick (~98% right / ~0% wrong)
- [ ] puller: downloads by sha1 with the .env key, asserts the sha1 of the bytes, lands `static/<feed>/<fetched_at date>.zip`, registers ref/picks; a 401 exits cleanly with the grant message; re-download metering headers are printed
- [ ] listing calls use the free key and respect the published limits; no key in the repo or logs
- [ ] the 24 slice downloads (C1, D1, C3, D3 x six feeds) are a documented `make picks WINDOW=` invocation that runs when 13 says approved
