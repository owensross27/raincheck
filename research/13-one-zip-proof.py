"""Ticket 13: one-zip proof of the Transitland Hobbyist/Academic historic-download
grant. Downloads a Brooklyn pick (default: the 2021Jul pick, code C1, the one the
Ida-day trip_ids carry; ticket 12's fetched_at rule wrongly chose the 2021Sep pick,
see the 13 sweep), saves it as Bronze `data/archive/static/brooklyn/<fetched_at
date>.zip` (09 layout), checks it is a real GTFS zip whose trip_ids follow the
nycbuspositions scheme, reports the pick codes inside, records size and latency,
then downloads once more to see whether the grant is metered per request or per
distinct version. Stdlib only. Exit 2 = grant not live yet (401).

  set -a; . ./.env; set +a; python3 research/13-one-zip-proof.py [sha1]
  python3 research/13-one-zip-proof.py some.zip   # check-only, no download
"""
import collections
import hashlib
import io
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

# Brooklyn sha1 prefixes: 4b8dec91 = 2021Jul pick (C1, fetched 2021-06-25, in effect on 2021-09-01);
# c244b822 = 2021Sep content published 2021-08-31 (12's original target); 61d83dfe = 2023Sep (D3).
DEFAULT_SHA1 = "4b8dec91"
# <depot>_<pick>-<service>[-<modifier>...]-<start>_<route>_<run>: WF_C1-Weekday-033000_SBS6_153,
# EN_C6-Weekday-SDon-028500_SBS82_901 (SDon = school days on, 28% of 2026 trips), rare -BM.
TRIP_ID = re.compile(r"^[A-Z]{2}_([A-Z]\d+)-[A-Za-z]+(?:-[A-Za-z]+)*-\d{6}_[A-Z0-9+]+_\d+$")


class NoRedirect(urllib.request.HTTPRedirectHandler):
    # urllib re-sends every header (the apikey) to redirect targets, and the download
    # endpoint 302s to third-party blob storage - follow one hop with the key stripped
    def redirect_request(self, *args, **kwargs):
        return None


OPENER = urllib.request.build_opener(NoRedirect)


def fetch(url, key):
    headers = {"apikey": key}
    body, hdr, code = b"redirect loop", {}, 599
    t0 = time.perf_counter()
    for _ in range(2):
        req = urllib.request.Request(url, headers=headers)
        try:
            with OPENER.open(req, timeout=300) as r:
                body, hdr, code = r.read(), dict(r.headers), r.status
            break
        except urllib.error.HTTPError as e:
            if e.code in (301, 302, 303, 307, 308) and e.headers.get("Location"):
                url, headers = e.headers["Location"], {}
                continue
            body, hdr, code = e.read(), dict(e.headers), e.code
            break
    dt = time.perf_counter() - t0
    quota = {k: v for k, v in hdr.items() if re.search(r"ratelimit|credit|quota|remaining", k, re.I)}
    print(f"HTTP {code}  {len(body):,} B  {dt:.1f}s  {hdr.get('Content-Type')}  {quota}")
    return code, body, dt


def check(body):
    z = zipfile.ZipFile(io.BytesIO(body))
    names = set(z.namelist())
    assert {"trips.txt", "stop_times.txt", "calendar.txt"} <= names, names
    trips = z.read("trips.txt").decode("utf-8-sig").splitlines()
    col = trips[0].split(",").index("trip_id")
    ids = [ln.split(",")[col].strip('"') for ln in trips[1:] if ln]
    bad = [t for t in ids if not TRIP_ID.match(t)]
    codes = collections.Counter(m.group(1) for t in ids if (m := TRIP_ID.match(t)))
    print(f"zip ok: {sorted(names)}\ntrips {len(ids):,}, pick codes {dict(codes)}, sample {ids[:2]}, off-scheme {len(bad)}: {bad[:5]}")
    assert ids and not bad, "trip_id scheme differs from nycbuspositions"


if len(sys.argv) > 1 and sys.argv[1].endswith(".zip"):  # check-only on a local zip
    check(Path(sys.argv[1]).read_bytes())
    sys.exit(print("PASS (check-only)"))

key = os.environ.get("TRANSITLAND_API_KEY") or sys.exit("TRANSITLAND_API_KEY missing: set -a; . ./.env; set +a")
prefix = (sys.argv[1] if len(sys.argv) > 1 else DEFAULT_SHA1)[:8]
# resolve the full sha1 + fetched_at from the free list endpoint (one REST call)
lst = fetch("https://transit.land/api/v2/rest/feed_versions?feed_onestop_id=f-dr5r-mtanyctbusbrooklyn&limit=200", key)[1]
ver = next(v for v in json.loads(lst)["feed_versions"] if v["sha1"].startswith(prefix))
sha1, out = ver["sha1"], Path(f"data/archive/static/brooklyn/{ver['fetched_at'][:10]}.zip")
url = f"https://transit.land/api/v2/rest/feed_versions/{sha1}/download"
print(f"target {sha1} fetched {ver['fetched_at'][:10]} cal {ver['earliest_calendar_date']}..{ver['latest_calendar_date']}")

code, body, dt1 = fetch(url, key)
if code == 401:
    print("grant not live yet: 401 on tl_download_fv_historic (submit the Hobbyist/Academic form)")
    sys.exit(2)
assert code == 200, body[:200]
assert hashlib.sha1(body).hexdigest() == sha1, "bytes do not match Transitland's sha1"
check(body)
out.parent.mkdir(parents=True, exist_ok=True)
out.write_bytes(body)
print(f"saved {out} ({len(body)/1e6:.1f} MB, {dt1:.1f}s)")

print("re-download (metering check: compare credit/quota headers, if any):")
code2, body2, dt2 = fetch(url, key)
assert code2 == 200 and body2 == body
print("PASS")
