"""Flood-build ticket 15, testing seam 3: the flood tick, its two gate-side payloads and
the release checklist.

The rendering half is pure: `payloads()` takes a `cycle()` return, a universe and a truth
read and gives back four documents, so every claim rule below is a data assertion over
fixtures with no network and no data root. The reading half (`universe`, `wet_series`,
`cell_hours`, `parts`) needs the real tables and its tests skip off the main root, which
is the normal shape in a worktree.

The Window fixture is flood 11's — REAL AORC output for 2021-09-01 (Ida) plus its second,
wet-antecedent event — so "the panel renders what the detector produced" is asserted
against the shipped numbers rather than against a hand-shaped stub.
"""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from raincheck import contract, flood_detect as fd, flood_exposure as fe
from raincheck import flood_panel as fp, flood_truth as ft, publish, release_check
from raincheck.paths import data_root

FIX = Path(__file__).parent / "fixtures" / "flood_detect_ida.json"
NOW = datetime(2021, 9, 2, 3, 0, tzinfo=timezone.utc)
MAIN = Path("/Users/ross/raincheck/data")


def _dt(s: str) -> datetime:
    return datetime.fromisoformat(s)


@pytest.fixture(scope="module")
def ida() -> dict:
    f = json.loads(FIX.read_text())
    f["ws"], f["we"] = _dt(f["window_start_utc"]), _dt(f["window_end_utc"])
    f["peak"] = _dt(f["peak_hour_utc"])
    f["wet"] = {_dt(k): v for k, v in f["wet_counts"].items()}
    f["hours"] = [{"cell": c["cell"], "hour_end_utc": _dt(h), "mm_1h": mm}
                  for c in f["cells"] for h, mm in c["hourly"].items()]
    f["mx"] = {c["cell"]: c["matrix"] for c in f["cells"]}
    return f


@pytest.fixture(scope="module")
def art() -> dict:
    return fe.coefficients()


@pytest.fixture(scope="module")
def det() -> dict:
    return fd.constants()


@pytest.fixture(scope="module")
def units(ida) -> list[dict]:
    us = [dict(p) for p in ida["points"]]
    cell = next(iter(ida["mx"]))
    for c, m in ida["mx"].items():
        us.append({"asset_id": f"cell:{c:x}", "kind": "cell", "cell": c} | {
            k: m[k] for k in ("share_deep", "share_nuisance", "share_not_analyzed",
                              "density_311_3y")})
    us.append({"asset_id": ida["complex_asset_id"], "kind": "complex",
               "complex_id": ida["complex_id"], "cell": cell})
    return us


@pytest.fixture(scope="module")
def uni(ida, units, art) -> dict:
    """A universe over the fixture's Units: a static exposure row for each, and the
    artifact's own score_version as the stamp the table carried."""
    static = {}
    for u in units:
        if u["kind"] == "entrance":
            continue
        static[u["asset_id"]] = {
            "asset_id": u["asset_id"], "kind": u["kind"], "score_index": 0.5,
            "surge_margin_ft": None, "flags": [], "score_version": art["score_version"]}
    return {"units": units, "static": static,
            "where": {u["asset_id"]: {"name": "a name", "lon": -73.9, "lat": 40.7}
                      for u in units},
            "table_score_version": art["score_version"]}


def truth_read(sensors=(), chips=()) -> dict:
    return {"floodnet": {"source": "floodnet", "status": "ok", "citation": "c",
                         "caveats": ["a"], "rule": "r", "window_min": 60,
                         "asof": NOW.isoformat(), "detected": sum(1 for s in sensors
                                                                  if s["display"]),
                         "read": {"newest": NOW.isoformat()}, "sensors": list(sensors)},
            "mta": {"source": "mta_alerts", "status": "ok", "vocabulary": "v", "hours": 6,
                    "asof": NOW.isoformat(), "active": 1, "rows": 3, "chips": list(chips)}}


def sensor(**kw) -> dict:
    base = {"deployment_id": "d1", "name": "n", "status": "good", "state": "dry",
            "label": None, "depth_mm": 1.0, "rise_mm": 0.0, "run": 0, "age_min": 1.0,
            "fresh": True, "gate": None, "display": False, "lon": -73.9, "lat": 40.7,
            "cell": None}
    return base | kw


def chip(**kw) -> dict:
    base = {"event_id": "e1", "state": "active", "age_min": 5.0, "first_seen": 1,
            "last_seen": 2, "alert_ids": ["a1"],
            "stations": [{"complex_id": "1", "name": "s", "state": "active",
                          "lon": -73.98, "lat": 40.75}]}
    return base | kw


def render(ida, uni, det, art, *, now=NOW, state=None, temp_c=22.0, table=..., **kw):
    read = fd.cycle(state, now, ida["hours"], uni["units"], art, det, temp_c=temp_c,
                    table_score_version=(uni["table_score_version"] if table is ...
                                         else table),
                    wet_by_hour=ida["wet"])
    return read, fp.payloads(read, uni, kw.pop("truth", None) or truth_read(),
                             kw.pop("coastal", None), kw.pop("winter", None),
                             det, art, now)


# ---- the two files, the two metas, one cycle ---------------------------------------

