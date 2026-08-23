"""`make picks WINDOW=` (ticket 09 / spec D): Pick resolver v2 and the historic-zip puller.

Resolver v2: the pick code carried in that service date's own VP trip_ids names the MTA
bundle (letter A/B/C/D = Jan/Apr/Jul/Sep pick, digit = year mod 10; depot form
`<depot>_<pick>-<service>[-modifiers]-<start:6>_<route>_<run>`, MTA Bus Company form
`-..P<code>-`). Among a feed's Transitland versions carrying that code, the Pick in
effect on D is the greatest fetched_at <= D+1 (mid-pick revisions supersede). Before the
bytes exist, "carries the code" is read off the listing: the version's
latest_calendar_date lands within BOUNDARY_SLACK of the code's next pick boundary
(measured on the real listing 2026-08-22: the C1 zip ends 2021-09-04 ~ Sep 1, while the
early-published D1 zip ends 2022-01-01 ~ Jan 1 and is correctly excluded). The exact
trip_id join is the self-check: ~98% against the right zip, ~0% against the wrong one,
logged per resolved Pick once the zip is local.

Puller: GET /feed_versions/{sha1}/download with the .env key (never in the repo or
logs), asserts the bytes hash to the listed sha1, lands Bronze
`static/<feed>/<fetched_at date>.zip` plus a `.tl.json` sidecar (marks
source=transitland in ref/picks), prints the metering headers, then rebuilds ref/picks.
A 401 means the ticket-13 Hobbyist/Academic grant is not live yet: clean exit 2.

Run: make picks WINDOW=w1|w2   (python -m raincheck.picks pull w1)
"""
import argparse
import hashlib
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from collections import Counter
from datetime import date, timedelta
from pathlib import Path

import pyarrow.compute as pc
import pyarrow.parquet as pq

from raincheck.paths import data_root
from raincheck.ref import WINDOWS, build_picks

API = "https://transit.land/api/v2/rest"
FEEDS = {
    "bronx": "f-dr72-mtanyctbusbronx", "brooklyn": "f-dr5r-mtanyctbusbrooklyn",
    "manhattan": "f-dr5r-mtanyctbusmanhattan", "queens": "f-dr5x-mtanyctbusqueens",
    "staten_island": "f-dr5r-mtanyctbusstatenisland", "busco": "f-dr5r-mtabc",
}
WINDOW = dict(zip(("w1", "w2"), WINDOWS))

# The two trip_id grammars (research 11/13); schedule.py's gate imports these.
DEPOT_RE = re.compile(r"^[A-Z0-9-]+_([A-Z]\d+)-.+-\d{6}_.+_\d+$")
BUSCO_RE = re.compile(r"-..P([A-Z]?\d+)-")
# letter -> (year offset, month) of the FIRST DAY AFTER the pick's period; the pick's
# zip calendar ends at the pick boundary, which is what identifies it in the listing.
PICK_BOUNDARY = {"A": (0, 4), "B": (0, 7), "C": (0, 9), "D": (1, 1)}
BOUNDARY_SLACK = timedelta(days=21)  # boundaries wobble around the 1st; gaps are >= 62 d
METER_RE = re.compile(r"ratelimit|credit|quota|remaining", re.I)


def pick_code(trip_id: str) -> str | None:
    m = DEPOT_RE.match(trip_id) or BUSCO_RE.search(trip_id)
    return m.group(1) if m else None


def day_vp(root: Path, day: date) -> set[tuple[str, str]]:
    """Distinct (trip_id, route_id) among the service date's own VP rows (start_date = D)."""
    part = root / "archive" / "vp" / f"date={day.isoformat()}"
    if not part.exists():
        return set()
    t = pq.read_table(part, columns=["trip_id", "route_id", "start_date"])
    t = t.filter(pc.equal(t.column("start_date"), day.strftime("%Y%m%d")))
    return {(tid, rid) for tid, rid in zip(t.column("trip_id").to_pylist(),
                                           t.column("route_id").to_pylist()) if tid}


