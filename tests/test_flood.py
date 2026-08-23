"""Flood-build ticket 04: the observation table and the event spine.

Seam 1 (DuckDB contract assertions over the written tables) and seam 2 (pure functions on
fixtures). No network anywhere: every snapshot under the fixture root is cut from the real
one this ticket fetched, through the same file names the builders read, so the fixtures
carry the sources' real quirks — the coordinate-less 311 report, the FloodNet sensor with
no deployment row, the GUID-keyed pre-2020 alert archive, both Storm Events CZ_TYPEs, and
the two alert events that disagree about Utica Av.

Years with no fixture rows are written as EMPTY snapshots rather than left absent: absent
would send the builders to the network, and empty is what a quiet year really looks like.
"""
import json
import shutil
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from raincheck import duck, flood_alerts as fa, flood_obs as fo, flood_spine as fs

FIXTURES = Path(__file__).parent / "fixtures"
ASOF = fo.ASOF
# the fixture snapshots hold a handful of days, so the spine runs on its own thresholds;
# the frozen pins are asserted against the real daily series in their own test below
FIXTURE_P99 = {"76ig-c548": 5, "erm2-nwe9": 10}
REFERENCE_DAY = date(2023, 9, 29)


def _land(root: Path) -> None:
    snap = root / "archive" / "flood"
    snap.mkdir(parents=True)
    for src, dst in (
            ("flood_311_76ig-c548.json", f"311_76ig-c548_{ASOF}.json"),
            ("flood_311_erm2-nwe9.json", f"311_erm2-nwe9_{ASOF}.json"),
            ("flood_floodnet_events.json", f"floodnet_events_{ASOF}.json"),
            ("flood_floodnet_sensors.json", f"floodnet_sensors_{ASOF}.json"),
            ("flood_alerts_3h5b-5ktz.json", f"alerts_3h5b-5ktz_{ASOF}.json"),
            ("flood_alerts_7kct-peq7.json", f"alerts_7kct-peq7_{ASOF}.json"),
            ("flood_hwm_event24.json", f"usgs_hwm_event24_{ASOF}.json"),
            ("flood_sandy.json", f"sandy_{fo.SANDY_ZONE}_{ASOF}.json"),
            ("flood_ghcn.csv", f"ghcn_{fs.GHCN_STATION}_{ASOF}.csv")):
        shutil.copy(FIXTURES / src, snap / dst)
    # Ida's marks are not in the fixture set: an event with no NYC rows is still a real
    # answer, and the empty snapshot keeps the builder off the network
    (snap / f"usgs_hwm_event312_{ASOF}.json").write_text("[]")

    for year in range(fs.STORM_FROM, ASOF.year + 1):
        out = snap / f"stormevents_{year}_{ASOF}.csv"
        src = FIXTURES / f"flood_stormevents_{year}.csv"
        if src.exists():
            shutil.copy(src, out)
        else:  # header only: that year published no New York rows
            out.write_text("STATE,EVENT_TYPE,CZ_TYPE,CZ_FIPS,CZ_NAME,FLOOD_CAUSE,"
                           "BEGIN_DATE_TIME,END_DATE_TIME\n")
    for station in fs.NWS_MINOR_STND_FT:
        for year in range(fs.COOPS_FROM, ASOF.year + 1):
            out = snap / f"coops_{station}_{year}_{ASOF}.json"
            src = FIXTURES / f"flood_coops_{station}_{year}.json"
            if src.exists():
                shutil.copy(src, out)
            else:  # the shape datagetter really answers for a dark station-year
                out.write_text(json.dumps({"error": {"message": "No data was found."}}))

    assets = root / "ref" / "assets"
    assets.mkdir(parents=True)
    shutil.copy(FIXTURES / "flood_ref_assets.parquet", assets / "part-00000.parquet")
    # the archiver's own capture, at the path the live-era reader globs
    capture = root / "archive" / "subway_alerts" / "date=2026-08-21"
    capture.mkdir(parents=True)
    shutil.copy(FIXTURES / "flood_alerts_water.parquet", capture / "part-00000.parquet")


@pytest.fixture(scope="module")
def flood_root(spark, tmp_path_factory):
    root = tmp_path_factory.mktemp("flood")
    _land(root)
    fo.build(root, spark, ASOF, expect=None)
    fs.build(root, ASOF, thresholds=FIXTURE_P99)
    return root