def test_the_writer_emits_two_families_split_by_lineage(ida, uni, det, art):
    """frontend 01 D3, Ross's decision: the MTA terms gate would otherwise withhold the
    FloodNet tier - which carries no MTA content at all - because it shared a meta file
    with bus data. The split is by LINEAGE, so it has to be two FAMILIES: `gated` is a
    property of a family, and one family cannot be on two sides of a gate."""
    _, docs = render(ida, uni, det, art)
    assert set(docs) == set(fp.FILES[fp.UNGATED] + fp.FILES[fp.GATED])
    assert docs["flood.json"]["lineage"] == "ungated"
    assert docs["flood-mta.json"]["lineage"] == "mta-alerts"
    assert publish.FAMILIES[fp.UNGATED].gated is False
    assert publish.FAMILIES[fp.GATED].gated is True


def test_the_filenames_are_the_ones_the_page_already_fetches():
    """frontend 05 froze these because a chassis cannot read a URL that does not exist;
    the page's LAYERS table names them today. Landing different ones is a page edit."""
    page = (Path(publish.__file__).parents[2] / "web" / "layers.js").read_text()
    for name in ("flood.json", "flood-mta.json"):
        assert f'"files/{name}"' in page, f"web/layers.js does not fetch files/{name}"


def test_one_cycle_id_across_the_whole_set(ida, uni, det, art):
    """Four files, two families, one tick. A reader that finds two different cycle_ids is
    looking at a torn set and can say so."""
    _, docs = render(ida, uni, det, art)
    assert len({d["cycle_id"] for d in docs.values()}) == 1
    assert len({d["detector_version"] for d in docs.values()}) == 1


def test_the_meta_goes_last_in_each_family():
    """cloud 09's ordering rule, which is a correctness contract and not style: a
    publisher that dies mid-family must leave an OLD meta over a new payload (a consumer
    re-reads and finds it), never a fresh meta over a payload that is not there."""
    for fam in (fp.UNGATED, fp.GATED):
        assert publish.FAMILIES[fam].files == fp.FILES[fam]
        assert publish.FAMILIES[fam].files[-1].endswith("-meta.json")
        assert not publish.FAMILIES[fam].files[0].endswith("-meta.json")


def test_the_ungated_side_carries_nothing_mta_derived(ida, uni, det, art):
    """The whole point of the split. An alert id or a complex id on the open side would
    publish MTA-derived data through the gate that exists to hold it."""
    _, docs = render(ida, uni, det, art, truth=truth_read(chips=[chip()]))
    open_side = json.dumps({k: docs[k] for k in fp.FILES[fp.UNGATED]}, default=str).lower()
    for word in ("mta", "alert_id", "complex_id", "subwaydata"):
        assert word not in open_side, f"{word!r} reached the ungated payloads"
    assert docs["flood-mta.json"]["mta"]["chips"], "the gated side still carries them"


# ---- what the panel may say ---------------------------------------------------------

def test_the_frozen_honesty_string_is_rendered_verbatim_on_both_sides(ida, uni, det, art):
    """notify 01 froze it on 2026-08-23 and notify 09 renders the same words, so a panel
    and a message cannot contradict each other. Not re-worded, not summarised."""
    _, docs = render(ida, uni, det, art)
    for name in ("flood.json", "flood-mta.json"):
        assert docs[name]["strings"]["operating_truth"] == fp.OPERATING_TRUTH
    assert fp.OPERATING_TRUTH.startswith("raincheck ranks where a flood REPORT is likely")
    assert fp.OPERATING_TRUTH.endswith(
        "means nothing was flagged, not that nothing flooded.")


def test_the_retired_storm_page_claim_has_zero_hits():
    """It is retired because a notifier falsifies it, and a ticket that lists it as a
    fixed string puts it straight back (TRAPS). The checklist owns the grep; this is the
    suite's copy of the same gate."""
    hits = release_check._grep(release_check.RETIRED)
    assert hits == [], f"the retired claim is back in {hits}"


def test_every_string_comes_from_the_artifact_and_none_is_retyped(ida, uni, det, art):
    """`display.*` is deliberately outside `detector_version` so rewording a label cannot
    roll a live Window - which only holds while the panel READS those labels."""
    _, docs = render(ida, uni, det, art)
    s = docs["flood.json"]["strings"]
    for key in ("tier_labels", "tiers", "cutpoint_basis", "window_interval",
                "window_states", "precip_states", "winter_label", "winter_unknown_label",
                "no_complex_skill_claim", "within_cell", "cutpoints_confirmed_by",
                "forcing_stamp"):
        assert s[key] == det["display"][key], key
    assert s["panel"] == art["gate"]["panel_strings"]
    assert s["gate_branch"] == art["gate"]["branch"]


def test_the_human_facing_value_is_the_rank_never_an_eta(ida, uni, det, art):
    """A score is the LINEAR PREDICTOR and is negative for nearly every Unit (bus_stop
    -7.39..-3.91): printing one reads as a broken number, and it would be the calibration
    claim the honesty strings exist to prevent. Never sigmoid it either."""
    read, docs = render(ida, uni, det, art)
    assert any(u["eta"] < 0 for u in read["units"]), "the fixture must carry real etas"
    blob = json.dumps(docs, default=str)
    assert '"eta"' not in blob and '"probability"' not in blob
    for u in docs["flood.json"]["units"]:
        assert 0.0 <= u["rank"] <= 1.0


