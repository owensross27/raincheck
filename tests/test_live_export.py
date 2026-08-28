"""14-3 (the live-export fixture) and 14-4's live half, ticket 14.

The page-TEXT half of this file moved to tests/test_page.py at frontend2 01, which
split web/app.js into six ES modules; what is left here is the export seam and the
stdlib server. Nothing about the export changed.

Seam: `raincheck.live_export.once()` against a pytest temp data root holding hand-built
VP/TU/precip rows, with the wall clock injected. The files it swaps are read back as JSON.
No Spark, no Kafka - the export is DuckDB only.

**Why every row here is hand-built at a fixed epoch.** Ticket 12's review recorded that any
test asserting clock-derived behaviour on a decoded `.pb` fixture is suspect by
construction: `decode_vp` / `decode_tu` stamp `fetched_at` at decode time, so the fixture's
clock IS the wall clock and the assertion cannot tell the two apart. Everything below is
pinned to `T` = 2026-03-01T12:00:00Z with `now` passed in as `T + 60 s`, so `now` and
`max(fetched_at)` are DIFFERENT NUMBERS and the two rules the panel's honesty rests on are
each killed by a mutation:

  * the recency window is `now - 10 min`, never `max(fetched_at) - 10 min`. Vehicle V2's
    only Ping sits at `T - 570` - inside the max-based window, outside the wall-clock one -
    so the max-based mutation turns `n_vehicles` from 1 into 2.
  * the Prediction is measured against the feed's SNAPSHOT clock, never `now()`. The
    newest TU fetch has `header_ts = T - 60` and its earliest future arrival at `T + 120`,
    so the honest answer is 180 s and the wall-clock mutation gives 60 s.
"""
import json
import shutil
import threading
import urllib.request
from datetime import datetime, timedelta, timezone
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
import shapely

from raincheck import duck, live_export, publish

T = datetime(2026, 3, 1, 12, 0, 0, tzinfo=timezone.utc)   # the fixture clock
EPOCH = int(T.timestamp())
NOW = T + timedelta(seconds=60)                            # the injected wall clock
CELL = 613229522952650751                                  # a real Cell id (Central Park)
CELL_HEX = "882a100895fffff"
# V1's newest Ping sits at (-73.9700, 40.7820); the box covers only that point, so the
# planted Cell id IS the oracle for `cell_of`'s covers-confirm (nothing else seeded is inside
# it: V2 is at -73.98/40.75, V3 at -73.99/40.70).
CELL_BOX = (-73.9705, 40.7815, -73.9695, 40.7825)
PRECIP_MM = 2.5              # the winning (newest-fetched_at) row - above RAIN_MM
PRECIP_MM_DECOY = 0.4        # an older fetch for the same (cell, valid_ts) - below RAIN_MM,
                              # so oldest-wins would both pick the wrong value AND miscount rain
PRECIP_MM_FUTURE = 9.9       # a valid_ts partition after the wall clock - must never be read


def _stop(name: str) -> str:
    return f"MTA_{name}"


# (vehicle_id, trip_id, fetched_at, ts, lon, lat, rain?) - V1 three times, newest last
VP_ROWS = [
    ("V1", "TRIP1", EPOCH - 240, EPOCH - 245, -73.9600, 40.7800, False),
    ("V1", "TRIP1", EPOCH - 120, EPOCH - 125, -73.9650, 40.7810, False),
    ("V1", "TRIP1", EPOCH, EPOCH - 5, -73.9700, 40.7820, True),
    # inside max(fetched_at) - 600, OUTSIDE now - 600: the wall-clock mutation check.
    # Bronze's 20-min window does reach it, which is how the bronze test proves window_min.
    ("V2", None, EPOCH - 570, EPOCH - 575, -73.9800, 40.7500, False),
    ("V3", None, EPOCH - 3600, EPOCH - 3605, -73.9900, 40.7000, False),  # plainly old
]

