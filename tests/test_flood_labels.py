"""Flood-build ticket 05: gold/flood_labels and the read-side negatives generator.

Seam 1 (DuckDB contract assertions over the written table) and seam 2 (pure functions on
fixture calendars). No network: the flood snapshots come from ticket 04's own fixture set
through test_flood._land, and ref/assets + ref/cells are cut from the real registry —
every complex and station, plus the entrances, bus stops and Cells the fixture
observations can actually reach.

Two rows in the assets fixture are deliberate, not cut: `ent:fixture-inside-95m` and
`ent:fixture-outside-140m` sit due SOUTH of 311 report 24283048 at 95 m and 140 m, which
is the only way to pin RADIUS_M from both sides. South, not north: they were planted
north until 2026-08-24, and a SECOND 311 report of the same event sits 59 m from where the
140 m row stood — so the "outside" row attached under a correct 100 m cut and the failure
read as a radius bug. An outside fixture only pins anything when it is outside the radius of EVERY
observation, not of the one it was measured against; due south the nearest observation to
it is 139.4 m, and to the inside row 95.0 m exactly. One Cell that fixture observations
fall in carries scored = false, so the cells_scored filter has something to bite on.
"""
import json
import shutil
from datetime import date
from pathlib import Path

import pyarrow.parquet as pq
import pytest

from raincheck import duck, flood_labels as fl, flood_obs as fo, flood_spine as fs
from test_flood import FIXTURE_P99, _land

FIXTURES = Path(__file__).parent / "fixtures"
ASOF = fo.ASOF
# the 149 St rename: an alert naming the station's FORMER name, on a day the fixture spine
# already holds, so the label must land on the complex the alias table resolves to
RENAMED_ALERT = {
    "alert_id": "fixture-149", "event_id": "990001", "update_number": "0",
    "date": "2023-09-29T18:30:00.000", "agency": "NYCT Subway", "affected": "2 | 4 | 5",
    "header": "Northbound 4 trains are running with delays.",
    "description": "What's Happening?\nWe are removing water from the tracks at "
                   "149 St - Grand Concourse.\n\nListen to announcements.",
}
RENAMED_COMPLEX = "603"  # 149 St-Hostos, per flood_alerts.FORMER_NAMES


@pytest.fixture(scope="module")
def label_root(spark, tmp_path_factory):
    root = tmp_path_factory.mktemp("labels")
    _land(root)
    # the richer registry this ticket needs, replacing ticket 04's stations-only cut
    shutil.copy(FIXTURES / "flood_labels_assets.parquet",
                root / "ref" / "assets" / "part-00000.parquet")
    cells = root / "ref" / "cells"
    cells.mkdir(parents=True)
    shutil.copy(FIXTURES / "flood_labels_cells.parquet", cells / "part-00000.parquet")
    snap = root / "archive" / "flood" / f"alerts_{fo.ALERTS_NEW}_{ASOF}.json"
    snap.write_text(json.dumps(json.loads(snap.read_text()) + [RENAMED_ALERT]))

    fo.build(root, spark, ASOF, expect=None)
    fs.build(root, ASOF, thresholds=FIXTURE_P99)
    fl.build(root, spark, ASOF)
    return root


@pytest.fixture(scope="module")
def con():
    return duck.connect()


@pytest.fixture(scope="module")
def labels(con, label_root):
    return duck.table(con, label_root / "gold" / "flood_labels")


@pytest.fixture(scope="module")
def universe(label_root):
    return (pq.read_table(label_root / "ref" / "assets").to_pylist(),
            pq.read_table(label_root / "silver" / "flood_events").to_pylist())


def one(rel, sql):
    return rel.query("t", sql).fetchall()


# ---- seam 2: the negative universe is a pure function ------------------------------

def _event(day, **cov):
    return {"event_id": day.isoformat(), "day_start": day, "day_end": day,
            **{f"cov_{s}": cov.get(s, True) for s in ("311", "alert", "floodnet")}}


def _asset(kind, asset_id="x", complex_id=None, feeds=None, scored=True):
    return {"asset_id": asset_id, "kind": kind, "cell": 1, "complex_id": complex_id,
            "feeds": feeds, "scored": scored}