@pytest.fixture(scope="module")
def con():
    return duck.connect()


@pytest.fixture(scope="module")
def obs(con, flood_root):
    return duck.table(con, flood_root / "silver" / "flood_obs")


@pytest.fixture(scope="module")
def events(con, flood_root):
    return duck.table(con, flood_root / "silver" / "flood_events")


def one(rel, sql):
    return rel.query("t", sql).fetchall()


# ---- seam 2: the window is a calendar fact ----------------------------------------

def test_the_window_is_midnight_pad_three_hours_in_utc():
    """[NY-midnight of the first day - 3 h, NY-midnight after the last day + 3 h]. EDT
    puts NY midnight at 04:00 UTC, EST at 05:00 — the rule is stated in NY wall time and
    lands on whole UTC hours either way, so it needs no rounding."""
    assert fs.window(REFERENCE_DAY, REFERENCE_DAY) == (
        datetime(2023, 9, 29, 1, tzinfo=timezone.utc),
        datetime(2023, 9, 30, 7, tzinfo=timezone.utc))
    assert fs.window(date(2018, 1, 8), date(2018, 1, 8)) == (
        datetime(2018, 1, 8, 2, tzinfo=timezone.utc),
        datetime(2018, 1, 9, 8, tzinfo=timezone.utc))
    # a multi-day event pads once, at the ends
    assert fs.window(date(2012, 10, 28), date(2012, 10, 30)) == (
        datetime(2012, 10, 28, 1, tzinfo=timezone.utc),
        datetime(2012, 10, 31, 7, tzinfo=timezone.utc))


def test_the_window_survives_the_dst_switch():
    """A fall-back event day is 25 h long in NY. The bounds still land on whole hours, and
    the window still covers every hour of the day it names."""
    start, end = fs.window(date(2023, 11, 5), date(2023, 11, 5))
    assert (start.minute, end.minute) == (0, 0)
    assert (end - start).total_seconds() / 3600 == 25 + 2 * fs.PAD_H


def test_the_window_is_never_observation_derived(events):
    """The circularity refutation, asserted on the written table: every window is exactly
    the calendar rule applied to the event's own days. No observation timestamp can widen
    it, so the spine cannot confirm its own labels."""
    for day_start, day_end, start, end in one(
            events, "SELECT day_start, day_end, window_start_utc, window_end_utc FROM t"):
        assert (start, end) == fs.window(day_start, day_end)


def test_contiguous_days_merge_and_a_gap_splits():
    assert fs.runs({date(2023, 9, 29)}) == [(REFERENCE_DAY, REFERENCE_DAY)]
    assert fs.runs({date(2012, 10, 28), date(2012, 10, 29), date(2012, 10, 30)}) == [
        (date(2012, 10, 28), date(2012, 10, 30))]
    assert fs.runs({date(2021, 9, 1), date(2021, 9, 2), date(2021, 9, 4)}) == [
        (date(2021, 9, 1), date(2021, 9, 2)), (date(2021, 9, 4), date(2021, 9, 4))]


# ---- seam 2: the frozen 311 pins --------------------------------------------------

def test_p99_is_nearest_rank():
    """Nearest rank, never interpolated: the ceil(0.99 N)-th smallest of the days that
    have a report at all. A threshold has to be a count a day can actually hit."""
    series = {date(2020, 1, 1) + timedelta(n): n + 1 for n in range(100)}
    assert fs.p99(series) == 99
    assert fs.p99(series, 0.95) == 95
    # days with no report are not days: they must not drag the rank down
    series[date(2021, 1, 1)] = 0
    assert fs.p99(series) == 99


def test_the_frozen_p99_pins_reproduce_on_the_measured_series():
    """The pins ARE the event universe: every boundary, label and fold downstream moves if
    they move. Re-measured here on the real daily series (5,485 days), so a rebuild years
    later reproduces the same spine — or fails this test first."""
    series = json.loads((FIXTURES / "flood_311_daily.json").read_text())
    measured = {ds: fs.p99({date.fromisoformat(d): n for d, n in days.items()})
                for ds, days in series.items()}
    assert measured == fs.P99_311 == {"76ig-c548": 97, "erm2-nwe9": 85}