def test_the_tiers_say_provisional_while_the_artifact_says_so(ida, uni, det, art):
    """flood 12 measured the cost and RECOMMENDED rank-only; the verdict is Ross's. It is
    read at RENDER time, so recording it reaches the panel without a redeploy."""
    _, docs = render(ida, uni, det, art)
    assert docs["flood.json"]["provisional"] is bool(det["cutpoints"]["provisional"])
    confirmed = json.loads(json.dumps(det))
    confirmed["cutpoints"]["provisional"] = False
    _, after = render(ida, uni, confirmed, art)
    assert after["flood.json"]["provisional"] is False


def test_the_two_disclaimers_ride_with_the_rows_they_belong_to(ida, uni, det, art):
    """A complex score is an aggregate of doorway scores (the independent complex-grain
    set caught 1 of 118), and live ordering inside a Cell is purely static."""
    _, docs = render(ida, uni, det, art)
    s = docs["flood.json"]["strings"]
    assert "1 of 118" in s["no_complex_skill_claim"]
    assert "purely static" in s["within_cell"]
    assert docs["flood-mta.json"]["strings"]["no_complex_skill_claim"] == \
        s["no_complex_skill_claim"], "a complex row on the gated side needs it too"


# ---- states are data, never absence ---------------------------------------------------

def test_the_four_window_states_render_as_themselves(ida, uni, det, art):
    """OK / HOLES / INSUFFICIENT_DATA / WINDOW_CAPPED. A holed Window is still a Window and
    its anchor stands; INSUFFICIENT_DATA means there is no Window at all."""
    _, ok = render(ida, uni, det, art)
    assert ok["flood.json"]["window"]["state"] == fd.OK
    assert ok["flood.json"]["window"]["anchor"]
    read = fd.cycle(None, NOW, [], uni["units"], art, det, wet_by_hour={})
    docs = fp.payloads(read, uni, truth_read(), None, None, det, art, NOW)
    assert docs["flood.json"]["window"]["state"] == fd.INSUFFICIENT_DATA
    assert "anchor" not in docs["flood.json"]["window"]
    assert docs["flood.json"]["units"] == []


def test_a_refused_model_tier_renders_the_refusal_and_no_last_good_number(ida, uni, det, art):
    """`fd.skew` compares against the score_version of the TABLE THAT WAS READ. When they
    are different models the tier is DROPPED - no ranks, no tiers, no flagged Units - and
    the reason is rendered. Serving the last good number is the failure this prevents."""
    _, good = render(ida, uni, det, art)
    assert good["flood.json"]["model_tier"] == "ok"
    assert any(c.get("rank") is not None for c in good["flood.json"]["cells"].values())
    _, bad = render(ida, uni, det, art, table="a-different-model")
    assert bad["flood.json"]["skew"]["model_tier"] == "refused"
    assert bad["flood.json"]["skew"]["reason"]
    assert bad["flood.json"]["model_tier"] == "dropped"
    assert bad["flood.json"]["units"] == []
    assert all("rank" not in c and "tier" not in c
               for c in bad["flood.json"]["cells"].values())
    # ...and the STATIC view survives, because it is not the model tier
    assert all("score_index" in c for c in bad["flood.json"]["cells"].values())


def test_an_absent_table_stamp_refuses_rather_than_assuming_a_match(ida, uni, det, art):
    """"I could not tell" is not "they match"."""
    _, docs = render(ida, uni, det, art, table=None)
    assert docs["flood.json"]["skew"]["model_tier"] == "refused"


def test_the_dim_state_carries_the_rain_ended_hours_ago_number(ida, uni, det, art):
    _, docs = render(ida, uni, det, art)
    dim = docs["flood.json"]["dim"]
    assert set(dim) == {"dimmed", "dry_hours"}
    assert isinstance(dim["dimmed"], bool)


def test_the_winter_gate_suppresses_and_says_why(ida, uni, det, art):
    _, warm = render(ida, uni, det, art, temp_c=22.0)
    _, cold = render(ida, uni, det, art, temp_c=0.0)
    assert warm["flood.json"]["winter"]["suppressed"] is False
    assert cold["flood.json"]["winter"]["suppressed"] is True
    assert cold["flood.json"]["winter"]["label"] == det["display"]["winter_label"]
    assert all(u["tier"] == fd.NONE for u in cold["flood.json"]["cells"].values()
               if "tier" in u)


# ---- staleness, dated at the reader --------------------------------------------------

def test_every_source_is_dated_at_the_reader_against_its_own_budget(ida, uni, det, art):
    """The frozen-age trap, closed: `meta.json` once carried an age the WRITER computed,
    so a dead exporter served the same small number forever. Every row here is the
    reader's clock against the stamp the source itself carried."""
    fresh = NOW - timedelta(minutes=2)
    _, docs = render(ida, uni, det, art,
                     truth={"floodnet": truth_read()["floodnet"] | {
                         "read": {"newest": fresh.isoformat()}},
                            "mta": truth_read()["mta"]},
                     coastal={"chips": [{"obs_t": fresh.isoformat()}]},
                     winter={"status": "ok", "t": fresh.isoformat()})
    st = docs["flood.json"]["staleness"]
    assert {r["state"] for r in st.values()} <= set(det["display"]["precip_states"])
    assert st["floodnet"]["state"] == fd.FRESH and st["coops"]["state"] == fd.FRESH
    assert st["nws_knyc_obs"]["state"] == fd.FRESH
    assert all(r["budget_s"] for r in st.values())