def test_a_complex_is_only_dry_where_the_alert_feed_was_live():
    """A complex's positives come from alerts alone, so an event no alert feed covered
    cannot mint a dry complex — that would be a false negative, not an observation."""
    day = date(2013, 5, 1)
    assert fl.detectable("complex", _event(day, alert=True))
    assert not fl.detectable("complex", _event(day, alert=False))
    # 311 being live says nothing about a complex: it never labels one
    assert not fl.detectable("complex", _event(day, alert=False, **{"311": True}))


def test_a_point_unit_is_dry_where_either_311_or_floodnet_was_live():
    day = date(2015, 5, 1)
    for kind in ("entrance", "bus_stop", "cell"):
        assert fl.detectable(kind, _event(day, **{"311": True}, floodnet=False))
        assert fl.detectable(kind, _event(day, **{"311": False}, floodnet=True))
        assert not fl.detectable(kind, _event(day, **{"311": False}, floodnet=False))


def test_the_spines_own_coverage_flags_are_what_the_generator_reads(universe):
    """The calendars live in flood_spine and are already stamped per event; ticket 05 must
    not re-derive them (two copies of a calendar is one calendar and one bug)."""
    _, events = universe
    uncovered = [e for e in events if not e["cov_alert"]]
    assert uncovered, "the fixture spine must hold alert-uncovered events"
    for e in uncovered:
        assert not fl.detectable("complex", e)


def test_a_station_that_had_not_opened_yet_is_never_a_negative():
    opened, name = fl.OPENED["475"]  # 96 St on the Second Av line, 2017-01-01
    sas = _asset("complex", "stn:475", complex_id="475")
    assert fl.anachronistic(sas, _event(opened.replace(year=2012)))
    assert not fl.anachronistic(sas, _event(opened))
    # its entrances inherit the rule; an unrelated complex does not
    assert fl.anachronistic(_asset("entrance", "ent:x", complex_id="475"), _event(date(2012, 10, 29)))
    assert not fl.anachronistic(_asset("complex", "stn:1", complex_id="1"), _event(date(2012, 10, 29)))


def test_a_station_that_opened_mid_event_stays_out():
    """Judged on the event's FIRST day: half an event is not coverage."""
    opened, _ = fl.OPENED["328"]  # WTC Cortlandt
    e = {**_event(opened), "day_start": opened.replace(day=opened.day - 1)}
    assert fl.anachronistic(_asset("complex", "stn:328", complex_id="328"), e)


def test_bus_stop_pairs_start_in_2020_and_later_where_a_redesign_moved_them():
    plain = _asset("bus_stop", "bus:1", feeds=["brooklyn"])
    assert fl.anachronistic(plain, _event(date(2019, 12, 31)))
    assert not fl.anachronistic(plain, _event(fl.BUS_STOPS_FROM))
    bronx = _asset("bus_stop", "bus:2", feeds=["bronx", "busco"])
    assert fl.anachronistic(bronx, _event(date(2021, 7, 1)))
    assert not fl.anachronistic(bronx, _event(fl.BUS_REDESIGN["bronx"]))
    queens = _asset("bus_stop", "bus:3", feeds=["queens"])
    assert fl.anachronistic(queens, _event(date(2024, 12, 31)))
    assert not fl.anachronistic(queens, _event(fl.BUS_REDESIGN["queens"]))
    # a stop in BOTH moved boroughs takes the later floor, never the earlier one
    both = _asset("bus_stop", "bus:4", feeds=["bronx", "queens"])
    assert fl.anachronistic(both, _event(date(2024, 12, 31)))


def test_a_cell_is_never_anachronistic_but_an_unscored_one_is_out_of_the_universe():
    assert not fl.anachronistic(_asset("cell", "cell:1"), _event(date(2010, 3, 13)))
    assert fl.in_universe(_asset("cell", "cell:1", scored=True))
    assert not fl.in_universe(_asset("cell", "cell:1", scored=False))
    assert not fl.in_universe(_asset("station", "sta:1"))  # a Carrier is never scored


def test_negatives_are_generated_never_stored_and_exclude_the_positives():
    assets = [_asset("cell", "cell:1"), _asset("cell", "cell:2")]
    events = [_event(date(2021, 6, 1)), _event(date(2021, 7, 1))]
    got = {(n["asset_id"], n["event_id"]) for n in
           fl.negatives(assets, events, [("cell:1", "2021-06-01")])}
    assert got == {("cell:1", "2021-07-01"), ("cell:2", "2021-06-01"), ("cell:2", "2021-07-01")}