def day_codes(root: Path, day: date) -> tuple[list[str], list[str]]:
    """The day's (depot-form, busco-form) pick codes by falling trip count. The head
    is normally the pick in effect, but special-service codes can outnumber it (26k O1
    vs 3.5k D1 trips on Columbus Day 2021-10-11) while living inside the same bundle
    (data.ny.gov stamps those O1 service_ids with bundle 2021Sep), so resolution walks
    the list until a code resolves. Stray codes stay ranked below (674 M3 rows on
    2023-09-29)."""
    depot: Counter[str] = Counter()
    busco: Counter[str] = Counter()
    for tid, _ in day_vp(root, day):
        if m := DEPOT_RE.match(tid):
            depot[m.group(1)] += 1
        elif m := BUSCO_RE.search(tid):
            busco[m.group(1)] += 1
    return [c for c, _ in depot.most_common()], [c for c, _ in busco.most_common()]


def next_boundary(code: str, day: date) -> date:
    """First day of the pick after <code>'s period. The year digit is year mod 10,
    resolved to the latest matching year <= the service date's (a D pick spills into
    January: code D1 on 2022-01-01 still means 2021)."""
    offset, month = PICK_BOUNDARY[code[0]]
    digit = int(code[1:]) % 10
    year = day.year - (day.year - digit) % 10
    return date(year + offset, month, 1)


def resolve(versions: list[dict], code: str, day: date) -> dict | None:
    """v2: among listing versions carrying <code> (latest_calendar_date within
    BOUNDARY_SLACK of the code's next boundary), the greatest fetched_at <= D+1."""
    if code[0] not in PICK_BOUNDARY:
        return None
    boundary = next_boundary(code, day)
    limit = (day + timedelta(days=1)).isoformat()
    hits = [v for v in versions
            if v.get("latest_calendar_date")
            and abs(date.fromisoformat(v["latest_calendar_date"][:10]) - boundary) <= BOUNDARY_SLACK
            # the winner's own calendar must cover D: short snapshot publishes exist
            # (bronx Dec-2020, 3-day calendar) that end near a boundary and out-fetch
            # the true zip (review find - 159 wrong feed-days without this)
            and (not v.get("earliest_calendar_date")
                 or v["earliest_calendar_date"][:10] <= day.isoformat() <= v["latest_calendar_date"][:10])
            and v["fetched_at"][:10] <= limit]
    return max(hits, key=lambda v: v["fetched_at"], default=None)


def resolve_any(versions: list[dict], codes: list[str], day: date) -> tuple[dict, str] | None:
    """First code (by falling count) that names a listing version, with that version."""
    for code in codes:
        if v := resolve(versions, code, day):
            return v, code
    return None


def match_rate(root: Path, day: date, zip_path: Path) -> tuple[int, int]:
    """Exact trip_id join of the day's VP against the zip's trips.txt, restricted to
    the routes the zip serves (a borough zip never holds another borough's trips).
    ~98% on the right zip, ~0% on the wrong one (research 13)."""
    import csv
    import io

    with zipfile.ZipFile(zip_path) as z:
        rows = list(csv.DictReader(io.TextIOWrapper(z.open("trips.txt"), "utf-8-sig")))
    zip_trips = {r["trip_id"].strip() for r in rows}
    zip_routes = {r["route_id"].strip() for r in rows}
    ids = {tid for tid, rid in day_vp(root, day) if rid in zip_routes}
    return len(ids & zip_trips), len(ids)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """urllib re-sends every header (the apikey) to redirect targets, and the download
    endpoint 302s to third-party blob storage (review find, live-verified). Surface the
    3xx instead; api_get follows one hop itself with the key stripped."""
    def redirect_request(self, *args, **kwargs):
        return None


_OPENER = urllib.request.build_opener(_NoRedirect)


def api_get(path: str, key: str) -> tuple[int, bytes, dict]:
    url, headers, meter = API + path, {"apikey": key}, {}
    for _ in range(2):  # the original request + at most one keyless redirect hop
        req = urllib.request.Request(url, headers=headers)
        try:
            with _OPENER.open(req, timeout=300) as r:
                return r.status, r.read(), {**meter, **dict(r.headers)}
        except urllib.error.HTTPError as e:
            if e.code in (301, 302, 303, 307, 308) and e.headers.get("Location"):
                meter = dict(e.headers)  # the 302 carries the rate-limit headers
                url = urllib.parse.urljoin(url, e.headers["Location"])
                headers = {}  # the key never crosses hosts; signed URLs need none
                continue
            return e.code, e.read(), {**meter, **dict(e.headers)}
    return 599, b"redirect loop", meter