def test_a_stamp_past_the_published_tolerance_reads_down_never_fresh(det):
    ahead = det["staleness_budgets"]["clock_ahead_min"]
    future = NOW + timedelta(minutes=ahead + 10)
    assert fp._source(future, NOW, 600, ahead=ahead)["state"] == fd.DOWN
    # ...and INSIDE the tolerance it is fresh, or 386 live FloodNet sensors that stamp two
    # minutes ahead by design would read DOWN forever - the tier inventing an outage
    assert fp._source(NOW + timedelta(minutes=1), NOW, 600, ahead=ahead)["state"] == fd.FRESH


def test_a_failed_read_is_down_and_never_silently_fresh():
    assert fp._source(None, NOW, 600)["state"] == fd.DOWN
    assert fp._source(NOW, NOW, 600, ok=False)["state"] == fd.DOWN


def test_coops_freshness_is_the_observation_stamp_not_the_fetch_time():
    """`coastal.asof` is when the loop fetched, which is always now - reading it would
    paint a dead gauge FRESH forever. The chips carry the real observation stamps."""
    old = (NOW - timedelta(hours=3)).isoformat()
    coastal = {"asof": NOW.isoformat(), "chips": [{"obs_t": old}, {"obs_t": None}]}
    assert fp._coops_newest(coastal) == fp._ts(old)
    assert fp._source(fp._coops_newest(coastal), NOW, fp.BUDGETS_S["coops"])["state"] == \
        fd.STALE


def test_the_budgets_are_derived_from_the_modules_that_fetch(det):
    """Frontend 02 counted nine sources on the running map with three carrying a frozen
    budget; these are the five this ticket owed. A mirrored constant drifts, so each is
    read from the module that owns it and cross-checked against the artifact."""
    b = det["staleness_budgets"]
    assert fp.BUDGETS_S == {
        "precip_fresh": b["precip_fresh_min"] * 60, "precip_stale": b["precip_stale_min"] * 60,
        "floodnet": b["floodnet_min"] * 60, "coops": b["coops_min"] * 60,
        "nws_alerts": b["nws_alerts_min"] * 60, "nws_knyc_obs": b["nws_knyc_obs_min"] * 60}
    assert fp.BUDGETS_S["floodnet"] == ft.MAX_AGE_MIN * 60 == 600
    assert fp.BUDGETS_S["nws_knyc_obs"] == 7200, "SETTLED by flood 11: KNYC reports hourly"
    assert fp.BUDGETS_S["nws_alerts"] == 900, "the spec's 15 min is the ALERTS budget"


def test_the_budgets_ship_on_both_metas(ida, uni, det, art):
    """The page renders a per-source freshness row and gets its numbers from here; until a
    source carries a budget it can only show a bare AGE and judge nothing."""
    _, docs = render(ida, uni, det, art)
    for name in ("flood-meta.json", "flood-mta-meta.json"):
        assert docs[name]["budgets_s"] == fp.BUDGETS_S


# ---- the payload shapes the page and later tickets bind to ---------------------------

def test_cells_are_keyed_by_hex_and_hold_one_extensible_dict_each(ida, uni, det, art):
    """An H3 Cell id is an int64 past 2^53 and JSON cannot carry one, so the key is the
    same hex string `cells.geojson` already keys on. One dict per Cell so flood-build 20
    can add `design_storm` in wave 8 without a rewrite."""
    _, docs = render(ida, uni, det, art)
    cells = docs["flood.json"]["cells"]
    assert cells and all(isinstance(k, str) and int(k, 16) for k in cells)
    assert all(isinstance(v, dict) for v in cells.values())
    assert all(f"cell:{k}" in uni["static"] for k in cells)


def test_absent_is_never_null_anywhere_in_a_payload(ida, uni, det, art):
    """The writer discipline the whole read surface shares: an unpublishable value is an
    ABSENT KEY, because MapLibre's ["has", p] is true on a null and `interpolate` then
    errors on it. Empty is not absent - [] and 0 still publish."""
    _, docs = render(ida, uni, det, art)

    def walk(o, path=""):
        if isinstance(o, dict):
            for k, v in o.items():
                assert v is not None, f"null at {path}.{k}"
                walk(v, f"{path}.{k}")
        elif isinstance(o, list):
            for i, v in enumerate(o):
                walk(v, f"{path}[{i}]")

    for name in ("flood.json", "flood-meta.json", "flood-mta.json", "flood-mta-meta.json"):
        walk(docs[name], name)
    # empty is NOT absent - "no sensor is reporting" and "no chip is open" are answers
    assert docs["flood.json"]["floodnet"]["geojson"]["features"] == []
    assert docs["flood-mta.json"]["mta"]["chips"] == []
    assert docs["flood-mta-meta.json"]["counts"]["chips"] == 0