# Bronze TU is still one row per stop. The newest fetch's earliest arrival overall is the
# FIRST row and it is in the past - the earliest FUTURE arrival is the second.
# (fetched_at, header_ts, stop_sequence, stop_id, arrival_time)
TU_STOPS = [
    (EPOCH - 300, EPOCH - 300, 1, _stop("S9"), EPOCH + 60),    # an older fetch
    (EPOCH - 60, EPOCH - 60, 1, _stop("S1"), EPOCH - 120),     # newest fetch, already past
    (EPOCH - 60, EPOCH - 60, 2, _stop("S2"), EPOCH + 120),     # <- the Prediction
    (EPOCH - 60, EPOCH - 60, 3, _stop("S3"), EPOCH + 400),
]
PRED_S = 180          # (EPOCH + 120) - (EPOCH - 60), against the snapshot clock
WALL_CLOCK_PRED_S = 60    # what a now()-based mutation would report instead
TRIP_DELAY_S = 420        # > the 300 s cut, so the gated delay state can open


def _con():
    con = duck.connect()
    con.execute(f"SET VARIABLE unused = {EPOCH}")   # keeps the connection's UTC session
    return con


def _write(con, out: Path, sql: str) -> None:
    out.mkdir(parents=True, exist_ok=True)
    con.execute(f"COPY ({sql}) TO '{out}' (FORMAT parquet, PARTITION_BY (date, hour), "
                f"OVERWRITE_OR_IGNORE true)")


def _vp_values() -> str:
    return ", ".join(
        f"('{v}', {'NULL' if t is None else repr(t)}, {f}, {ts}, {lon}, {lat}, "
        f"{2.5 if rain else 'NULL'})"
        for v, t, f, ts, lon, lat, rain in VP_ROWS)


def seed_live(root: Path) -> None:
    """`<root>/live/vp` and `<root>/live/tu` as the streaming job writes them: TU already
    reduced to one row per (trip, vehicle, fetched_at), and Cell / mm_1h / precip_valid_ts
    already joined onto the VP row (so the export does no precip join)."""
    con = _con()
    _write(con, root / "live" / "vp", f"""
        SELECT vehicle_id, trip_id, 'B41' AS route_id, 0::BIGINT AS direction_id,
               '20260301' AS start_date, 'SCHEDULED' AS schedule_relationship,
               lat, lon, 90.0 AS bearing, NULL::VARCHAR AS stop_id, ts,
               NULL::VARCHAR AS occupancy, fetched_at AS header_ts, fetched_at,
               {CELL}::BIGINT AS cell, 43::BIGINT AS zone_id, 'Manhattan' AS borough,
               mm_1h::FLOAT AS mm_1h,
               CASE WHEN mm_1h IS NULL THEN NULL
                    ELSE date_trunc('hour', to_timestamp(fetched_at)::TIMESTAMP) END AS precip_valid_ts,
               strftime(to_timestamp(fetched_at), '%Y-%m-%d') AS date,
               strftime(to_timestamp(fetched_at), '%H') AS hour
        FROM (VALUES {_vp_values()}) t(vehicle_id, trip_id, fetched_at, ts, lon, lat, mm_1h)""")

    # the stream's reduce_tu applied by hand: the newest fetch keeps its earliest FUTURE
    # arrival, the older fetch keeps its own
    reduced = ", ".join(
        f"({f}, {h}, {seq}, '{stop}', {arr})"
        for f, h, seq, stop, arr in (TU_STOPS[0], TU_STOPS[2]))
    _write(con, root / "live" / "tu", f"""
        SELECT 'TRIP1' AS trip_id, 'V1' AS vehicle_id, 'B41' AS route_id,
               '20260301' AS start_date, 0::BIGINT AS direction_id,
               {TRIP_DELAY_S}::BIGINT AS trip_delay_s, fetched_at AS trip_ts,
               header_ts, fetched_at, stop_id AS next_stop_id,
               stop_sequence AS next_stop_sequence, arrival_time AS next_arrival_time,
               strftime(to_timestamp(fetched_at), '%Y-%m-%d') AS date,
               strftime(to_timestamp(fetched_at), '%H') AS hour
        FROM (VALUES {reduced}) t(fetched_at, header_ts, stop_sequence, stop_id, arrival_time)""")

    (root / "live" / "_progress.json").write_text(json.dumps(
        {"batch_id": 7, "batch_end": T.strftime(live_export.STAMP), "rows": 1234}))
    con.close()


