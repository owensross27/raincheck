"""Flood-build ticket 02: the alert-station extractor.

Seam 2 (pure functions on fixtures, no network — the decode-census precedent). Fixtures
are cut from the real capture through the archiver's own parquet serialization:
  flood_alerts_water.parquet   410 captured subway_alerts rows (every row whose header or
                               description says WATER), archiver schema, zstd.
  flood_alerts_stations.json   the 496 ref/assets station rows the aliases are built from.
  flood_alerts_truth.json      the 50 text REVISIONS labeled blind by two independent
                               agents that never saw extractor output; the two labelings
                               agreed on every revision and all 71 pairs. Keyed by
                               (alert_id, sha1 of the text) so the oracle never depends
                               on the module's own ordering. complex_of is the hand
                               adjudication from truth station name to complex.
  flood_alerts_holdout.json    the 40-row frozen-rule holdout (Socrata era) with its own
                               independent labels — re-run here against the ported rules.
"""
import hashlib
import json
from pathlib import Path

import pyarrow.parquet as pq
import pytest

from raincheck import flood_alerts as fa

FIXTURES = Path(__file__).parent / "fixtures"
LEGACY_LITERALS = ("FLOOD", "WATER COND")  # ticket 01's vocabulary, dead in the live feed


@pytest.fixture(scope="module")
def aliases():
    stations = json.loads((FIXTURES / "flood_alerts_stations.json").read_text())
    by = fa.build_aliases(stations)
    return by, fa.build_pattern(by)


@pytest.fixture(scope="module")
def water_rows():
    return pq.read_table(FIXTURES / "flood_alerts_water.parquet").to_pylist()


@pytest.fixture(scope="module")
def truth():
    return json.loads((FIXTURES / "flood_alerts_truth.json").read_text())


def _text(row):
    return "\n".join(filter(None, (row.get("header"), row.get("description"))))


def _text_sha(header, description) -> str:
    return hashlib.sha1(f"{header or ''}\x00{description or ''}".encode()).hexdigest()[:12]


def _scanned(rows, aliases):
    """(alert_id, text_sha) -> the scan of that revision. Keyed the way the truth file is
    keyed, so a fold bug shows up as a KeyError rather than as a silent score."""
    by, pat = aliases
    return {(r["alert_id"], _text_sha(r["header"], r["description"])): fa.scan(r, by, pat)
            for r in fa.revisions(rows)}


def _predicted(scan) -> set:
    return {m["complex_ids"][0] for m in scan["matches"]
            if m["cause"] and not m["ambiguous"]}


# ---- the live-era vocabulary claims the ticket is built on ----

def test_legacy_vocabulary_is_dead_in_the_live_feed(water_rows):
    assert len(water_rows) == 410
    assert not [r for r in water_rows
                if any(lit in _text(r).upper() for lit in LEGACY_LITERALS)]


def test_every_live_water_alert_is_the_remove_water_family(water_rows):
    misses = {r["alert_id"] for r in water_rows if not fa.LIVE.search(fa.norm(_text(r)))}
    assert misses == set()
    assert len({r["alert_id"] for r in water_rows}) == 24


def test_informed_entity_is_no_shortcut(water_rows):
    assert [r for r in water_rows if r["stop_id"] is not None] == []


def test_the_station_is_in_the_description_not_only_the_header(water_rows, aliases):
    """The ticket's header AND description requirement: there are revisions whose flood
    station appears ONLY in the description, and scanning the header alone loses them."""
    by, pat = aliases
    recovered = 0
    for r in fa.revisions(water_rows):
        routes = " ".join(sorted(r["routes"]))
        head = {m["complex_ids"][0] for m in fa.extract(r["header"] or "", routes, by, pat)
                if m["cause"] and not m["ambiguous"]}
        both = _predicted(fa.scan(r, by, pat))
        assert head <= both
        recovered += len(both - head)
    assert recovered > 0, "fixture no longer exercises the description path"


# ---- frozen dedupe keys (this ticket owns them; 04 and 13 consume them) ----

def test_a_rename_in_the_registry_fails_loudly(aliases):
    """FORMER_NAMES exists because alert text uses the name of its era. If ref/assets
    renames the target, the historic alias must blow up, not quietly stop resolving."""
    by, _ = aliases
    assert by[next(iter(fa.FORMER_NAMES))], "the 149 St rename no longer resolves"
    with pytest.raises(KeyError):
        fa.build_aliases([{"asset_id": "sta:1", "name": "Somewhere Else",
                           "complex_id": "1", "daytime_routes": "N"}])


def test_both_apostrophes_normalize_the_same_way():
    """Two assets are spelled with an apostrophe. A curly one falling through to the
    non-alphanumeric strip would split PRINCES into PRINCE S and never match the alias."""
    assert fa.norm("Prince's Bay") == fa.norm("Prince’s Bay") == "PRINCES BAY"