def test_the_four_literal_union_is_what_puts_the_reference_day_in_the_spine():
    """2023-09-29 is the reference storm AND the week the city renamed the descriptors.
    Under the union it is the modern era's biggest day by a factor of three."""
    series = json.loads((FIXTURES / "flood_311_daily.json").read_text())["erm2-nwe9"]
    assert series["2023-09-29"] == 1233 >= fs.P99_311["erm2-nwe9"]
    assert max(series.values()) == series["2023-09-29"]
    assert fo.DESCRIPTORS == ("Street Flooding (SJ)", "Highway Flooding (SH)",
                              "Flooding on Street", "Flooding on Highway")


# ---- seam 2: classification -------------------------------------------------------

def _trig(**kw):
    base = dict.fromkeys(("by_311", "by_alert", "by_storm", "by_tide", "by_storm_pluvial",
                          "by_storm_coastal"), False)
    return {**base, **kw}


def test_class_from_triggers():
    day = date(2023, 9, 29)
    assert fs.classify(_trig(by_311=True), None, day, day, 20.0) == fs.PLUVIAL
    assert fs.classify(_trig(by_tide=True), None, day, day, 20.0) == fs.COASTAL
    assert fs.classify(_trig(by_311=True, by_tide=True), None, day, day, 20.0) == fs.MIXED
    # a Coastal Flood row with no gauge crossing is still coastal: the Rockaways have no
    # gauge at all, so tide silence is not evidence of no surge
    assert fs.classify(_trig(by_storm=True, by_storm_coastal=True), None, day, day,
                       20.0) == fs.COASTAL


def test_storm_events_flood_cause_speaks_first():
    day = date(2021, 9, 1)
    assert fs.classify(_trig(by_311=True), "Heavy Rain", day, day, 25.0) == fs.PLUVIAL
    assert fs.classify(_trig(by_311=True), "Heavy Rain / Snow Melt", day, day,
                       2.0) == fs.SNOWMELT


def test_a_freezing_winter_event_reclasses_to_snowmelt():
    """Dec-Mar pluvial days at or below freezing are snowmelt-driven; they keep their
    labels and leave the pluvial fit. The rule is the whole event, not one hour of it."""
    jan = date(2018, 1, 8)
    assert fs.classify(_trig(by_alert=True), None, jan, jan, -3.0) == fs.SNOWMELT
    assert fs.classify(_trig(by_alert=True), None, jan, jan, 0.0) == fs.SNOWMELT
    assert fs.classify(_trig(by_alert=True), None, jan, jan, 0.1) == fs.PLUVIAL
    # July never reclasses, however the arithmetic is fed
    jul = date(2021, 7, 8)
    assert fs.classify(_trig(by_alert=True), None, jul, jul, -3.0) == fs.PLUVIAL
    # and with no reading the class is not guessed
    assert fs.classify(_trig(by_alert=True), None, jan, jan, None) == fs.UNCLASSIFIED


def test_coverage_calendars_carry_the_alert_holes():
    assert fs.covered("311", date(2010, 6, 1), date(2010, 6, 1))
    assert not fs.covered("311", date(2009, 12, 31), date(2009, 12, 31))
    assert not fs.covered("floodnet", date(2020, 11, 15), date(2020, 11, 15))
    assert fs.covered("alert", date(2019, 5, 1), date(2019, 5, 1))
    assert not fs.covered("alert", date(2020, 4, 10), date(2020, 4, 10))   # the 2020 hole
    assert not fs.covered("alert", date(2026, 7, 15), date(2026, 7, 15))   # Socrata -> archiver
    # one dark day inside a multi-day event is enough to mark the event uncovered
    assert not fs.covered("alert", date(2020, 3, 31), date(2020, 4, 1))


# ---- seam 2: cross-event reconciliation (this ticket's job) ------------------------

def _pair(event_id, complex_id, first, last, state, name="Utica Av"):
    return {"event_id": event_id, "complex_id": complex_id, "first_seen": first,
            "last_seen": last, "state": state, "name": name}