def seed_bronze(root: Path) -> None:
    """`<root>/archive/vp|tu` as the archiver writes them: the raw decoder rows, Stop-row
    TU, no Cell and no precip. One VP row carries the archive era's NULL `fetched_at`."""
    con = _con()
    _write(con, root / "archive" / "vp", f"""
        SELECT vehicle_id, trip_id, 'B41' AS route_id, 0::BIGINT AS direction_id,
               '20260301' AS start_date, 'SCHEDULED' AS schedule_relationship,
               lat, lon, 90.0 AS bearing, NULL::VARCHAR AS stop_id, ts,
               NULL::VARCHAR AS occupancy, fetched_at AS header_ts, fetched_at,
               coalesce(strftime(to_timestamp(fetched_at), '%Y-%m-%d'), '2026-03-01') AS date,
               coalesce(strftime(to_timestamp(fetched_at), '%H'), '12') AS hour
        FROM (VALUES {_vp_values()},
                     -- the archive era's fetched_at IS NULL row: the recency filter drops it
                     ('V0', NULL, NULL, {EPOCH}, -73.95, 40.75, NULL)
             ) t(vehicle_id, trip_id, fetched_at, ts, lon, lat, mm_1h)""")

    stops = ", ".join(f"({f}, {h}, {seq}, '{stop}', {arr})" for f, h, seq, stop, arr in TU_STOPS)
    _write(con, root / "archive" / "tu", f"""
        SELECT 'TRIP1' AS trip_id, 'B41' AS route_id, '20260301' AS start_date,
               0::BIGINT AS direction_id, 'V1' AS vehicle_id,
               {TRIP_DELAY_S}::BIGINT AS trip_delay_s, fetched_at AS trip_ts,
               stop_id, stop_sequence, arrival_time, NULL::BIGINT AS departure_time,
               header_ts, fetched_at,
               strftime(to_timestamp(fetched_at), '%Y-%m-%d') AS date,
               strftime(to_timestamp(fetched_at), '%H') AS hour
        FROM (VALUES {stops}) t(fetched_at, header_ts, stop_sequence, stop_id, arrival_time)""")
    con.close()


def seed_ref_cells(root: Path) -> None:
    """A minimal `ref/cells` (cell int64, geometry WKB - the real table's two columns
    `flood_panel.cell_index` reads) with ONE polygon, `CELL_BOX`, covering only V1's
    rain-flagged point. The planted id is the oracle: `cell_of` point-queries then
    `covers`-confirms, so a box that missed the point would resolve nothing."""
    box = shapely.box(*CELL_BOX)
    t = pa.table({"cell": pa.array([CELL], pa.int64()),
                  "geometry": pa.array([shapely.to_wkb(box)], pa.binary())})
    out = root / "ref" / "cells"
    out.mkdir(parents=True, exist_ok=True)
    pq.write_table(t, out / "part.parquet")


def seed_precip_cell(root: Path, now: datetime = NOW) -> None:
    """`live/precip_cell` as `precip_live.tick` writes it (cell, mm_1h, fetched_at under
    `valid_ts=YYYY-MM-DDTHH`). The target partition (`now`'s hour) holds a decoy older
    `fetched_at` with a DIFFERENT mm_1h so newest-fetch selection is killable by name; a
    second, later-than-`now` partition must never be read."""
    hour = now.strftime("%Y-%m-%dT%H")
    future_hour = (now + timedelta(hours=1)).strftime("%Y-%m-%dT%H")

    def part(valid_ts: str, rows: list[tuple[float, int]]) -> None:
        d = root / "live" / "precip_cell" / f"valid_ts={valid_ts}"
        d.mkdir(parents=True, exist_ok=True)
        t = pa.table({
            "cell": pa.array([CELL] * len(rows), pa.int64()),
            "mm_1h": pa.array([mm for mm, _ in rows], pa.float32()),
            "fetched_at": pa.array([datetime.fromtimestamp(f, timezone.utc) for _, f in rows],
                                    pa.timestamp("us", tz="UTC")),
        })
        pq.write_table(t, d / "part.parquet")

    part(hour, [(PRECIP_MM_DECOY, EPOCH - 300), (PRECIP_MM, EPOCH - 60)])
    part(future_hour, [(PRECIP_MM_FUTURE, EPOCH - 30)])