def test_alert_id_grammar():
    assert fa.alert_key("lmm:alert:264026:29") == ("264026", 29)
    assert fa.alert_key("lmm:alert:264026:34") == ("264026", 34)  # same incident
    assert fa.alert_key("256811") is None
    assert fa.alert_key(None) is None


def test_incident_and_observation_keys_are_frozen():
    assert fa.INCIDENT_KEY == ("event_id",)
    assert fa.OBSERVATION_KEY == ("event_id", "complex_id")
    assert fa.REVISION_KEY == ("alert_id", "header", "description")


def test_alert_id_is_not_a_stable_text_key(water_rows, aliases, truth):
    """The MTA edits header/description in place under one alert_id, so alert_id does not
    identify a text. Measured harm, not a theory: a fold that keeps one arbitrary revision
    per id reports the WRONG active/cleared state for six revisions — and that flag is
    what ticket 13 renders on the chip."""
    by, pat = aliases
    revs = fa.revisions(water_rows)
    assert len({r["alert_id"] for r in revs}) == 24 and len(revs) == 50

    per_revision = {(r["alert_id"], _text_sha(r["header"], r["description"])): fa.scan(
        r, by, pat)["state"] for r in revs}
    naive = {}  # revisions() is ordered by first_seen, so [0] is the naive fold's pick
    for r in revs:
        naive.setdefault(r["alert_id"], fa.scan(r, by, pat)["state"])

    right = sum(per_revision[(t["alert_id"], t["text_sha"])] == t["state"]
                for t in truth["labels"])
    wrong = sum(naive[t["alert_id"]] != t["state"] for t in truth["labels"])
    assert right == 50            # the shipped fold agrees with truth on every revision
    assert wrong == 6             # the alert_id fold does not


def test_observation_state_comes_from_the_newest_revision(water_rows, aliases):
    """`state` is what ticket 13 draws on the chip, so pin it per observation. The
    WTC/Chambers and 79 St incidents all end cleared; 264048 is the one still active at
    the end of capture. Only 264063 disagrees with 264048 about Utica Av — each event
    carries its own newest revision, and reconciling across events is the spine's job."""
    by, pat = aliases
    got = {(o["event_id"], o["complex_id"]): o["state"]
           for o in fa.observations(water_rows, by, pat)}
    assert got == {
        ("264026", "312"): fa.CLEARED_STATE, ("264029", "603"): fa.CLEARED_STATE,
        ("264031", "624"): fa.CLEARED_STATE, ("264043", "624"): fa.CLEARED_STATE,
        ("264048", "181"): fa.ACTIVE,        ("264050", "624"): fa.CLEARED_STATE,
        ("264060", "624"): fa.CLEARED_STATE, ("264063", "181"): fa.CLEARED_STATE,
        ("264063", "624"): fa.CLEARED_STATE,
    }


def test_a_revision_naming_two_aliases_of_one_complex_counts_once(water_rows, aliases):
    """n_rows/n_revisions feed the panel and the spine, so they must count sightings, not
    regex matches: "Astoria-Ditmars Blvd" and "Ditmars Blvd" are one complex, one sighting."""
    by, pat = aliases
    rows = [{"alert_id": "lmm:alert:999:1", "route_id": "N",
             "header": "We are removing water from the tracks at Astoria-Ditmars Blvd.",
             "description": "Ditmars Blvd is closed because of flooding.",
             "fetched_at": 1_700_000_000 + i} for i in range(3)]
    obs = fa.observations(rows, by, pat)
    assert len(obs) == 1 and obs[0]["n_rows"] == 3 and obs[0]["n_revisions"] == 1

    real = fa.observations(water_rows, by, pat)
    assert sum(o["n_rows"] for o in real) <= len(water_rows) * len(real)
    assert {o["event_id"]: o["n_rows"] for o in real if o["event_id"] == "264026"} == \
        {"264026": 101}


def test_one_observation_row_per_event_and_complex(water_rows, aliases):
    by, pat = aliases
    obs = fa.observations(water_rows, by, pat)
    keys = [tuple(o[k] for k in fa.OBSERVATION_KEY) for o in obs]
    assert len(keys) == len(set(keys))
    # the WTC/Chambers night mints several event ids for one physical flood; merging them
    # is the spine's job (04), so complex 624 legitimately appears under several events
    assert len({o["complex_id"] for o in obs if o["event_id"] in {"264031", "264060"}}) == 1
    assert len(obs) == 9 and len({o["event_id"] for o in obs}) == 8