def test_the_census_accounts_for_every_pair_in_the_grid():
    """grid = uncovered + anachronistic + candidates, and candidates = negatives +
    in-universe positives. A rule that drops rows it does not count is a silent cap."""
    assets = [_asset("cell", "cell:1"), _asset("complex", "stn:475", complex_id="475"),
              _asset("bus_stop", "bus:1", feeds=["queens"])]
    events = [_event(date(2013, 5, 1), alert=False), _event(date(2026, 5, 1))]
    positives = [("cell:1", "2026-05-01")]
    c = fl.census(assets, events, positives)
    assert c["grid"] == c["dropped_uncovered"] + c["dropped_anachronistic"] + c["candidates"]
    assert c["negatives"] == sum(1 for _ in fl.negatives(assets, events, positives))
    assert c["positives_outside"] == 0


# ---- seam 1: the written table -----------------------------------------------------

def test_the_grain_is_one_row_per_asset_event(labels):
    assert one(labels, "SELECT count(*) FROM (SELECT asset_id, event_id FROM t "
                       "GROUP BY 1, 2 HAVING count(*) > 1)") == [(0,)]
    assert one(labels, "SELECT count(*) FROM t WHERE asset_id IS NULL OR event_id IS NULL "
                       "OR cell IS NULL OR label_version IS NULL") == [(0,)]


def test_no_negative_row_is_ever_stored(labels):
    """The file has no `flooded` column to be false in, and every kind it carries is a
    label kind. There is nothing here that could be read as a negative."""
    cols = {c.lower() for c in labels.columns}
    assert not cols & {"flooded", "label", "negative", "y"}
    assert set(one(labels, "SELECT DISTINCT kind FROM t")) <= {(k,) for k in fl.LABEL_KINDS}
    assert one(labels, "SELECT count(*) FROM t WHERE source_mix = 0") == [(0,)]


def test_every_source_bit_is_reachable_and_the_mask_stays_in_range(labels):
    """bit_or over a real source set: no row may carry a bit outside the frozen map, and
    a row touched by two sources must carry both."""
    top = sum(fl.SOURCE_BIT.values())
    assert one(labels, f"SELECT count(*) FROM t WHERE source_mix < 1 OR source_mix > {top}") == [(0,)]
    mixed = one(labels, "SELECT count(*) FROM t WHERE bit_count(source_mix) > 1")[0][0]
    assert mixed > 0, "the fixture must exercise a multi-source label"


def test_the_support_vocabulary_is_frozen_and_sorted(labels):
    supports = one(labels, "SELECT DISTINCT unnest(label_support) FROM t")
    assert {s for (s,) in supports} <= set(fl.SUPPORT)
    assert one(labels, "SELECT count(*) FROM t WHERE label_support != "
                       "list_sort(label_support) OR len(label_support) = 0") == [(0,)]


def test_radius_attachment_is_geodesic_and_cuts_at_one_hundred_metres(labels):
    """The fixture's two planted entrances sit 95 m and 140 m from 311 report 24283048,
    and no other observation is nearer to either than 95.0 m and 139.4 m."""
    got = {a for (a,) in one(labels, "SELECT DISTINCT asset_id FROM t "
                                     "WHERE asset_id LIKE 'ent:fixture-%'")}
    assert got == {"ent:fixture-inside-95m"}


def test_cells_attach_by_h3_equality_and_only_inside_cells_scored(label_root, labels, con):
    """A Cell that observations fall in but which is not in cells_scored mints no label."""
    assets = duck.table(con, label_root / "ref" / "assets")
    unscored = {a for (a,) in one(assets, "SELECT asset_id FROM t WHERE kind = 'cell' AND NOT scored")}
    assert unscored, "the fixture must carry an unscored Cell"
    labelled = {a for (a,) in one(labels, "SELECT DISTINCT asset_id FROM t WHERE kind = 'cell'")}
    assert not (labelled & unscored)
    # H3 equality, not proximity: a Cell label's own Cell is the asset's Cell
    assert one(labels, "SELECT count(*) FROM t WHERE kind = 'cell' "
                       "AND asset_id != printf('cell:%x', cell)") == [(0,)]


def test_an_alert_lands_one_row_on_the_complex_and_never_on_its_entrances(labels, label_root, con):
    station = one(labels, "SELECT count(*), count(DISTINCT kind) FROM t "
                          "WHERE list_contains(label_support, 'station')")
    assert station[0][1] == 1
    assert one(labels, "SELECT count(*) FROM t WHERE list_contains(label_support, 'station') "
                       "AND kind != 'complex'") == [(0,)]
    # complexes are alert-only: no other rule may reach one, or ticket 08's independent
    # complex-grain validation set stops being independent
    assert one(labels, "SELECT count(*) FROM t WHERE kind = 'complex' "
                       f"AND source_mix != {fl.SOURCE_BIT['mta_alert']}") == [(0,)]