def test_a_foreign_tier_with_its_own_nulls_is_pruned_too(ida, uni, det, art):
    """Three members here are other modules' shapes and every one carries explicit Nones
    by ITS convention: a CO-OPS chip's `reason` is None when nothing is wrong and its
    `observed_ft` is None when the gauge is OUT. Packing this document key by key would
    have missed them - the fixture path had `coastal` absent entirely, and it did."""
    coastal = {"source": "noaa_coops", "asof": NOW.isoformat(), "stage": "nws_minor",
               "chips": [{"station": "8518750", "state": "OUTAGE", "observed_ft": None,
                          "obs_t": None, "reason": "no observation in the last hour",
                          "next_high": None, "anomaly": {"anomaly_ft": None, "n": 0}}],
               "recolor": {"gauges": ["8518750"], "units": None}}
    _, docs = render(ida, uni, det, art, coastal=coastal)
    blob = json.dumps(docs["flood.json"])
    assert ": null" not in blob and "null," not in blob
    chip = docs["flood.json"]["coastal"]["chips"][0]
    assert chip["state"] == "OUTAGE" and "observed_ft" not in chip
    assert chip["reason"], "the reason for the outage is DATA and must survive"


def test_the_static_recolor_set_does_not_ride_in_a_thirty_second_payload(ida, uni, det, art):
    """MEASURED: 1,072 rows / 212 KB during a real APPROACHING tide, in a `no-cache`
    payload republished every two minutes - the largest member of the file, static, and
    already carried per Cell as `surge_margin_ft` from gold/flood_exposure. The COUNTS
    ship, so a page can still say how many Units a hot gauge covers."""
    coastal = {"source": "noaa_coops", "asof": NOW.isoformat(), "stage": "nws_minor",
               "chips": [], "recolor": {"gauges": ["8518750"], "n_units": 1072,
                                        "n_no_margin": 77, "n_below_minor": 5,
                                        "units": [{"asset_id": "bus:1"}] * 1072}}
    _, docs = render(ida, uni, det, art, coastal=coastal)
    r = docs["flood.json"]["coastal"]["recolor"]
    assert "units" not in r and r["n_units"] == 1072 and r["gauges"] == ["8518750"]
    assert "bus:1" not in json.dumps(docs["flood.json"])


def test_every_floodnet_feature_carries_a_boolean_display(ida, uni, det, art):
    """frontend 05: the map paints a water-now sensor as a filled disc and a dry or stale
    one as a HOLLOW RING, and the MapLibre expression reads exactly ["get", "display"]. A
    missing key paints every sensor as a ring."""
    sensors = [sensor(deployment_id="wet", state="water", display=True),
               sensor(deployment_id="dry"), sensor(deployment_id="nowhere", lon=None)]
    _, docs = render(ida, uni, det, art, truth=truth_read(sensors=sensors))
    feats = docs["flood.json"]["floodnet"]["geojson"]["features"]
    assert len(feats) == 2, "a sensor with no point cannot be a map feature"
    assert all(isinstance(f["properties"]["display"], bool) for f in feats)
    assert {f["properties"]["deployment_id"]: f["properties"]["display"]
            for f in feats} == {"wet": True, "dry": False}


def test_the_mta_chip_can_be_placed_without_a_second_lookup(ida, uni, det, art):
    """frontend 02 built the layer and could not draw a dot: `chips()` named a complex and
    stopped there. Same defect as notify 05's manifest, and the price of closing it is 445
    complexes with lon/lat = 30,087 B."""
    _, docs = render(ida, uni, det, art, truth=truth_read(chips=[chip()]))
    feats = docs["flood-mta.json"]["mta"]["geojson"]["features"]
    assert len(feats) == 1
    assert feats[0]["geometry"]["coordinates"] == [-73.98, 40.75]
    assert feats[0]["properties"]["display"] is True
    st = docs["flood-mta.json"]["mta"]["chips"][0]["stations"][0]
    assert st["lon"] and st["lat"]


def test_point_units_publish_only_at_elevated_or_above(ida, uni, det, art):
    """Dormant weather shows the static Cell view, not a list of 13,370 bus stops. Flagged
    means flagged."""
    _, docs = render(ida, uni, det, art)
    units = docs["flood.json"]["units"]
    assert all(u["tier"] in (fd.ELEVATED, fd.HIGH) for u in units)
    assert all(u["kind"] != "cell" for u in units), "Cells ride in `cells`, keyed by hex"


def test_the_static_exposure_view_is_always_available(ida, uni, det, art):
    """`score_index` is the within-kind empirical CDF, bounded (0, 1], one row per Unit,
    no nulls - the dormant read. It does not depend on there being a Window."""
    read = fd.cycle(None, NOW, [], uni["units"], art, det, wet_by_hour={})
    docs = fp.payloads(read, uni, truth_read(), None, None, det, art, NOW)
    cells = docs["flood.json"]["cells"]
    assert cells and all(0.0 < c["score_index"] <= 1.0 for c in cells.values())


def test_the_new_families_are_additive_under_the_contract_integer():
    """ADDING a family is additive under `PROMISE ⊆ surface`; removing or renaming a key
    is what demands the bump. A digest over the surface would have bumped here."""
    assert not (contract.PROMISE[contract.CONTRACT] - contract.surface())
    assert contract.CONTRACT == 1, "adding two families must not bump the integer"
    assert {fp.UNGATED, fp.GATED} <= {f for f, _, _ in contract.surface()}


# ---- the tick's cadence and failure policy --------------------------------------------