def test_concurrent_events_that_disagree_reconcile_to_one_observation():
    """The measured case: 264048 ends ACTIVE on Utica Av while 264063 reports it cleared,
    because each event carries only its own newest revision. They overlap in time, so they
    are one flood — one row, and the newest revision across both owns the state."""
    got = fo.reconcile([_pair("264048", "181", 1000, 3000, fa.ACTIVE),
                        _pair("264063", "181", 2000, 4000, fa.CLEARED_STATE)])
    assert len(got) == 1
    assert got[0]["event_ids"] == ["264048", "264063"]
    assert (got[0]["first_seen"], got[0]["last_seen"]) == (1000, 4000)
    assert got[0]["state"] == fa.CLEARED_STATE


def test_floods_that_do_not_overlap_stay_two_observations():
    """Reconciliation must not swallow a second flood at the same complex weeks later."""
    got = fo.reconcile([_pair("1", "181", 1000, 2000, fa.CLEARED_STATE),
                        _pair("2", "181", 900_000, 910_000, fa.ACTIVE)])
    assert [o["event_ids"] for o in got] == [["1"], ["2"]]


def test_reconciliation_does_not_depend_on_row_order():
    import random

    pairs = [_pair("264031", "624", 100, 400, fa.CLEARED_STATE, "World Trade Center"),
             _pair("264043", "624", 300, 900, fa.CLEARED_STATE, "World Trade Center"),
             _pair("264063", "624", 800, 950, fa.CLEARED_STATE, "Chambers St"),
             _pair("264048", "181", 100, 500, fa.ACTIVE)]
    want = fo.reconcile(pairs)
    assert sorted(len(o["event_ids"]) for o in want) == [1, 3]
    for seed in range(5):
        shuffled = pairs[:]
        random.Random(seed).shuffle(shuffled)
        assert fo.reconcile(shuffled) == want


# ---- seam 2: three alert eras, one frozen grammar ---------------------------------

def test_both_socrata_eras_render_into_the_frozen_alert_grammar():
    """The 2012-2020 archive keys incidents by a status_id GUID and the 2020+ one by
    event_id/update_number. Both become ticket 02's alert_id, so ONE extractor with one
    measured precision serves every era."""
    old = fo.adapt_socrata_alerts([
        {"status_id": "F1C32585-C44D-4894-9CC1-0489EF8A021C", "date": "2018-01-08T05:00:00.000",
         "header": "h", "description": "d", "affected": "A|C"},
        {"status_id": "F1C32585-C44D-4894-9CC1-0489EF8A021C", "date": "2018-01-08T06:00:00.000",
         "header": "h2", "description": "d", "affected": "A"}], "old")
    keys = [fa.alert_key(r["alert_id"]) for r in old]
    assert None not in keys, "the GUID era no longer parses into the frozen grammar"
    assert {k[0] for k in keys if k} == {"F1C32585-C44D-4894-9CC1-0489EF8A021C"}
    assert sorted({k[1] for k in keys if k}) == [0, 1]  # update = rank within the incident
    assert sorted(r["route_id"] for r in old[:2]) == ["A", "C"]  # one row per route

    new = fo.adapt_socrata_alerts([
        {"event_id": "117601", "update_number": "3", "date": "2023-09-29T12:00:00.000",
         "header": "h", "description": "d", "affected": "1"}], "new")
    assert fa.alert_key(new[0]["alert_id"]) == ("117601", 3)


def test_the_pre_2020_update_number_is_a_function_of_the_snapshot_not_the_order():
    import random

    rows = [{"status_id": "G", "date": f"2018-01-0{n}T05:00:00.000", "header": f"h{n}",
             "description": "d", "affected": "A"} for n in range(1, 6)]
    want = [r["alert_id"] for r in fo.adapt_socrata_alerts(rows, "old")]
    for seed in range(5):
        shuffled = rows[:]
        random.Random(seed).shuffle(shuffled)
        assert [r["alert_id"] for r in fo.adapt_socrata_alerts(shuffled, "old")] == want


# ---- seam 1: the written observation table ----------------------------------------

def test_flood_obs_grain_and_label_grade_sources(obs):
    (total, keys, celled, geoms) = one(obs, "SELECT count(*), count(DISTINCT (source, "
                                       "source_id)), count(cell), count(geometry) FROM t")[0]
    assert total == keys == celled == geoms
    assert {s for (s,) in one(obs, "SELECT DISTINCT source FROM t")} <= set(fo.SOURCES)
    assert {k for (k,) in one(obs, "SELECT DISTINCT obs_ts_kind FROM t")} <= set(fo.OBS_TS_KIND)
    # the covariate sources the design bars from this table
    assert not one(obs, "SELECT * FROM t WHERE source IN ('nfip','sewer_backup',"
                        "'catch_basin','mycoast','storm_events','coops')")