def seed_bronze_full(root: Path) -> None:
    """`seed_bronze` plus `ref/cells` and `live/precip_cell`, so the `bronze` fixture
    exercises `enrich_bronze`'s success path end to end."""
    seed_bronze(root)
    seed_ref_cells(root)
    seed_precip_cell(root)


def _tick(root: Path, out: Path, source: str, now: datetime = NOW) -> tuple[dict, dict]:
    """One tick, returning (meta, live.geojson)."""
    con = duck.connect()
    try:
        meta = live_export.once(con, root, out, source, now=now)
    finally:
        con.close()
    return meta, json.loads((out / "live.geojson").read_text())


@pytest.fixture(scope="module")
def live(tmp_path_factory):
    root = tmp_path_factory.mktemp("root")
    seed_live(root)
    return _tick(root, tmp_path_factory.mktemp("web"), "live")


@pytest.fixture(scope="module")
def bronze(tmp_path_factory):
    root = tmp_path_factory.mktemp("broot")
    seed_bronze_full(root)
    return _tick(root, tmp_path_factory.mktemp("bweb"), "bronze")


def only(fc: dict, vehicle: str = "V1") -> dict:
    (f,) = [f for f in fc["features"] if f["properties"]["vehicle_id"] == vehicle]
    return f


# ---------------------------------------------------------------------- 14-3, live source
def test_the_newest_ping_wins(live):
    meta, fc = live
    assert meta["n_vehicles"] == 1                       # V2 and V3 are out of the window
    p = only(fc)["properties"]
    assert p["fetched_at"] == EPOCH                       # not EPOCH - 240 or EPOCH - 120
    assert only(fc)["geometry"]["coordinates"] == [-73.97, 40.782]


def test_the_prediction_is_the_newest_fetchs_earliest_future_arrival(live):
    """Two discriminators in one: the older fetch's stop (S9) means the two-step reduce
    collapsed, and the newest fetch's FIRST stop (S1, already in the past) means the
    future filter was dropped."""
    _, fc = live
    p = only(fc)["properties"]
    assert p["next_stop_id"] == _stop("S2")
    assert p["pred_next_s"] == PRED_S


def test_the_prediction_is_measured_against_the_snapshot_clock_not_the_wall_clock(live):
    """Ticket 12's handoff rule. `now` is 60 s past the fixture's newest TU fetch, so a
    `next_arrival_time - now()` mutation reports 60 s where the honest answer is 180 s -
    and this assertion is what goes red when someone "simplifies" it."""
    _, fc = live
    assert only(fc)["properties"]["pred_next_s"] != WALL_CLOCK_PRED_S
    assert only(fc)["properties"]["pred_next_s"] == PRED_S


def test_mm_1h_and_the_precip_stamp_are_read_off_the_vp_row(live):
    meta, fc = live
    p = only(fc)["properties"]
    assert p["mm_1h"] == pytest.approx(2.5)
    assert p["precip_valid_ts"] == T.strftime(live_export.STAMP)
    assert meta["n_in_rain_cells"] == 1                   # mm_1h >= 1 mm RadarOnly
    assert p["cell"] == CELL_HEX