def listing(feed: str, key: str) -> list[dict]:
    code, body, _ = api_get(f"/feed_versions?feed_onestop_id={FEEDS[feed]}&limit=200", key)
    if code != 200:
        sys.exit(f"picks: listing {feed} failed HTTP {code}: {body[:200]!r}")
    return json.loads(body)["feed_versions"]


def download(sha1: str, key: str) -> bytes:
    code, body, hdr = api_get(f"/feed_versions/{sha1}/download", key)
    meter = {k: v for k, v in hdr.items() if METER_RE.search(k)}
    print(f"picks: download {sha1[:8]} HTTP {code} {len(body):,} B {meter}", flush=True)
    if code == 401:
        print("picks: 401 - the ticket-13 Hobbyist/Academic grant is not live yet; "
              "re-run `make picks` when 13 says approved", file=sys.stderr, flush=True)
        sys.exit(2)
    if code != 200:
        sys.exit(f"picks: download {sha1[:8]} failed HTTP {code}: {body[:200]!r}")
    if hashlib.sha1(body).hexdigest() != sha1:
        sys.exit(f"picks: download {sha1[:8]} bytes do not hash to the listed sha1")
    return body


def pull(root: Path, window: str) -> None:
    key = os.environ.get("TRANSITLAND_API_KEY") or sys.exit(
        "TRANSITLAND_API_KEY missing: set -a; . ./.env; set +a")
    start, end = WINDOW[window]
    listings: dict[str, list[dict]] = {}
    # (feed, sha1) -> (listing row, code, latest window day that resolved to it)
    plan: dict[tuple[str, str], tuple[dict, str, date]] = {}
    for n in range((end - start).days + 1):
        day = start + timedelta(n)
        depot_codes, busco_codes = day_codes(root, day)
        if not depot_codes and not busco_codes:
            print(f"picks: {day}: no Bronze VP, skipped", file=sys.stderr, flush=True)
            continue
        for feed in FEEDS:
            codes = busco_codes if feed == "busco" else depot_codes
            if not codes:
                continue
            if feed not in listings:
                listings[feed] = listing(feed, key)
            hit = resolve_any(listings[feed], codes, day)
            if hit is None:
                print(f"picks: {feed} {day} codes {codes}: no listing version carries "
                      "any (pick_gap stays)", file=sys.stderr, flush=True)
                continue
            v, code = hit
            if code != codes[0]:
                print(f"picks: {feed} {day}: dominant code {codes[0]} has no version, "
                      f"resolved via {code}", flush=True)
            plan[(feed, v["sha1"])] = (v, code, day)

    print(f"picks: {window} needs {len(plan)} zips", flush=True)
    for (feed, sha1), (v, code, day) in sorted(plan.items()):
        # fromisoformat validates the listing-supplied name (a hostile fetched_at
        # could otherwise escape the data root as an absolute path)
        fetched = date.fromisoformat(v["fetched_at"][:10])
        out = root / "archive" / "static" / feed / f"{fetched.isoformat()}.zip"
        if out.exists() and hashlib.sha1(out.read_bytes()).hexdigest() == sha1:
            print(f"picks: {feed} {code} {sha1[:8]} already landed", flush=True)
        else:
            body = download(sha1, key)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(body)
            out.with_name(out.name + ".tl.json").write_text(json.dumps(
                {k: v.get(k) for k in ("sha1", "fetched_at", "earliest_calendar_date",
                                       "latest_calendar_date", "url")}))
        matched, total = match_rate(root, day, out)
        rate = matched / total if total else 0.0
        print(f"picks: {feed} {code} -> {sha1[:8]} fetched {v['fetched_at'][:10]} "
              f"match {matched}/{total} = {rate:.3f}", flush=True)
    build_picks(root)


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("pull").add_argument("window", choices=sorted(WINDOW))
    args = ap.parse_args()
    pull(data_root(), args.window)


if __name__ == "__main__":
    main()