def test_every_source_lands_rows(obs):
    got = dict(one(obs, "SELECT source, count(*) FROM t GROUP BY 1"))
    assert set(got) == set(fo.SOURCES), got
    assert got["sandy"] == 3 and got["usgs_hwm"] == 8


def test_311_rows_carry_only_the_four_frozen_literals(obs):
    assert {t for (t,) in one(obs, "SELECT DISTINCT text FROM t WHERE source='311'")} \
        <= set(fo.DESCRIPTORS)


def test_a_report_with_no_coordinate_is_counted_but_never_placed(obs):
    """It is still a report — it is in the daily series the p99 trigger is cut on — but it
    cannot attach to an asset, so it mints no observation."""
    raw = json.loads((FIXTURES / "flood_311_erm2-nwe9.json").read_text())
    bare = [r for r in raw if not r.get("latitude")]
    assert bare, "the fixture no longer exercises the coordinate-less path"
    placed = {k for (k,) in one(obs, "SELECT source_id FROM t WHERE source='311'")}
    assert not {r["unique_key"] for r in bare} & placed
    assert fo.daily_311(raw)[date.fromisoformat(bare[0]["created_date"][:10])] >= 1


def test_depth_is_millimetres_and_only_where_a_source_measures_it(obs):
    """FloodNet publishes inches; depth_mm is the only depth column and it is mm. A USGS
    mark is an elevation, not a depth above ground, so it stays NULL rather than pretending."""
    assert not one(obs, "SELECT * FROM t WHERE depth_mm IS NOT NULL AND source <> 'floodnet'")
    events = json.loads((FIXTURES / "flood_floodnet_events.json").read_text())
    deepest = max(float(e["max_depth_inches"]) for e in events if e.get("max_depth_inches"))
    (got,) = one(obs, "SELECT max(depth_mm) FROM t WHERE source='floodnet'")[0]
    assert got == pytest.approx(deepest * 25.4)


def test_floodnet_stamps_are_utc_not_new_york(obs):
    """Measured against the pipeline's own AORC rain: reading these stamps as local would
    shift the evening events onto the wrong NY day. The fixture pins the rule."""
    events = json.loads((FIXTURES / "flood_floodnet_events.json").read_text())
    sample = min(e["flood_start_time"] for e in events if e.get("flood_start_time"))
    (got,) = one(obs, f"SELECT ts_utc FROM t WHERE source='floodnet' AND source_id LIKE "
                      f"'%{sample}' LIMIT 1")[0]
    assert got == datetime.fromisoformat(sample).replace(tzinfo=timezone.utc)


def test_a_sensor_with_no_deployment_row_mints_nothing(obs):
    """The event table is not a subset of the deployment table (measured: one sensor has
    events but no deployment row). An event with no point is no label — it must be dropped,
    never landed at (0, 0)."""
    events = json.loads((FIXTURES / "flood_floodnet_events.json").read_text())
    located = {s["sensor_id"] for s in
               json.loads((FIXTURES / "flood_floodnet_sensors.json").read_text())}
    orphan = {e["sensor_id"] for e in events} - located
    assert orphan == {"BK-w-st-kent-st-31i7yc"}, "the fixture no longer exercises the drop"
    placed = {sid.rsplit(":", 1)[0] for (sid,) in
              one(obs, "SELECT source_id FROM t WHERE source='floodnet'")}
    assert placed and not placed & orphan


def test_one_alert_row_per_complex_per_physical_flood(obs):
    """Ticket 02 mints one observation per (event, complex); the reconciliation lands ONE
    row on the complex per flood, so the World Trade Center night is not counted four
    times. The merged event ids stay visible in source_id."""
    rows = one(obs, "SELECT source_id, text FROM t WHERE source='mta_alert' ORDER BY 1")
    merged = [sid for sid, _ in rows if "+" in sid.split(":")[0]]
    assert merged, "the fixture no longer exercises a cross-event merge"
    for sid, name in rows:
        merged_events, complex_id = sid.rsplit(":", 1)
        assert complex_id and merged_events and name
    assert len({sid.rsplit(":", 1)[1] for sid, _ in rows}) <= len(rows)