def test_every_age_is_the_wall_clock_against_the_fixture_epoch(live):
    """`now` is a hand-passed 60 s past `T`, and every row was written at a fixed epoch far
    from the real clock, so these numbers cannot be an accident of when the test ran."""
    meta, _ = live
    assert meta["vp_age_s"] == 60                          # now - EPOCH
    assert meta["vp_fetched_at_utc"] == T.strftime(live_export.STAMP)
    assert meta["tu_age_s"] == 120                         # now - (EPOCH - 60)
    assert meta["precip_age_s"] == 60
    assert meta["stream_progress"]["batch_id"] == 7
    assert meta["stream_progress"]["rows"] == 1234
    assert meta["stream_progress"]["age_s"] == 60


def test_a_row_outside_the_wall_clock_window_is_excluded(live):
    """V2 sits at `now - 630 s`: outside `now - 600` but INSIDE `max(fetched_at) - 600`.
    Swap the wall clock for the table's own max and this test goes red, which is the whole
    point - against the table's max a dead stream still paints a full, frozen fleet."""
    meta, fc = live
    assert {f["properties"]["vehicle_id"] for f in fc["features"]} == {"V1"}
    assert meta["window_min"] == 10 and meta["source"] == "live"


def test_unknown_values_are_absent_keys_never_null(live):
    """The same writer discipline as the insight export: a null would defeat `["has", p]`.
    V1 has no stop_id and no occupancy, so those keys must simply not be there."""
    _, fc = live
    p = only(fc)["properties"]
    assert "stop_id" not in p and "occupancy" not in p
    for f in fc["features"]:
        assert not [k for k, v in f["properties"].items() if v is None]


def test_a_healthy_tick_reports_no_error_and_counts_what_it_published(live):
    meta, fc = live
    assert meta["error"] is None and meta["stale"] is False
    assert meta["n_with_prediction"] == 1
    assert meta["n_with_trip_delay"] == 1
    assert only(fc)["properties"]["trip_delay_s"] == TRIP_DELAY_S
    assert meta["as_of_utc"] == NOW.strftime(live_export.STAMP)
    assert isinstance(meta["export_s"], float)


def test_a_dead_stream_still_reports_how_old_it_is(tmp_path):
    """The reason the `max(fetched_at)` probe runs over the pruned partitions and NOT over
    the windowed rows. Half an hour after the last write there is nothing in the 10-min
    window, so a probe taken off the result set would return NULL and the panel would have
    no age to go stale on - an empty map and a shrug. The pruned probe still dates it."""
    root, out = tmp_path / "root", tmp_path / "web"
    seed_live(root)
    meta, fc = _tick(root, out, "live", now=T + timedelta(minutes=30))
    assert meta["n_vehicles"] == 0 and fc["features"] == []
    assert meta["vp_age_s"] == 1800                        # and the panel's cut is 120 s
    assert meta["vp_fetched_at_utc"] == T.strftime(live_export.STAMP)
    assert meta["error"] is None                           # the tick worked; the feed did not


# ------------------------------------------------------------- 14-3, the failure path
def test_deleting_the_live_root_between_two_ticks_sets_meta_error_and_keeps_the_geojson(
        tmp_path):
    """A dead exporter must look STALE on the page, never absent and never fresh: the
    failed tick writes meta with `error` + `stale` and leaves live.geojson untouched."""
    root, out = tmp_path / "root", tmp_path / "web"
    seed_live(root)
    con = duck.connect()
    good = live_export.once(con, root, out, "live", now=NOW)
    before = (out / "live.geojson").read_bytes()
    assert good["error"] is None

    shutil.rmtree(root / "live")
    bad = live_export.once(con, root, out, "live", prev=good, now=NOW)   # must not raise
    con.close()

    assert bad["error"] and bad["stale"] is True
    assert bad["n_vehicles"] == good["n_vehicles"]        # the last good numbers, dated
    assert bad["checked_utc"] == NOW.strftime(live_export.STAMP)
    assert (out / "live.geojson").read_bytes() == before
    assert json.loads((out / "meta.json").read_text())["error"] == bad["error"]


