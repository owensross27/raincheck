"""Ticket 09: pick-code grammar, resolver v2 on the frozen Transitland listing
(snapshotted 2026-08-22, trimmed to the four fields the resolver reads), day_codes /
match_rate on a fake Bronze VP, and the puller's 401 / sha1 edges - all offline."""
import hashlib
import json
import zipfile
from datetime import date
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from raincheck import picks

LISTING = json.loads(
    (Path(__file__).parent / "fixtures" / "transitland-listing-2026-08-22.json").read_text())


@pytest.mark.parametrize("tid,code", [
    ("WF_C1-Weekday-033000_SBS6_153", "C1"),                # plain depot form
    ("EN_C6-Weekday-SDon-028500_SBS82_901", "C6"),          # -SDon modifier
    ("FP_D3-Weekday-BM-045000_Q54_302", "D3"),              # -BM modifier
    ("MQ_M3-Weekday-060000_M100_1", "M3"),                  # stray code still parses
    ("31325137-LGPC1-LG_C1-Weekday-10", "C1"),              # busco -..P<code>- form
    ("1234-LGPA5-Weekday-10-123456_Q50_1", "A5"),           # busco (conftest shape)
    ("", None),
    ("MTABC_12345", None),
    ("Weekday-033000", None),
])
def test_pick_code(tid, code):
    assert picks.pick_code(tid) == code


def test_next_boundary_january_spillover():
    # a D pick runs into January: D1 seen on 2022-01-01 still means the 2021 Sep pick
    assert picks.next_boundary("D1", date(2022, 1, 1)) == date(2022, 1, 1)
    assert picks.next_boundary("C1", date(2021, 9, 1)) == date(2021, 9, 1)
    assert picks.next_boundary("D3", date(2023, 9, 29)) == date(2024, 1, 1)


def test_resolve_ida_day_is_c1_not_early_september():
    # 2021-09-01 carries C1; the fetched_at<=D+1 winner c244b822 is the 2021Sep pick
    # published early (cal ends 2022-01-01) and must lose to the real C1 zip
    v = picks.resolve(LISTING["brooklyn"], "C1", date(2021, 9, 1))
    assert v["sha1"].startswith("4b8dec91")


def test_resolve_d1_after_the_boundary():
    v = picks.resolve(LISTING["brooklyn"], "D1", date(2021, 9, 5))
    assert v["sha1"].startswith("5b7f197c")  # fetched 2021-09-02 supersedes c244b822


def test_resolve_2023_storm_day_d3():
    v = picks.resolve(LISTING["brooklyn"], "D3", date(2023, 9, 29))
    assert v["sha1"].startswith("61d83dfe")


def test_resolve_mid_pick_revision_supersedes():
    # two C3 zips exist (fetched 2023-06-29 and 07-29); the revision wins for later days
    v = picks.resolve(LISTING["brooklyn"], "C3", date(2023, 9, 1))
    assert v["sha1"].startswith("920028e6")


def test_resolve_january_uses_previous_year_boundary():
    v = picks.resolve(LISTING["brooklyn"], "D1", date(2022, 1, 1))
    assert v["sha1"].startswith("cade406c")  # fetched 2021-12-21, cal ends 2022-01-01


def test_resolve_none_on_empty_or_unknown_code():
    assert picks.resolve([], "C1", date(2021, 9, 1)) is None
    assert picks.resolve(LISTING["brooklyn"], "M3", date(2023, 9, 29)) is None


def test_resolve_requires_calendar_coverage():
    # review find: bronx D0 on 2021-01-02 - a 3-day Dec-2020 snapshot (e9e60295,
    # cal 2020-12-15..17) ends near the Jan boundary and out-fetches the true D0
    # zip; the coverage clause keeps the zip whose calendar contains the day
    v = picks.resolve(LISTING["bronx"], "D0", date(2021, 1, 2))
    assert v["sha1"].startswith("7cd39cd2")


def test_resolve_any_walks_past_special_service_codes():
    # Columbus Day 2021-10-11: O1 (special service inside the 2021Sep bundle)
    # outnumbers D1; O1 names no version, so the walk lands on the D1 zip
    v, code = picks.resolve_any(LISTING["brooklyn"], ["O1", "D1"], date(2021, 10, 11))
    assert code == "D1" and v["sha1"].startswith("5b7f197c")
    assert picks.resolve_any(LISTING["brooklyn"], ["O1"], date(2021, 10, 11)) is None


def bronze_vp(root: Path, day: date, rows: list[tuple[str, str, str]]) -> None:
    part = root / "archive" / "vp" / f"date={day.isoformat()}" / "hour=12"
    part.mkdir(parents=True)
    pq.write_table(pa.table({
        "trip_id": [r[0] for r in rows],
        "route_id": [r[1] for r in rows],
        "start_date": [r[2] for r in rows],
    }), part / "part-00.parquet")


