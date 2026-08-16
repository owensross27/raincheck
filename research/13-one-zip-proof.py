"""Ticket 13: one-zip proof of the Transitland Hobbyist/Academic historic-download
grant. Downloads the 2021-09-01 Brooklyn pick (ticket 12's resolver), saves it as
Bronze `data/archive/static/brooklyn/<fetched_at date>.zip` (09 layout), checks it
is a real GTFS zip whose trip_ids follow the nycbuspositions scheme, records size
and latency, then downloads it once more to see whether the grant is metered per
request or per distinct version. Stdlib only. Exit 2 = grant not live yet (401).

  set -a; . ./.env; set +a; python3 research/13-one-zip-proof.py
  python3 research/13-one-zip-proof.py some.zip   # check-only, no download
"""
import hashlib
import io
import os
import re
import sys
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

SHA1 = "c244b822b8d0120d40e5849369b451220e1bfdd2"  # Brooklyn, fetched 2021-08-31, covers 2021-09-01
URL = f"https://transit.land/api/v2/rest/feed_versions/{SHA1}/download"
OUT = Path("data/archive/static/brooklyn/2021-08-31.zip")
# <depot>_<pick>-<service>[-<modifier>...]-<start>_<route>_<run>: WF_C1-Weekday-033000_SBS6_153,
# EN_C6-Weekday-SDon-028500_SBS82_901 (SDon = school days on, 28% of 2026 trips), rare -BM.
TRIP_ID = re.compile(r"^[A-Z]{2}_[A-Z]\d+-[A-Za-z]+(?:-[A-Za-z]+)*-\d{6}_[A-Z0-9+]+_\d+$")


def fetch(key):
    req = urllib.request.Request(URL, headers={"apikey": key})
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            body, hdr, code = r.read(), dict(r.headers), r.status
    except urllib.error.HTTPError as e:
        body, hdr, code = e.read(), dict(e.headers), e.code
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
    print(f"zip ok: {sorted(names)}\ntrips {len(ids):,}, sample {ids[:3]}, off-scheme {len(bad)}: {bad[:5]}")
    assert ids and not bad, "trip_id scheme differs from nycbuspositions"


if len(sys.argv) > 1:  # check-only on a local zip
    check(Path(sys.argv[1]).read_bytes())
    sys.exit(print("PASS (check-only)"))

key = os.environ.get("TRANSITLAND_API_KEY") or sys.exit("TRANSITLAND_API_KEY missing: set -a; . ./.env; set +a")
code, body, dt1 = fetch(key)
if code == 401:
    print("grant not live yet: 401 on tl_download_fv_historic (submit the Hobbyist/Academic form)")
    sys.exit(2)
assert code == 200, body[:200]
assert hashlib.sha1(body).hexdigest() == SHA1, "bytes do not match Transitland's sha1"
check(body)
OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_bytes(body)
print(f"saved {OUT} ({len(body)/1e6:.1f} MB, {dt1:.1f}s)")

print("re-download (metering check: compare credit/quota headers, if any):")
code2, body2, dt2 = fetch(key)
assert code2 == 200 and body2 == body
print("PASS")