def test_the_149_st_rename_resolves_to_the_right_complex(labels):
    """An alert naming '149 St - Grand Concourse' must label the complex the station is
    filed under today, not nothing."""
    assert one(labels, "SELECT count(*) FROM t WHERE asset_id = "
                       f"'stn:{RENAMED_COMPLEX}' AND kind = 'complex'")[0][0] >= 1


def test_the_sandy_footprint_attaches_by_containment_not_by_radius(labels):
    poly = one(labels, "SELECT DISTINCT kind FROM t WHERE list_contains(label_support, 'polygon')")
    assert {k for (k,) in poly} <= {"entrance", "bus_stop", "cell"}
    assert one(labels, "SELECT count(*) FROM t WHERE list_contains(label_support, 'polygon') "
                       f"AND source_mix & {fl.SOURCE_BIT['sandy']} = 0") == [(0,)]


def test_depth_rides_only_where_a_source_measures_it(labels):
    """FloodNet is the only fixture source with a depth; a label with no FloodNet bit
    cannot carry one."""
    assert one(labels, "SELECT count(*) FROM t WHERE depth_mm IS NOT NULL "
                       f"AND source_mix & {fl.SOURCE_BIT['floodnet']} = 0") == [(0,)]
    assert one(labels, "SELECT count(*) FROM t WHERE depth_mm <= 0") == [(0,)]


def test_every_label_sits_inside_its_own_events_window(label_root, con):
    """The event join is the window, never the observation: a label whose observation fell
    outside the window would mean the spine had been bypassed.

    What this actually pins is the PRECONDITION for that — no observation lands in two
    event windows, so `oe` assigns each observation to exactly one event and a label can
    only carry the window it was joined on. The name is broader than the assertion;
    recorded on the ticket rather than quietly widened.
    """
    obs = duck.table(con, label_root / "silver" / "flood_obs")
    events = duck.table(con, label_root / "silver" / "flood_events")
    # projected views, never .arrow(): rel.arrow() is a LAZY RecordBatchReader on this
    # same connection, and a join over two registered ones deadlocks at 0% CPU - the
    # scan pulls a batch whose production needs the connection context the join holds.
    # That, not Sandy's 2.3M-vertex polygon, was the ">400 s hang". The projection
    # still keeps the geometry out of the join.
    obs.select("source", "source_id", "ts_utc").create_view("o")
    events.select("window_start_utc", "window_end_utc").create_view("e")
    assert con.sql("SELECT count(*) FROM o JOIN e ON o.ts_utc >= e.window_start_utc "
                   "AND o.ts_utc < e.window_end_utc GROUP BY o.source, o.source_id "
                   "HAVING count(*) > 1").fetchall() == []


def test_label_version_chains_the_spine_and_the_registry(label_root, labels):
    (spine,) = {v for (v,) in one(duck.table(duck.connect(), label_root / "silver" / "flood_events"),
                                  "SELECT DISTINCT spine_version FROM t")}
    stamp = fl.label_version(label_root, spine, ASOF)
    assert {v for (v,) in one(labels, "SELECT DISTINCT label_version FROM t")} == {stamp}
    # a different spine, a different label set: ticket 18's universes cannot collide
    assert fl.label_version(label_root, "another-spine", ASOF) != stamp
    assert fl.label_version(label_root, spine, date(2026, 1, 1)) != stamp


def test_the_file_names_its_estimand(label_root):
    meta = pq.read_table(label_root / "gold" / "flood_labels").schema.metadata
    assert meta[b"estimand"] == fl.ESTIMAND.encode() == b"flooded_reported"
    assert b"REPORTED" in meta[b"estimand_note"]
    assert meta[b"negatives"] == b"generated at read; none stored"


def test_the_read_side_generator_runs_off_the_written_tables(label_root, labels):
    stored = {(a, e) for a, e in one(labels, "SELECT asset_id, event_id FROM t")}
    got = list(fl.read_negatives(label_root))
    assert got, "the fixture universe must yield negatives"
    assert not {(n["asset_id"], n["event_id"]) for n in got} & stored