def test_day_codes_dominance_and_start_date_filter(tmp_path):
    day = date(2021, 9, 1)
    bronze_vp(tmp_path, day, [
        ("WF_C1-Weekday-033000_SBS6_153", "B6+", "20210901"),
        ("EN_C1-Weekday-040000_B41_101", "B41", "20210901"),
        ("MQ_M3-Weekday-060000_M100_1", "M100", "20210901"),     # stray, outvoted
        ("WF_D1-Weekday-050000_B44_1", "B44", "20210902"),       # next service date: excluded
        ("31325137-LGPC1-LG_C1-Weekday-10", "Q39", "20210901"),  # busco
    ])
    assert picks.day_codes(tmp_path, day) == (["C1", "M3"], ["C1"])
    assert picks.day_codes(tmp_path, date(2021, 9, 3)) == ([], [])  # no Bronze


def gtfs_zip(path: Path, trips: list[tuple[str, str]]) -> None:
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("trips.txt", "route_id,service_id,trip_id\n"
                   + "".join(f"{r},WKD,{t}\n" for t, r in trips))


def test_match_rate_route_restricted(tmp_path):
    day = date(2021, 9, 1)
    bronze_vp(tmp_path, day, [
        ("MV_C1-Weekday-033000_B41_101", "B41", "20210901"),  # in zip
        ("MV_C1-Weekday-034000_B41_102", "B41", "20210901"),  # in zip
        ("MV_D1-Weekday-035000_B41_103", "B41", "20210901"),  # wrong pick: not in zip
        ("GA_C1-Weekday-040000_Q59_901", "Q59", "20210901"),  # other feed's route: excluded
    ])
    zp = tmp_path / "pick.zip"
    gtfs_zip(zp, [("MV_C1-Weekday-033000_B41_101", "B41"),
                  ("MV_C1-Weekday-034000_B41_102", "B41"),
                  ("MV_C1-Weekday-090000_B41_199", "B41")])
    assert picks.match_rate(tmp_path, day, zp) == (2, 3)


def test_download_401_exits_2_with_grant_message(monkeypatch, capsys):
    monkeypatch.setattr(picks, "api_get", lambda p, k: (401, b'{"error":"Unauthorized"}', {}))
    with pytest.raises(SystemExit) as e:
        picks.download("4b8dec91" + "0" * 32, "key")
    assert e.value.code == 2
    assert "grant" in capsys.readouterr().err


def test_download_asserts_sha1(monkeypatch):
    monkeypatch.setattr(picks, "api_get", lambda p, k: (200, b"not the zip", {}))
    with pytest.raises(SystemExit, match="sha1"):
        picks.download("4b8dec91" + "0" * 32, "key")


def test_download_ok(monkeypatch):
    body = b"zipbytes"
    monkeypatch.setattr(picks, "api_get", lambda p, k: (200, body, {"X-RateLimit-Limit-Minute": "600"}))
    assert picks.download(hashlib.sha1(body).hexdigest(), "key") == body


def test_api_get_strips_key_on_redirect(monkeypatch):
    # review find: urllib re-sends every header to redirect targets; the download
    # endpoint 302s to third-party blob storage, so the hop must go out keyless
    import email
    import io as _io
    import urllib.error

    seen = []

    class Opener:
        def open(self, req, timeout=None):
            seen.append((req.full_url, dict(req.headers)))
            if len(seen) == 1:
                hdrs = email.message_from_string("Location: https://blob.example/x.zip\n")
                raise urllib.error.HTTPError(req.full_url, 302, "Found", hdrs, _io.BytesIO(b""))
            r = _io.BytesIO(b"zipbytes")
            r.status, r.headers = 200, {}
            return r

    monkeypatch.setattr(picks, "_OPENER", Opener())
    code, body, _ = picks.api_get("/feed_versions/x/download", "SECRET")
    assert (code, body) == (200, b"zipbytes")
    assert seen[0][1].get("Apikey") == "SECRET"          # first hop carries the key
    assert seen[1][0] == "https://blob.example/x.zip"
    assert "Apikey" not in seen[1][1]                    # redirect hop is keyless


def test_build_picks_marks_transitland_source(tmp_path):
    from conftest import gtfs_zip_bytes  # bare pytest and `python -m pytest` both resolve this

    from raincheck import ref

    data = gtfs_zip_bytes()
    for feed, name, sidecar in (("brooklyn", "2021-06-25.zip", True),
                                ("queens", "2026-06-23.zip", False)):
        out = tmp_path / "archive" / "static" / feed / name
        out.parent.mkdir(parents=True)
        out.write_bytes(data)
        if sidecar:
            out.with_name(out.name + ".tl.json").write_text("{}")
    ref.build_picks(tmp_path)
    rows = pq.read_table(tmp_path / "ref" / "picks").to_pylist()
    assert {r["feed"]: r["source"] for r in rows} == {"brooklyn": "transitland", "queens": "mta"}