def test_the_loop_survives_failing_ticks(tmp_path, monkeypatch):
    """The loop keeps ticking through a broken data root - `once` never raises, which is
    what "Ctrl-C stops it, a dead table does not" actually means."""
    root, out = tmp_path / "root", tmp_path / "web"
    seed_live(root)
    ticks = []

    class Stop(Exception):
        pass

    def fake_sleep(_):
        ticks.append(len(ticks))
        if len(ticks) == 1:
            shutil.rmtree(root / "live")     # break the tables between tick 1 and tick 2
        if len(ticks) >= 3:
            raise Stop
    monkeypatch.setattr(live_export.time, "sleep", fake_sleep)

    with pytest.raises(Stop):
        live_export.loop(root, out, "live", interval=0)
    assert len(ticks) == 3                   # three sleeps means four ticks were attempted
    assert json.loads((out / "meta.json").read_text())["error"]


# ------------------------------------------------------------------ 14-3, SOURCE=bronze
def test_bronze_reduces_stop_row_tu_in_two_steps(bronze):
    """Latest fetch per (trip, vehicle), then THAT fetch's earliest future arrival. A
    single pooled min() would return S9 from the older fetch instead."""
    _, fc = bronze
    p = only(fc)["properties"]
    assert p["next_stop_id"] == _stop("S2")
    assert p["pred_next_s"] == PRED_S


def test_bronze_carries_cell_rain_and_trip_delay(bronze):
    """The new contract: `enrich_bronze` resolves `cell` off `ref/cells`, `mm_1h`/
    `precip_valid_ts` off `live/precip_cell` (newest fetch of the target partition, never
    the future one or the older decoy), and the bronze TU reduce carries the agency's own
    `trip_delay_s`."""
    meta, fc = bronze
    p = only(fc)["properties"]
    assert p["cell"] == CELL_HEX
    assert p["mm_1h"] == pytest.approx(PRECIP_MM)
    assert p["mm_1h"] != pytest.approx(PRECIP_MM_DECOY)   # newest fetched_at wins, not oldest
    assert p["mm_1h"] != pytest.approx(PRECIP_MM_FUTURE)  # the later partition was never read
    assert p["precip_valid_ts"] == T.strftime(live_export.STAMP)
    assert p["trip_delay_s"] == TRIP_DELAY_S
    assert meta["n_in_rain_cells"] == 1                   # V1 only - V2's point has no Cell
    assert meta["n_with_trip_delay"] == 1
    assert meta["source"] == "bronze" and meta["error"] is None


def test_bronze_enrichment_is_garnish_when_ref_cells_is_absent(tmp_path):
    """Rule 1 of MUST 1: a missing `ref/cells` leaves the three keys absent and the tick
    healthy - it must not raise, and it must not fail the FLEET read either."""
    root, out = tmp_path / "root", tmp_path / "web"
    seed_bronze(root)   # no ref/cells, no live/precip_cell at all
    meta, fc = _tick(root, out, "bronze")
    p = only(fc)["properties"]
    assert not {"cell", "mm_1h", "precip_valid_ts"} & set(p)
    assert meta["error"] is None and meta["stale"] is False
    assert meta["n_in_rain_cells"] == 0


def test_bronze_enrichment_is_garnish_when_precip_cell_is_absent(tmp_path):
    """`cell` still resolves off `ref/cells`; only the precip join fails closed."""
    root, out = tmp_path / "root", tmp_path / "web"
    seed_bronze(root)
    seed_ref_cells(root)   # cell resolves; live/precip_cell is not there
    meta, fc = _tick(root, out, "bronze")
    p = only(fc)["properties"]
    assert p["cell"] == CELL_HEX
    assert not {"mm_1h", "precip_valid_ts"} & set(p)
    assert meta["error"] is None and meta["stale"] is False
    assert meta["n_in_rain_cells"] == 0