def test_active_and_cleared(water_rows, aliases, truth):
    scans = _scanned(water_rows, aliases)
    disagree = [r["alert_id"] for r in truth["labels"]
                if scans[(r["alert_id"], r["text_sha"])]["state"] != r["state"]]
    assert disagree == []
    # an alert naming a finished removal AND an ongoing one is still active
    assert fa.state_of(fa.norm(
        "We removed water from the tracks at Chambers St. "
        "We are working to remove water from the tracks at Utica Av.")) == fa.ACTIVE
    assert fa.state_of(fa.norm(
        "What Happened? We removed water from the tracks near Chambers St.")) == fa.CLEARED_STATE


# ---- the precision gate ----

def test_precision_gate_on_the_remove_water_family(water_rows, aliases, truth):
    cof = truth["complex_of"]
    scans = _scanned(water_rows, aliases)
    assert len(scans) == len(truth["labels"]) == 50
    tp = fp = fn = 0
    for row in truth["labels"]:
        t = {cof[n] for n in row["flood_stations"]}
        p = _predicted(scans[(row["alert_id"], row["text_sha"])])
        tp, fp, fn = tp + len(t & p), fp + len(p - t), fn + len(t - p)
    assert tp / (tp + fp) >= fa.MIN_PRECISION
    # measured 2026-08-23 over the full capture: zero false positives; all five recall
    # misses are the ambiguity drop, never a rule failure (see the next test)
    assert (tp, fp, fn) == (49, 0, 5)


def test_precision_gate_at_the_observation_grain(water_rows, aliases, truth):
    cof = truth["complex_of"]
    keys = {}
    for row in truth["labels"]:
        key = fa.alert_key(row["alert_id"])
        assert key is not None, row["alert_id"]
        keys[row["alert_id"]] = key[0]
    want = {(keys[r["alert_id"]], cof[n])
            for r in truth["labels"] for n in r["flood_stations"]}
    by, pat = aliases
    got = {(o["event_id"], o["complex_id"]) for o in fa.observations(water_rows, by, pat)}
    assert not got - want                       # precision 1.000: every prediction is truth
    assert want - got == {("264044", "312")}    # the one drop: 79 St under [4][5]


def test_observations_do_not_depend_on_row_order(water_rows, aliases):
    """Parquet parts arrive in whatever order the reader hands them over, and the state
    fold takes the newest revision — so a wrong tie-break would show as flapping state."""
    import random

    by, pat = aliases
    want = fa.observations(water_rows, by, pat)
    for seed in range(5):
        shuffled = water_rows[:]
        random.Random(seed).shuffle(shuffled)
        assert fa.observations(shuffled, by, pat) == want


def test_every_recall_miss_is_the_ambiguity_drop(water_rows, aliases, truth):
    """The drop rule is what buys the perfect precision: three stations are named
    Chambers St and two are named 79 St, and a [B][D] or [4][5] alert cannot say which.
    Each miss must be a cause-anchored match that failed to resolve, not a rule failure."""
    cof = truth["complex_of"]
    scans = _scanned(water_rows, aliases)
    misses = 0
    for row in truth["labels"]:
        scan = scans[(row["alert_id"], row["text_sha"])]
        for want in {cof[n] for n in row["flood_stations"]} - _predicted(scan):
            misses += 1
            assert [m for m in scan["matches"]
                    if m["cause"] and m["ambiguous"] and want in m["complex_ids"]], \
                f"{row['alert_id']} lost {want} to a rule failure, not to ambiguity"
    assert misses == 5


# ---- the archiver's parquet serialization changes nothing ----

def test_parquet_serialization_is_lossless_for_the_extractor(water_rows, aliases, tmp_path):
    """The gate is measured on rows that went through the archiver, so pin that the
    archiver's serialization is what the extractor sees: prose with newlines, curly
    apostrophes and [route] brackets survives another trip through the same writer."""
    import pyarrow as pa

    from raincheck.archiver import TYPES

    by, pat = aliases
    cols = list(water_rows[0])
    schema = pa.schema([(c, TYPES.get(c, pa.string())) for c in cols])
    out = tmp_path / "part-00.parquet"
    pq.write_table(pa.Table.from_pylist(water_rows, schema=schema), out, compression="zstd")
    again = pq.read_table(out).to_pylist()

    assert again == water_rows
    assert any("\n" in _text(r) for r in again) and any("’" in _text(r) or "'" in _text(r)
                                                        for r in again)
    assert fa.observations(again, by, pat) == fa.observations(water_rows, by, pat)


# ---- the frozen rules themselves ----