def test_the_tick_skips_unless_the_forcing_advanced_or_the_throttle_expired(det):
    """The model tier can only change when the precip stamp advances - hourly - so on a
    30 s loop nearly every tick has nothing to score. The truth tiers can change in
    between, which is what the artifact's FloodNet throttle is for."""
    t = det["throttles"]["floodnet_s"]
    prev = {"stamp": "valid_ts=2026-08-25T20", "at": NOW}
    assert fp.due(None, "x", NOW, t) is True, "the first cycle always runs"
    assert fp.due(prev, prev["stamp"], NOW + timedelta(seconds=30), t) is False
    assert fp.due(prev, "valid_ts=2026-08-25T21", NOW + timedelta(seconds=30), t) is True
    assert fp.due(prev, prev["stamp"], NOW + timedelta(seconds=t), t) is True


def test_an_outage_is_a_field_on_state_and_never_a_stopped_loop(tmp_path, monkeypatch):
    """Cloud 05's failure policy, copied: the panel degrades, the loop does not stop."""
    monkeypatch.setattr(fp, "universe", lambda *a, **k: 1 / 0)
    state = fp.tick(None, tmp_path, tmp_path / "web", None, NOW)
    assert "ZeroDivisionError" in state["error"]
    assert state["skipped"] is False and "error" in fp.line(state)


def test_a_gated_family_is_a_designed_state_logged_once(tmp_path, capsys):
    """cloud 09 rc 3. The MTA terms are unverified, so the gated pair is written locally
    and not published - a standing condition, and a line every 30 s would bury the tick
    that genuinely broke."""
    (tmp_path / "flood.json").write_text("{}")
    (tmp_path / "flood-meta.json").write_text("{}")
    (tmp_path / "flood-mta.json").write_text("{}")
    (tmp_path / "flood-mta-meta.json").write_text("{}")
    prev = None
    for _ in range(3):
        got = fp.ship(tmp_path, prev)
        prev = got
    assert got[fp.GATED] == "gated"
    assert capsys.readouterr().out.count("publish gated") == 1


def test_the_ungated_family_is_not_gated_by_the_mta_terms(tmp_path):
    """The whole point of the split, asserted through the real publisher: with the terms
    unverified the open side must still plan."""
    assert publish.LIVE_TERMS_VERIFIED is None
    for name in fp.FILES[fp.UNGATED]:
        (tmp_path / name).write_text("{}")
    items = publish.plan(fp.UNGATED, tmp_path)
    assert [i.key for i in items] == ["files/flood.json", "files/flood-meta.json"]
    with pytest.raises(publish.GateClosed):
        publish.plan(fp.GATED, tmp_path)


def test_half_a_flood_family_is_refused(tmp_path):
    (tmp_path / "flood.json").write_text("{}")
    with pytest.raises(publish.Refused):
        publish.plan(fp.UNGATED, tmp_path)


def test_the_log_holds_the_full_vector_only_when_the_model_recomputed(tmp_path, ida, uni,
                                                                      det, art):
    """Spec: the full unit-state vector when the model tier recomputes (~24/day), the
    flagged subset per cycle. 15,000 rows every 30 s is 3 GB/day, not 3 MB."""
    read, _ = render(ida, uni, det, art)
    fp.log(tmp_path, NOW, read, full=True, truth=None)
    fp.log(tmp_path, NOW, read, full=False, truth=None)
    rows = [json.loads(l) for l in _log_lines(tmp_path, NOW)]
    assert rows[0]["kind"] == "full" and rows[1]["kind"] == "flagged"
    assert len(rows[0]["units"]) > len(rows[1]["units"])
    assert all(u["tier"] != fd.NONE for u in rows[1]["units"])
    assert all("eta" not in u for r in rows for u in r["units"])


def _log_lines(root, now):
    import gzip
    with gzip.open(root / fp.LOG_DIR / f"{now:%Y-%m-%d}{fp.LOG_SUFFIX}", "rt") as fh:
        return fh.read().splitlines()


def test_the_log_is_gzipped_because_the_raw_vector_blows_the_byte_budget(tmp_path, ida,
                                                                        uni, det, art):
    """MEASURED on the real universe: one full vector is 15,106 rows = 1,651,324 B raw, so
    the ~24 recomputes a day the spec describes are 39.6 MB/day and 1.2 GB across the
    30-day prune, against a budget of "~3 MB/day, <= ~100 MB". Gzipped it is 3.2 MB/day.
    Appending gzip members keeps the file appendable and readable in one pass."""
    read, _ = render(ida, uni, det, art)
    for _ in range(3):
        fp.log(tmp_path, NOW, read, full=True, truth=None)
    path = tmp_path / fp.LOG_DIR / f"{NOW:%Y-%m-%d}{fp.LOG_SUFFIX}"
    assert path.is_file() and path.read_bytes()[:2] == b"\x1f\x8b"
    assert len(_log_lines(tmp_path, NOW)) == 3, "appended members read back as one stream"
    assert path.stat().st_size < len("".join(_log_lines(tmp_path, NOW)))