# ---- seam 1: the written spine ----------------------------------------------------

def test_flood_events_grain(events):
    rows = one(events, "SELECT event_id, day_start, day_end, n_days FROM t ORDER BY day_start")
    assert rows, "the fixture spine is empty"
    assert len({r[0] for r in rows}) == len(rows)
    for event_id, day_start, day_end, n_days in rows:
        assert event_id == day_start.isoformat()
        assert day_start <= day_end
        assert n_days == (day_end - day_start).days + 1
    # merged means merged: no two events may touch or overlap
    for (_, _, end, _), (_, nxt, _, _) in zip(rows, rows[1:]):
        assert (nxt - end).days > 1


def test_the_reference_day_is_an_event_day(events):
    """The fixture requirement: 2023-09-29 appears in the spine under the four-literal
    union. It is the day the city renamed the descriptors, so the two-literal set both
    loses the day's labels and biases the threshold that would admit it."""
    rows = one(events, f"SELECT event_id, by_311, by_alert, event_class, window_start_utc, "
                       f"window_end_utc FROM t WHERE day_start <= DATE '{REFERENCE_DAY}' "
                       f"AND day_end >= DATE '{REFERENCE_DAY}'")
    assert len(rows) == 1
    event_id, by_311, by_alert, klass, start, end = rows[0]
    assert (by_311, by_alert, klass) == (True, True, fs.PLUVIAL)
    assert (start, end) == fs.window(REFERENCE_DAY, REFERENCE_DAY)


def test_every_event_carries_a_trigger_and_a_class(events):
    assert not one(events, "SELECT * FROM t WHERE NOT (by_311 OR by_alert OR by_storm "
                           "OR by_tide)")
    assert {k for (k,) in one(events, "SELECT DISTINCT event_class FROM t")} <= {
        fs.PLUVIAL, fs.COASTAL, fs.MIXED, fs.SNOWMELT, fs.UNCLASSIFIED}


def test_the_tide_trigger_needs_two_consecutive_readings(flood_root):
    """Sandy's surge at the Battery, from the real hourly series: 17.27 ft against a
    10.49 ft NWS minor, station datum on both sides, no arithmetic in between."""
    hit, seen = fs.days_tide(flood_root, ASOF)
    assert date(2012, 10, 29) in hit
    assert date(2012, 10, 28) in seen
    readings = fs._coops_year(flood_root, "8518750", 2012, ASOF)
    assert max(v for _, v in readings) > fs.NWS_MINOR_STND_FT["8518750"]
    # a dark station-year is coverage=missing, never an implicit non-event
    assert fs._coops_year(flood_root, "8518750", 2015, ASOF) == []


def test_the_tide_rule_rejects_a_single_spike_and_a_gap():
    """Two CONSECUTIVE readings is the whole point of the rule: one reading is a spike, and
    two exceedances separated by an outage are two spikes. A run must be adjacent in time."""
    at = lambda h, v: (datetime(2012, 10, 29, h, tzinfo=timezone.utc), v)
    minor = fs.NWS_MINOR_STND_FT["8518750"]
    assert fs.exceedance_days([at(1, 12.0), at(2, 9.0)], minor) == set()
    assert fs.exceedance_days([at(1, 12.0), at(2, 11.0)], minor) == {date(2012, 10, 29)}
    assert fs.exceedance_days([at(1, 12.0), at(6, 12.0)], minor) == set()   # across a gap
    # and the frozen rule is TWO: one reading must not be enough
    assert fs.COOPS_CONSECUTIVE == 2
    assert fs.exceedance_days([at(1, 12.0), at(2, 9.0)], minor, consecutive=1) == {
        date(2012, 10, 29)}
    # at or above, never above
    assert fs.exceedance_days([at(1, minor), at(2, minor)], minor) == {date(2012, 10, 29)}