def test_frozen_rule_selfcheck(aliases):
    by, pat = aliases

    def causes(text, affected=""):
        return {n for m in fa.extract(text, affected, by, pat) if m["cause"]
                for n in m["names"]}

    assert "Queens Plaza" in causes(
        "[R] trains are running with delays due to a water condition at Queens Plaza.", "R")
    assert "238 St" in causes(
        "238 St on the 1 line is closed because of a flood at street-level.", "1")
    assert "149 St-Hostos" in causes(
        "flooding caused by overflowing street drains at 149 St - Grand Concourse.", "2|4|5")
    assert "Botanic Garden" in causes(
        "Franklin Av Shuttle suspended both directions because of flooding at Botanic Garden",
        "FS")
    assert not causes("Train service is extremely limited because of heavy rainfall "
                      "and flooding across the region")
    assert causes("There is no [D] service b/t 59 St & 205 St due to a water condition "
                  "at 163 St.", "D") == {"163 St-Amsterdam Av"}
    assert not causes("[SIR] trains are suspended between Pleasant Plains and Tottenville "
                      "because of flooding.", "SIR")
    got = causes("[4] and [5] train service has resumed following an earlier water condition "
                 "at 96 St and signal problems at 86 St.", "4|5")
    assert any("96 St" in n for n in got) and not any("86 St" in n for n in got), got
    assert "W 4 St-Wash Sq" in causes(
        "[F] via [E] Roosevelt Av to W 4 St, due to a water condition at W 4 St.", "F|M")
    assert "Queens Plaza" in causes(
        "We're addressing flooding that is causing a signal problem at Queens Plaza.", "E|M|R")
    got = causes("[A] delays some [A] terminate at 125 St & some terminate at 168 St "
                 "due to a water condition at 207 St.", "A")
    assert not any("168" in n for n in got) and any("207" in n for n in got), got
    assert "Times Sq-42 St" in causes(
        "We are working to clear water from the tracks after a water main break "
        "at Times Sq-42 St.", "1|2|3")
    got = causes("no [SIR] trains b/t Tottenville and Huguenot, due to flooding conditions "
                 "b/t Prince's Bay and Richmond Valley.", "SIR")
    assert any("Bay" in n for n in got) and any("Richmond Valley" in n for n in got) \
        and not any("Tottenville" in n for n in got), got
    assert any("179 St" in n for n in causes(
        "E F trains are running with delays after we addressed flooding in the facility "
        "that controls switches at 179 St.", "E|F"))
    # the live family, bridged both ways
    assert "Utica Av" in causes(
        "Queens-bound [A] trains are delayed while we remove water from the tracks "
        "at Utica Av.", "A|C")
    assert "149 St-Hostos" in causes(
        "Uptown [4] trains are running with delays after we removed water from the tracks "
        "near 149 St-Hostos.", "4")


def test_frozen_rule_holdout_reruns_green(aliases):
    """The 40-row holdout was labeled after the rules were frozen and was never retuned
    on. Scored the prototype's way: a predicted complex set is a TP when it intersects a
    truth set (ambiguity is a recall cost, never a precision credit)."""
    by, pat = aliases
    rows = json.loads((FIXTURES / "flood_alerts_holdout.json").read_text())

    def resolve(name, affected):
        n = fa.norm(name)
        m = pat.fullmatch(n) or pat.search(n)
        if not m or (m.group(0) != n and m.group(0) not in n):
            return frozenset()
        routes = fa.parse_routes(affected)
        cands = by.get(m.group(0), [])
        picked = [c for c in cands if routes & fa.parse_routes(c["daytime_routes"])] or cands
        return frozenset(c["complex_id"] for c in picked)

    tp = fp = fn = 0
    flag_agree = {"system_wide": 0, "footer_only": 0, "planned_work": 0}
    for row in rows:
        resolved, unresolved, want = [], [], []
        for name in row["flood_stations"]:
            cids = resolve(name, row["affected"])
            if not cids:
                unresolved.append(name)
                continue
            resolved.append(name)
            if cids not in want:  # two truth names for one station are one label
                want.append(cids)
        unresolved = [u for u in unresolved
                      if not any(fa.norm(r_) in fa.norm(u) for r_ in resolved
                                 if fa.norm(r_) != fa.norm(u))]
        pred = []
        for m in fa.extract(row["text"], row["affected"], by, pat):
            if m["cause"] and frozenset(m["complex_ids"]) not in pred:
                pred.append(frozenset(m["complex_ids"]))
        for p in pred:
            hit = next((t for t in want if t & p), None)
            if hit is None:
                fp += 1
            else:
                tp += 1
                want.remove(hit)
        fn += len(want) + len(unresolved)
        got = fa.flags(row["text"])
        for f in flag_agree:
            flag_agree[f] += got[f] == row[f]

    assert (tp, fp, fn) == (14, 0, 4)  # unchanged from the frozen-rule measurement
    assert tp / (tp + fp) >= fa.MIN_PRECISION
    assert flag_agree == {"system_wide": 40, "footer_only": 40, "planned_work": 40}