def test_the_log_prunes_on_the_first_write_of_a_day(tmp_path, ida, uni, det, art):
    read, _ = render(ida, uni, det, art)
    d = tmp_path / fp.LOG_DIR
    d.mkdir(parents=True)
    old = d / f"{(NOW - timedelta(days=fp.LOG_KEEP_DAYS + 1)).date()}{fp.LOG_SUFFIX}"
    keep = d / f"{(NOW - timedelta(days=2)).date()}{fp.LOG_SUFFIX}"
    old.write_text("{}\n")
    keep.write_text("{}\n")
    fp.log(tmp_path, NOW, read, full=False, truth=None)
    assert not old.exists() and keep.exists()


# ---- the release checklist ------------------------------------------------------------

def test_the_release_checklist_runs_and_every_row_passes():
    """flood 09 owed it, 10 and 11 both deferred it, and this is where it lands. It
    re-evaluates the headline gate from the published tables with `flood_fits.gate()`
    rather than reading a verdict anyone typed."""
    checks = release_check.rows()
    failed = [r for ok, r, _ in checks if not ok]
    assert not failed, f"release-check refused: {failed}"
    assert len(checks) >= 12


def test_the_checklist_asserts_the_branch_it_never_re_types():
    """A stored gate that disagrees with a re-evaluation of its own tables is a corrupted
    artifact, and the only way to know is to run the function."""
    from raincheck import flood_fits
    art = fe.coefficients()
    fits = json.loads((Path(publish.__file__).parents[2] / "research" /
                       "flood-09-fits.json").read_text())
    assert flood_fits.gate(fits["summary"])["branch"] == art["gate"]["branch"] == "MODEL"
    src = (Path(release_check.__file__)).read_text()
    assert "flood_fits.gate(" in src
    assert '"MODEL"' not in src, "the verdict must be read, never typed into the checklist"


def test_the_checklist_fails_when_the_panel_stops_saying_the_frozen_string(monkeypatch):
    """A checklist that passes whatever the code does is a checklist nobody needs."""
    monkeypatch.setattr(fp, "OPERATING_TRUTH", "something else entirely")
    failed = [r for ok, r, _ in release_check.rows() if not ok]
    assert any("operating-truth" in r for r in failed)


# ---- the real tables (skipped off the main root) ---------------------------------------

real = pytest.mark.skipif(data_root() != MAIN,
                          reason="needs the main data root (RAINCHECK_ARCHIVE_ROOT)")


@pytest.fixture(scope="module")
def con():
    from raincheck import duck
    return duck.connect()


@real
def test_the_universe_is_the_scored_registry_and_the_tables_stamp(con):
    uni = fp.universe(con, data_root())
    kinds = {}
    for u in uni["units"]:
        kinds[u["kind"]] = kinds.get(u["kind"], 0) + 1
    assert kinds == {"bus_stop": 13310, "entrance": 2120, "cell": 1351, "complex": 445}
    assert len(uni["static"]) == fe.EXPECT["units"] == 15166
    assert uni["table_score_version"] == fe.coefficients()["score_version"], (
        "the stamp must come from the TABLE that was read, not from a constant")


@real
def test_the_newest_part_per_hour_is_exactly_the_row_level_dedupe(con):
    """`precip_live` appends a full 4,113-Cell grid per fetch, so the newest part in an
    hour directory already holds the newest fetched_at for every Cell. This is what lets
    the read pick 92 files instead of scanning 657 and sorting 378,000 rows."""
    from raincheck import duck
    root = data_root()
    since = datetime.now(timezone.utc) - timedelta(days=fp.READ_DAYS)
    got = {(r["cell"], r["hour_end_utc"], r["mm_1h"])
           for r in fp.cell_hours(con, root, since, datetime.now(timezone.utc))}
    ref = set(con.execute(
        "SELECT cell, strptime(valid_ts, '%Y-%m-%dT%H')::TIMESTAMPTZ, mm_1h FROM "
        f"read_parquet('{root}/live/precip_cell/**/*.parquet', hive_partitioning = true, "
        "hive_types_autocast = false) QUALIFY row_number() OVER "
        "(PARTITION BY cell, valid_ts ORDER BY fetched_at DESC) = 1").fetchall())
    assert got == ref and got


def test_the_selected_part_is_the_newest_by_name_not_merely_a_part(tmp_path):
    """A SEMANTIC pin, and it has to be, because no value comparison can make this claim.

    MEASURED on the real table 2026-08-25: of 92 hour directories, 55 hold more than one
    part and in ZERO of them does the oldest part disagree with the newest on (cell,
    mm_1h) - MRMS RadarOnly for a settled :00 hour is final, and `precip_live` re-fetches
    the same grid every tick. So `got[0]` and `got[-1]` return identical rows today and a
    round-trip test against the window-function form passes either way (it did: that
    mutant survived). The rule is `ORDER BY fetched_at DESC`, so the assertion is that the
    SELECTION is the maximum - which stays true the day the live product revises an hour,
    which is the case `fd.revisions` exists for and which an offline replay can never
    exercise (TRAPS).
    """
    d = tmp_path / "live" / "precip_cell" / "valid_ts=2026-08-25T20"
    d.mkdir(parents=True)
    names = ["part-20260825T200500.parquet", "part-20260825T203000.parquet",
             "part-20260825T205448.parquet"]
    for n in names:
        (d / n).write_bytes(b"")
    got = fp.parts(tmp_path, datetime(2026, 8, 25, tzinfo=timezone.utc))
    assert [Path(p).name for p in got] == [max(names)] == [names[-1]]