def test_the_311_trigger_is_at_or_above_the_threshold(flood_root):
    """'at or above the frozen p99' — the boundary day itself is an event-day."""
    series = fo.daily_311(fo.rows_311(flood_root, ASOF)["erm2-nwe9"])
    day, count = max(series.items(), key=lambda kv: kv[1])
    assert day in fs.days_311(flood_root, ASOF, {"76ig-c548": 99, "erm2-nwe9": count})
    assert day not in fs.days_311(flood_root, ASOF,
                                  {"76ig-c548": 99, "erm2-nwe9": count + 1})


def test_the_alert_coverage_floor_is_the_label_era_not_the_dataset_era():
    """The archives open 2012-10-02 but the flood signal is effectively 2016+. Marking the
    sparse years covered would mint false negatives in ticket 05's anti-join."""
    assert fo.ALERT_LABELS_FROM == date(2016, 1, 1)
    assert not fs.covered("alert", date(2013, 6, 1), date(2013, 6, 1))
    assert fs.covered("alert", date(2016, 6, 1), date(2016, 6, 1))


def test_coverage_flags_follow_the_frozen_calendars(events):
    for day_start, day_end, c311, calert, cnet in one(
            events, "SELECT day_start, day_end, cov_311, cov_alert, cov_floodnet FROM t"):
        assert c311 == fs.covered("311", day_start, day_end)
        assert calert == fs.covered("alert", day_start, day_end)
        assert cnet == fs.covered("floodnet", day_start, day_end)


def test_a_dark_or_lagging_source_is_written_as_uncovered(events, flood_root):
    """Coverage=missing, never an implicit non-event. Storm Events LAGS (the real source
    has published through 2026-05-29 while the spine runs to today), and the fixture's
    tide series is one station-year, so both flags must actually vary rather than being
    hardcoded true."""
    _, through = fs.storm_rows(flood_root, ASOF)
    for day_end, cov_storm in one(events, "SELECT day_end, cov_storm FROM t"):
        assert cov_storm == (day_end <= through)
    _, seen = fs.days_tide(flood_root, ASOF)
    for day_start, n_days, cov_tide in one(
            events, "SELECT day_start, n_days, cov_tide FROM t"):
        assert cov_tide == all(day_start + timedelta(n) in seen for n in range(n_days))
    # the fixture must exercise BOTH values of each flag, or it is asserting nothing
    assert {c for (c,) in one(events, "SELECT DISTINCT cov_tide FROM t")} == {True, False}


def test_the_spine_version_moves_with_the_thresholds(events):
    """Ticket 18 re-derives the spine at alternate 311 thresholds; every alternate universe
    must stamp differently from the primary, or the artifacts cannot be told apart."""
    (stamped,) = {v for (v,) in one(events, "SELECT DISTINCT spine_version FROM t")}
    assert stamped == fs.spine_version(ASOF, FIXTURE_P99)
    assert stamped != fs.spine_version(ASOF, fs.P99_311)
    assert stamped != fs.spine_version(date(2026, 8, 24), FIXTURE_P99)


def test_the_derivation_is_a_pure_function_of_its_day_sets():
    """Ticket 18 parameterizes THIS function rather than forking the logic."""
    days = {"311": {REFERENCE_DAY}, "alert": {date(2023, 9, 30)}}
    got = fs.derive(days, {}, {REFERENCE_DAY: 22.0})
    assert [(e["event_id"], e["n_days"], e["event_class"]) for e in got] == [
        ("2023-09-29", 2, fs.PLUVIAL)]
    assert fs.derive(days, {}, {REFERENCE_DAY: 22.0}) == got
    assert fs.derive({}, {}, {}) == []


def test_storm_rows_read_both_cz_types(flood_root):
    """CZ_FIPS is a county code under CZ_TYPE='C' and an unrelated NWS zone number under
    'Z', and every NYC coastal-flood row is zone-coded — a county filter alone drops all
    of them, Sandy included."""
    rows, through = fs.storm_rows(flood_root, ASOF)
    assert through is not None and through >= date(2023, 9, 29)
    kinds = {(r["EVENT_TYPE"], r["CZ_TYPE"]) for r in rows}
    assert ("Coastal Flood", "Z") in kinds
    assert any(t == "C" for _, t in kinds)
    all_days, pluvial, coastal, _ = fs.storm_days(rows)
    assert date(2012, 10, 29) in coastal and date(2023, 9, 29) in pluvial
    assert pluvial | coastal == all_days