def test_bronze_trip_delay_s_absent_for_a_pre_era_tu_part(tmp_path):
    """A pre-era `archive/tu` PART with no `trip_delay_s` (or `header_ts`) column, sitting
    beside the normal wide part `seed_bronze` writes - the mixed-schema shape `eras.py`
    itself looks for. `union_by_name` synthesizes NULL for the narrow file's rows, never
    fails, and `json_merge_patch` drops it to an absent key - the same shape as V0's
    NULL-`fetched_at` VP row."""
    root, out = tmp_path / "root", tmp_path / "web"
    seed_bronze(root)   # the wide part: header_ts + trip_delay_s present
    con = _con()
    _write(con, root / "archive" / "vp", f"""
        SELECT 'V9' AS vehicle_id, 'TRIP9' AS trip_id, 'B41' AS route_id,
               0::BIGINT AS direction_id, '20260301' AS start_date,
               'SCHEDULED' AS schedule_relationship, 40.7820 AS lat, -73.9700 AS lon,
               90.0 AS bearing, NULL::VARCHAR AS stop_id, {EPOCH} AS ts,
               NULL::VARCHAR AS occupancy, {EPOCH} AS header_ts, {EPOCH} AS fetched_at,
               strftime(to_timestamp({EPOCH}), '%Y-%m-%d') AS date,
               strftime(to_timestamp({EPOCH}), '%H') AS hour""")
    # the narrow part: no header_ts, no trip_delay_s column at all
    _write(con, root / "archive" / "tu", f"""
        SELECT 'TRIP9' AS trip_id, 'B41' AS route_id, '20260301' AS start_date,
               0::BIGINT AS direction_id, 'V9' AS vehicle_id, '{_stop("S1")}' AS stop_id,
               1 AS stop_sequence, {EPOCH + 120} AS arrival_time,
               NULL::BIGINT AS departure_time, {EPOCH} AS fetched_at,
               strftime(to_timestamp({EPOCH}), '%Y-%m-%d') AS date,
               strftime(to_timestamp({EPOCH}), '%H') AS hour""")
    con.close()
    _, fc = _tick(root, out, "bronze")
    p = only(fc, "V9")["properties"]
    assert "trip_delay_s" not in p
    assert p["next_stop_id"] == _stop("S1")   # the Prediction still resolves off the union


def test_bronze_uses_the_twenty_minute_window_and_drops_null_fetched_at(bronze):
    """20 min reaches V2 at `now - 630` that the 10-min live window excludes - which is how
    this asserts the window rather than just reading the number back. V0's NULL
    `fetched_at` never survives `fetched_at >= t0`."""
    meta, fc = bronze
    assert meta["window_min"] == 20
    assert {f["properties"]["vehicle_id"] for f in fc["features"]} == {"V1", "V2"}
    assert meta["n_vehicles"] == 2


# ------------------------------------------------------------------------- 14-4 (live half)
def test_the_stdlib_server_answers_200_for_the_live_files(live, tmp_path):
    """14-4: the page plus five data files over `make web`. The three insight files are
    covered by tests/test_export.py's twin of this check; these are the two live ones, and
    `error: null` after a healthy tick is the assertion that says the loop really ran."""
    meta, fc = live
    web = tmp_path / "web"
    (web / "files").mkdir(parents=True)
    # the page is six ES modules now: take the file list from the `site` family rather
    # than a hand list, or a module a later ticket adds is one this server never answers for
    page = [k for k in publish.FAMILIES["site"].files if not k.startswith("vendor/")]
    for name in page:
        (web / name).write_bytes((live_export.REPO / "web" / name).read_bytes())
    (web / "files" / "meta.json").write_text(json.dumps(meta))
    (web / "files" / "live.geojson").write_text(json.dumps(fc))

    handler = partial(SimpleHTTPRequestHandler, directory=str(web))
    srv = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    served = {}
    try:
        port = srv.server_address[1]
        for path in [*page, "files/live.geojson", "files/meta.json"]:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/{path}", timeout=10) as r:
                assert r.status == 200, path
                body = r.read()
            assert body, path
            if path.endswith((".json", ".geojson")):
                served[path] = json.loads(body)
        assert served["files/meta.json"]["error"] is None    # a healthy tick really ran
        assert served["files/live.geojson"]["type"] == "FeatureCollection"
    finally:
        srv.shutdown()
        srv.server_close()