def test_parts_takes_one_file_per_hour_from_since_forward(tmp_path):
    base = tmp_path / "live" / "precip_cell"
    for hour in ("2026-08-24T22", "2026-08-25T01", "2026-08-25T02"):
        d = base / f"valid_ts={hour}"
        d.mkdir(parents=True)
        (d / "part-a.parquet").write_bytes(b"")
        (d / "part-b.parquet").write_bytes(b"")
    got = fp.parts(tmp_path, datetime(2026, 8, 25, 1, tzinfo=timezone.utc))
    assert len(got) == 2 and all(p.endswith("part-b.parquet") for p in got)
    assert "2026-08-24T22" not in " ".join(got)


def test_the_tick_hands_cycle_the_whole_grid_series_and_not_the_narrowed_rows(tmp_path,
                                                                              monkeypatch):
    """"Citywide" is a property of the GRID, and the per-Cell read is deliberately narrowed
    to the hours the anchor names - so if `cycle()` were left to recompute the series from
    those rows it would be counting a TIME subset. The walk looks back up to six days and
    the dry-run counter further still; both would then see hours that are simply absent
    and read INSUFFICIENT_DATA, or worse, pick a newer anchor whose wet evening the
    narrowed read cannot see. Ticket 12's box carries the same MUST for the same reason."""
    seen = {}
    grid = {datetime(2026, 8, 25, h, tzinfo=timezone.utc): h for h in range(1, 6)}
    narrow = [{"cell": 1, "hour_end_utc": datetime(2026, 8, 25, 5, tzinfo=timezone.utc),
               "mm_1h": 0.0}]
    monkeypatch.setattr(fp, "universe", lambda *a: {"units": [], "static": {},
                                                    "where": {}, "table_score_version": None})
    monkeypatch.setattr(fp, "wet_series", lambda *a, **k: grid)
    monkeypatch.setattr(fp, "cell_hours", lambda *a, **k: narrow)
    monkeypatch.setattr(fp, "cell_index", lambda root: False)
    monkeypatch.setattr(fp.ft, "truth", lambda *a, **k: truth_read())

    def spy(state, now, rows, units, art, det, **kw):
        seen.update(kw, rows=rows)
        return fd.cycle(state, now, rows, units, art, det, **kw)

    monkeypatch.setattr(fp.fd, "cycle", spy)
    fp.tick(None, tmp_path, tmp_path / "web", None, NOW,
            ship_=lambda o, p: {fp.UNGATED: "x", fp.GATED: "x"})
    assert seen["wet_by_hour"] == grid, "the whole-grid series must be passed explicitly"
    assert fd.wet_counts(seen["rows"]) != grid, (
        "this test asserts nothing unless the narrowed rows really do disagree")


@real
def test_the_citywide_series_counts_the_whole_grid(con):
    """"Citywide" is a property of the GRID. Deriving it from the narrowed per-Cell read
    would silently redefine it as "these Cells" - the trap flood 12's box names."""
    root, now = data_root(), datetime.now(timezone.utc)
    wet = fp.wet_series(con, root, now)
    rows = fp.cell_hours(con, root, now - timedelta(days=fp.READ_DAYS), now)
    assert wet == fd.wet_counts(rows)
    assert len({r["cell"] for r in rows}) == 4113


@real
def test_the_narrowed_read_reproduces_the_full_cycle_exactly(con):
    """The two-pass read is a memory contract, and a memory contract that changes an
    answer is a feature bug. Same cycle, byte for byte."""
    root, now = data_root(), datetime.now(timezone.utc)
    uni = fp.universe(con, root)
    art, det = fe.coefficients(), fd.constants()
    wet = fp.wet_series(con, root, now)
    kw = dict(temp_c=22.0, wet_by_hour=wet,
              table_score_version=uni["table_score_version"])
    full = fd.cycle(None, now, fp.cell_hours(con, root, now - timedelta(days=fp.READ_DAYS),
                                             now), uni["units"], art, det, **kw)
    narrow = fd.cycle(None, now, fp.cell_hours(con, root,
                                               fp.since_of(fd.walk(now, wet), now), now),
                      uni["units"], art, det, **kw)
    assert _norm(full) == _norm(narrow)


def _norm(o):
    """`cycle()`'s features are keyed by datetime, which json cannot encode as a key."""
    if isinstance(o, dict):
        return {str(k): _norm(v) for k, v in sorted(o.items(), key=lambda kv: str(kv[0]))}
    if isinstance(o, (list, tuple)):
        return [_norm(v) for v in o]
    return str(o) if isinstance(o, datetime) else o


@real
def test_a_real_tick_writes_four_files_and_publishes_only_the_open_side(con, tmp_path):
    out = tmp_path / "web"
    state = fp.tick(con, data_root(), out, None, datetime.now(timezone.utc),
                    ship_=lambda o, p: {fp.UNGATED: "test", fp.GATED: "test"})
    assert state.get("error") is None, state.get("error")
    for name in fp.FILES[fp.UNGATED] + fp.FILES[fp.GATED]:
        assert (out / name).is_file()
    doc = json.loads((out / "flood.json").read_text())
    assert doc["cells"] and doc["staleness"]["precip"]["state"] in det_states()
    assert state["counts"]["cells"] == len(doc["cells"])


def det_states():
    return set(fd.constants()["display"]["precip_states"])
