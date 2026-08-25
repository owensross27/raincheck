"""14-3 (the live-export fixture) and 14-4's live half, ticket 14.

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

import pytest

from raincheck import duck, live_export

T = datetime(2026, 3, 1, 12, 0, 0, tzinfo=timezone.utc)   # the fixture clock
EPOCH = int(T.timestamp())
NOW = T + timedelta(seconds=60)                            # the injected wall clock
CELL = 613229522952650751                                  # a real Cell id (Central Park)
CELL_HEX = "882a100895fffff"


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
    seed_bronze(root)
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


def test_bronze_carries_no_cell_precip_or_trip_delay(bronze):
    meta, fc = bronze
    for f in fc["features"]:
        p = f["properties"]
        assert not {"cell", "mm_1h", "precip_valid_ts", "trip_delay_s"} & set(p)
    assert meta["n_in_rain_cells"] == 0 and meta["n_with_trip_delay"] == 0
    assert meta["source"] == "bronze" and meta["error"] is None


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
    for name in ("index.html", "app.js", "app.css"):
        (web / name).write_bytes((live_export.REPO / "web" / name).read_bytes())
    (web / "files" / "meta.json").write_text(json.dumps(meta))
    (web / "files" / "live.geojson").write_text(json.dumps(fc))

    handler = partial(SimpleHTTPRequestHandler, directory=str(web))
    srv = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    served = {}
    try:
        port = srv.server_address[1]
        for path in ("index.html", "app.js", "app.css", "files/live.geojson", "files/meta.json"):
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


# ------------------------------------------------------------- the panel's contract in JS
# The page has no JS test runner (spec L: no npm, no build step), so these are text
# assertions on the wiring ticket 13 handed over. They catch a deleted rule, not a broken
# one; the rendering itself is checked by hand in a VISIBLE tab (MapLibre throttles rAF
# when hidden, so a headless screenshot is misleading).
def test_the_page_wires_the_live_panel_ids_ticket_13_stubbed():
    js = (live_export.REPO / "web" / "app.js").read_text()
    html = (live_export.REPO / "web" / "index.html").read_text()
    for el in ("livemeta", "delaystate", "rainstate", "livetoggle"):
        assert f'id="{el}"' in html, el
        assert f'"{el}"' in js, el
    assert 'getSource("live").setData' in js
    # vehicle_id is "MTA NYCT_1234": MapLibre 5.9.0 silently drops a source whose promoted
    # id is not integer-like, so no source may carry an actual promoteId assignment
    assert 'promoteId: "' not in js and "promoteId:'" not in js


def test_the_page_keeps_both_stale_thresholds_and_only_setdata_on_a_clean_tick():
    js = (live_export.REPO / "web" / "app.js").read_text()
    assert "live: 120" in js and "bronze: 900" in js   # spec L's two STALE cuts
    assert "cache: \"no-store\"" in js                 # a cached meta.json is a lie
    assert "STALE: the pipeline is not writing" in js
    # the delay wording is gated and never says "late"
    assert "over 5 min (agency-computed, unvalidated)" in js
    body = js.split("MTA-reported trip delay")[1]
    assert " late" not in body.lower().split("function liveTick")[0]


def test_the_toggle_waits_for_maplibre_to_parse_the_style():
    """Every branch of the toggle handler touches the `live` layer, and MapLibre throws on
    setPaintProperty / getSource for a layer the style has not parsed yet. Measured in a
    real tab: clicking the box the instant the page loaded killed the tick silently and
    left the panel reading "off" under a ticked box - the exact failure the panel exists to
    prevent. The box therefore ships disabled and app.js enables it on `load` - NOT on
    `styledata`, which fires while isStyleLoaded() is still false."""
    html = (live_export.REPO / "web" / "index.html").read_text()
    js = (live_export.REPO / "web" / "app.js").read_text()
    assert 'id="livetoggle" disabled' in html
    gate = js.split("$(\"livetoggle\").addEventListener")[0]
    assert 'map.once("load"' in gate and '$("livetoggle").disabled = false' in gate
    assert 'map.once("styledata", () => { $("livetoggle")' not in js


def test_the_rain_legend_names_the_uncalibrated_source_and_its_valid_stamp():
    html = (live_export.REPO / "web" / "index.html").read_text()
    assert "MRMS RadarOnly QPE 01H, uncalibrated, hour-ending," in html
    assert 'id="rainstate"' in html
    assert "valid ${m.precip_valid_ts}" in (live_export.REPO / "web" / "app.js").read_text()


# ==========================================================================================
# frontend 05 - the seven-layer chassis, pinned in the same page-as-data seam.
#
# There is still no JS test runner (spec L: no npm, no build step), so these read the page
# as DATA - its layer declarations, its rules, its gate keys, its budgets - and several of
# them derive the expected value from the PYTHON side (publish.LIVE_TERMS_VERIFIED,
# flood_truth.MAX_AGE_MIN) so that the page and the pipeline cannot drift apart silently.
# Every test below names, in its docstring, the mutation it kills; all of those mutations
# were applied to web/app.js and observed RED before this file was committed.
# ==========================================================================================
import re

from raincheck import flood_truth, publish

# frontend 02 D3, verbatim: ambient at the bottom, urgent on top.
SPEC_ORDER = ["bg", "zones-fill", "cells", "impact-fill", "cells-line", "impact-line",
              "zones-line", "locate", "live", "hist", "fn", "mta"]


def page_js() -> str:
    return (live_export.REPO / "web" / "app.js").read_text()


def page_html() -> str:
    return (live_export.REPO / "web" / "index.html").read_text()


def page_css() -> str:
    return (live_export.REPO / "web" / "app.css").read_text()


def style_layers(js: str) -> list[str]:
    """The layer ids the map style declares, in declaration order."""
    block = js.split("layers: [", 1)[1].split("\n    ],", 1)[0]
    return re.findall(r'\{ id: "([a-z-]+)"', block)


def layer_entries(js: str) -> dict[str, str]:
    """The LAYERS table, one source-text entry per layer id."""
    block = js.split("const LAYERS = [", 1)[1].split("\n];", 1)[0]
    out = {}
    for entry in block.split("\n\n"):
        m = re.search(r'\{ id: "(\w+)"', entry)
        if m:
            out[m.group(1)] = entry
    return out


def budgets(entry: str) -> list[str]:
    return [b.strip() for b in re.findall(r"budget: ([^,}\n]+)", entry)]


# ------------------------------------------------------------------ rule 1: declare at boot
def test_all_twelve_layers_are_declared_at_boot_in_the_frozen_order():
    """A lazily added layer lands on TOP of the order, so with anything lazy the stacking
    depends on CLICK order, and a `beforeId` naming a not-yet-added layer throws outright.
    MUTATION KILLED: moving any layer in the style block, dropping one, or adding one
    through a later addLayer() instead of declaring it here."""
    assert style_layers(page_js()) == SPEC_ORDER
    assert "addLayer(" not in page_js(), "a lazily added layer lands on top of the order"
    assert "addSource(" not in page_js()


def test_every_source_boots_empty_and_every_data_layer_boots_hidden():
    """An empty FeatureCollection at boot is what lets `cells` and the six not-yet-lit
    layers exist before their payload does; `visibility: "none"` is what stops them
    painting before the reader asks. MUTATION KILLED: booting a source straight off its
    URL again (which also re-creates the double fetch/parse of the 2.3 MB cells.geojson),
    or shipping a layer visible."""
    js = page_js()
    sources = js.split("sources: {", 1)[1].split("},", 1)[0]
    names = re.findall(r"(\w+): empty\(\)", sources)
    assert sorted(names) == ["cells", "fn", "hist", "impact", "live", "locate", "mta", "zones"]
    assert "empty = () => ({ type: \"geojson\", data: { type: \"FeatureCollection\", features: [] } })" in js
    assert 'data: "files/' not in sources, "a source booting off a URL cannot report its age"

    block = js.split("layers: [", 1)[1].split("\n    ],", 1)[0]
    for entry in re.split(r"\n      (?=\{ id: )", block):
        lid = re.search(r'\{ id: "([a-z-]+)"', entry)
        if not lid or lid.group(1) == "bg":     # `bg` is the background paint, not a source
            continue
        assert 'layout: { visibility: "none" }' in entry, lid.group(1)


# ------------------------------------------------- rule 4: the exclusive Cell fill channel
def test_the_cell_fill_is_a_radio_and_delay_cells_is_its_only_lit_option():
    """The delay layer and flood 17's impact overlay are the same quantity over the same
    Cells at two time-scales, so they share one channel. Exactly two layers claim it, the
    control is a RADIO in one named group, and the second option is dark until ticket 08
    lights the vehicle gate side. MUTATION KILLED: rendering the fill rows as checkboxes,
    dropping the group name (which makes two radios independently checkable), or marking
    a third layer `fill: true`."""
    js = page_js()
    entries = layer_entries(js)
    fills = [lid for lid, e in entries.items() if "fill: true" in e]
    assert fills == ["cells", "impact"]
    assert "impact" in entries and 'gate: "mta-vehicles"' in entries["impact"]
    row = js.split("function rowHTML", 1)[1].split("\n}", 1)[0]
    assert 'const kind = lyr.fill ? "radio" : "checkbox";' in row
    assert '\'name="cellfill"\'' in row
    assert "role=\"radiogroup\"" in page_html()


def test_two_cell_fills_can_never_be_held_at_once():
    """The radio group makes two fills unaskable in the markup; this makes them unholdable
    in the state, however the toggle was reached (a restored URL, a later slice calling
    toggle() directly). MUTATION KILLED: deleting the clear-the-others line from toggle(),
    or defaulting a second fill layer on."""
    js = page_js()
    body = js.split("async function toggle(id, want)", 1)[1].split("\n}", 1)[0]
    assert ("if (want && lyr.fill) for (const o of LAYERS) if (o.fill && o.id !== id) "
            "on[o.id] = false;") in body
    lit = [lid for lid, e in layer_entries(js).items()
           if "fill: true" in e and "open: true" in e]
    assert lit == ["cells"], "exactly one fill option opens lit"


# ------------------------------------------------------- the five states, and their order
def test_the_freshness_vocabulary_is_five_states_in_a_fixed_precedence():
    """FRESH / STALE(+reason) / OFF / GATED / AGE, one row per SOURCE. The ORDER is the
    contract: a gated layer reads GATED before it can read OFF, an unfetched one reads OFF
    before it can read STALE, and a source with no age reads STALE before any budget
    comparison - absent must never render as fresh-and-empty. MUTATION KILLED: dropping a
    state, reordering the branches (e.g. testing `on[]` before the gate, which would make a
    gated layer read OFF and lose the explanation), or letting a missing age fall through
    to FRESH."""
    body = page_js().split("function srcState(lyr, s)", 1)[1].split("\n}", 1)[0]
    order = [m for m in re.findall(r's: "(FRESH|STALE|OFF|GATED|AGE)"', body)]
    assert order == ["GATED", "OFF", "STALE", "AGE", "FRESH", "STALE"]
    assert "if (shut(lyr))" in body
    assert "if (!on[lyr.id])" in body
    assert "if (age === null || age === undefined)" in body
    assert "if (s.budget === null)" in body
    assert "age <= s.budget" in body
    # a layer is only as fresh as its worst source, and the worst-first order matches
    worst = page_js().split("const worst = (lyr)", 1)[1].split("};", 1)[0]
    assert '["GATED", "STALE", "OFF", "AGE", "FRESH"]' in worst


def test_only_a_source_with_a_frozen_budget_may_render_a_verdict():
    """frontend 02 D6, re-derived here rather than restated: of the nine sources the page
    reads, exactly THREE have a staleness budget frozen anywhere in the repo - the live
    pair (STALE_AFTER_S.live) and FloodNet (flood_truth.MAX_AGE_MIN). The other six render
    an AGE and judge nothing. MUTATION KILLED: guessing a budget for an unbudgeted source
    (the test counts them), copying the FloodNet number instead of deriving it (the test
    reads MAX_AGE_MIN), or giving the live pair a second, drifting copy of 120."""
    js = page_js()
    entries = layer_entries(js)
    all_budgets = [b for e in entries.values() for b in budgets(e)]
    assert len(all_budgets) == 9, "nine sources, nine budget declarations"
    assert all_budgets.count("null") == 6

    assert budgets(entries["live"]) == ["STALE_AFTER_S.live", "STALE_AFTER_S.live"]
    assert "const STALE_AFTER_S = { live: 120, bronze: 900 };" in js   # ticket 14's table
    assert budgets(entries["fn"]) == [str(flood_truth.MAX_AGE_MIN * 60)]
    for lid in ("zones", "cells", "mta", "impact", "hist"):
        assert budgets(entries[lid]) == ["null"] * len(budgets(entries[lid]))


def test_the_age_is_read_off_the_response_headers_and_never_off_a_payload():
    """frontend 01 D2. `Date` - `Last-Modified`, both from the origin, so a browser clock
    an hour behind cannot clamp an age to 0 and a CDN's cached copy errs stale. A payload
    stamp was rejected: it breaks test_export.py's byte-identity invariant AND it dates the
    write rather than the newest input. MUTATION KILLED: swapping either header for
    Date.now(), or reading an `as_of_utc` out of the body."""
    grab = page_js().split("async function grab(lyrId, s)", 1)[1].split("\n}", 1)[0]
    assert 'res.headers.get("Date")' in grab and 'res.headers.get("Last-Modified")' in grab
    assert "Date.now()" not in grab, "a browser clock cannot be allowed to fake freshness"
    assert "Math.max(0, (d - m) / 1000)" in grab
    assert 'cache: "no-store"' in grab


def test_a_missing_payload_is_stale_with_a_reason_and_never_an_empty_map():
    """A 404 and an empty FeatureCollection must not both paint an empty map under a fresh
    clock, and on the public host "run make live-export" is false in both halves - the
    files are not served because the gate is shut. MUTATION KILLED: treating !res.ok as a
    normal response, or recording an age for a response that carried no payload."""
    js = page_js()
    grab = js.split("async function grab(lyrId, s)", 1)[1].split("\n}", 1)[0]
    assert "if (!res.ok)" in grab
    assert 'res.status === 404 ? "not published on this host"' in grab
    assert "return null;" in grab
    assert 'whys["live/files/meta.json"] === "not published on this host"' in js


# --------------------------------------------------------------- the lineage gate, two sides
def test_both_lineage_gate_sides_exist_and_agree_with_the_publish_constant():
    """The MTA gate cuts by LINEAGE, so it has two sides: withholding the vehicles must
    never withhold the FloodNet tier, and opening the vehicles must never open MTA-derived
    alert rows. Ticket 08 lights a side by flipping ONE of these booleans. The expected
    value is DERIVED from publish.LIVE_TERMS_VERIFIED, so a page claiming a side is open
    while the pipeline refuses to publish it goes red here. MUTATION KILLED: one global
    switch instead of two keys, or a side opened on the page without the receipt."""
    js = page_js()
    block = js.split("const GATE = {", 1)[1].split("};", 1)[0]
    sides = dict(re.findall(r'"([a-z-]+)": (true|false)', block))
    assert set(sides) == {"mta-vehicles", "mta-alerts"}
    expected = "true" if publish.LIVE_TERMS_VERIFIED else "false"
    assert set(sides.values()) == {expected}, (
        "the page's gate sides disagree with publish.LIVE_TERMS_VERIFIED")
    assert "const shut = (lyr) => Boolean(lyr.gate) && !GATE[lyr.gate];" in js


def test_every_layer_names_its_gate_side_by_lineage():
    """Vehicle positions carry the live fleet AND flood 17's bus overlay; the alert rows
    carry the MTA flood tier. Nothing else is MTA-derived. MUTATION KILLED: gating the
    FloodNet tier (a layer with no MTA content) or leaving the bus overlay ungated."""
    entries = layer_entries(page_js())
    gates = {lid: re.search(r"gate: (\"[a-z-]+\"|null)", e).group(1)
             for lid, e in entries.items()}
    assert gates == {"zones": "null", "cells": "null", "live": '"mta-vehicles"',
                     "fn": "null", "mta": '"mta-alerts"', "impact": '"mta-vehicles"',
                     "hist": "null"}


def test_a_gated_layer_renders_dark_and_explained_never_absent():
    """Absence should be explained, not mysterious: the row stays, the box is disabled, the
    chip keeps its own hue and the reason is printed - and a gated layer never fetches.
    MUTATION KILLED: filtering gated layers out of the panel, or letting toggle() fetch one."""
    js, html = page_js(), page_html()
    row = js.split("function rowHTML", 1)[1].split("\n}", 1)[0]
    assert "const dark = shut(lyr);" in row
    assert "dark || !styled ? \"disabled\" : \"\"" in row
    assert "does not exist" in row                       # the printed reason
    toggle = js.split("async function toggle(id, want)", 1)[1].split("\n}", 1)[0]
    assert "if (shut(lyr)) return;" in toggle
    assert "not\n  verified" in html and 'id="mta-gate"' in html   # the deploy-time sentence


def test_the_four_not_yet_landed_sources_are_honest_off_or_gated_chips():
    """Rendering truthfully with layers dark is the design requirement, not a degraded
    mode. Each of the four names the ticket that owes its payload, so a reader is told what
    is missing rather than shown an empty map. MUTATION KILLED: deleting a not-yet-landed
    layer until its writer ships (which is what forces the re-plumbing tickets 07/08 are
    meant to be spared), or claiming a payload the page cannot draw."""
    entries = layer_entries(page_js())
    owed = {lid: re.search(r'owed: (\"[a-z0-9 ]+\"|null)', e).group(1)
            for lid, e in entries.items()}
    assert owed == {"zones": "null", "cells": "null", "live": "null", "fn": '"flood 15"',
                    "mta": '"flood 15"', "impact": '"flood 17"', "hist": '"notify 05"'}
    for lid in ("fn", "mta", "impact"):
        assert "draw: null" in entries[lid], f"{lid} may not claim to paint a payload it has not seen"


# ---------------------------------------------------------------- keyboard, mobile, layout
def test_toggling_a_layer_restores_focus_the_way_the_hour_buttons_do():
    """Rebuilding the rows destroys the control the reader just activated and focus falls to
    <body>, so a keyboard user tabs through the map and every other row again on each
    toggle - measured by clicking the prototype, not by eye. setHour() already solved this
    for the hour buttons; renderLayers reuses the same restore. MUTATION KILLED: dropping
    the restore from either place."""
    js = page_js()
    for fn in ("function renderLayers()", "function setHour(k)"):
        body = js.split(fn, 1)[1].split("\n}", 1)[0]
        assert "document.activeElement" in body, fn
        assert ".focus();" in body, fn
    restore = js.split("function renderLayers()", 1)[1].split("\n}", 1)[0]
    assert 'document.querySelector(`#layers [data-l="${keep}"]`)' in restore
    # the change handler is delegated to the stable container, so a rebuilt row keeps working
    assert '$("layers").addEventListener("change"' in js


def test_a_small_screen_opens_with_the_fill_on_and_every_point_layer_off():
    """frontend 02 D7: the 60vh map strip carries about two layers legibly at 375 px. The
    panel set itself does NOT collapse - it was measured at 375 px and nothing overlaps.
    MUTATION KILLED: a later slice defaulting a point layer on (the rule reads `l.point`,
    so a new point layer is covered without touching this code), or dropping the rule and
    opening seven layers on a phone."""
    js = page_js()
    assert 'window.matchMedia("(max-width: 900px)").matches' in js
    assert "LAYERS.forEach(l => { on[l.id] = l.open && !(SMALL && l.point); });" in js
    entries = layer_entries(js)
    points = {lid for lid, e in entries.items() if "point: true" in e}
    assert points == {"live", "fn", "mta", "hist"}
    opens = {lid for lid, e in entries.items() if "open: true" in e}
    assert opens == {"zones", "cells"}, "nothing but the ground and the fill opens lit"
    assert "@media (max-width: 900px)" in page_css()


def test_nothing_is_positioned_against_a_guessed_provenance_height():
    """The strip is mode-invariant (a spec sec.9 condition), its height changes with the
    attribution text and with every width, and a hard-coded clearance put the last toggle
    UNDERNEATH it in the prototype, where a real click never reached it. MUTATION KILLED:
    restoring a literal clearance, or dropping the observer that measures the strip."""
    css, js = page_css(), page_js()
    assert "bottom: 84px" not in css
    for col in ("#left", "#right"):
        rule = css.split(col + " { position: absolute;", 1)[1].split("}", 1)[0]
        assert "bottom: var(--prov)" in rule, col
    assert '$("provenance").offsetHeight' in js
    assert 'setProperty(\n  "--prov"' in js
    assert 'observe($("provenance"))' in js


def test_the_frozen_ramps_are_byte_untouched_and_the_new_hues_sit_beside_them():
    """frontend 02 D2: four new hues, none on either arm of the diverging ramp, and the
    ramp itself is not renegotiated. MUTATION KILLED: nudging a ramp stop, or reusing an
    existing colour for a new meaning."""
    js = page_js()
    assert ('const RATIO_STOPS = [[0.5, "#7f0000"], [0.65, "#d7301f"], [0.8, "#fc8d59"], '
            '[0.9, "#fdd49e"],\n                     [1.0, "#f7f7f7"], [1.1, "#c7dcef"], '
            '[1.2, "#6baed6"]];') in js
    assert ('const SPEED_STOPS = [[2, "#0d1b2a"], [3.5, "#1b4965"], [5, "#3d7ea6"], '
            '[6.5, "#7fb3d5"], [8, "#cfe6f4"]];') in js
    assert 'const GREY = "#3a4049";' in js
    for name, hue in (("WATER", "#35d6c2"), ("ALERT", "#ffc447"),
                      ("HIST", "#8f7bd6"), ("GATED_HUE", "#d2a24c")):
        assert f'const {name} = "{hue}";' in js
    ramp = {c for _, c in re.findall(r"\[([\d.]+), \"(#\w+)\"\]", js)}
    assert not ramp & {"#35d6c2", "#ffc447", "#8f7bd6", "#d2a24c"}
    assert ".st-GATED { color: #d2a24c; }" in page_css()


def test_a_dry_floodnet_sensor_is_a_hollow_ring_not_a_fifth_grey():
    """At 2.6 px a dry sensor, a dimmed vehicle and the "no publishable value" Cell fill
    were three meanings on one #3a4049. A sensor reporting water is a filled aqua disc; a
    dry or stale one is a STROKE with no fill, so it differs by MARK and not only by hue.
    MUTATION KILLED: painting the dry sensor grey (or any solid fill) again."""
    js = page_js()
    fn = js.split('{ id: "fn", type: "circle"', 1)[1].split('{ id: "mta"', 1)[0]
    assert '"circle-color": ["case", ["get", "display"], WATER, "rgba(0,0,0,0)"]' in fn
    assert '"circle-stroke-color": ["case", ["get", "display"], "#0b0d10", WATER]' in fn
    assert GREY_HEX not in fn, "a dry sensor may not be a fourth meaning on the grey"


GREY_HEX = "#3a4049"


def test_the_page_wires_the_layer_panel_ids():
    """The chassis's own seam: tickets 07 and 08 mount into these ids."""
    html, js = page_html(), page_js()
    for el in ("layers", "layers-fill", "layers-pts", "src-live", "live-chip", "right"):
        assert f'id="{el}"' in html, el
        if el != "right":
            assert f'"{el}"' in js, el
    # the live fleet's row IS the Live panel: one control, never two for one layer
    assert 'toggle: "livetoggle"' in js
    assert 'LAYERS.filter(l => !l.fill && !l.toggle).map(rowHTML)' in js
