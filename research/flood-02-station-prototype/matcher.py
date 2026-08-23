#!/usr/bin/env python3
"""Station-name extractor for MTA subway flood alerts (ticket 02 prototype).

Reads stations.json, alerts_old.json, alerts_new.json (same directory).
Writes extractions.json (row grain) and events_stations.json (event grain,
cause-anchored matches only).
Run: python3 matcher.py   (self-check asserts run first, then full pass)
"""
import collections
import json
import pathlib
import re

DIR = pathlib.Path(__file__).parent

WORD_CANON = {
    "AVENUE": "AV", "AVENUES": "AVS", "AVE": "AV", "STREET": "ST",
    "STREETS": "STS", "ROAD": "RD", "BOULEVARD": "BLVD", "PARKWAY": "PKWY",
    "SQUARE": "SQ", "CENTER": "CTR", "CENTRE": "CTR", "HEIGHTS": "HTS",
    "FORT": "FT", "MOUNT": "MT",
}
ORDINAL = re.compile(r"\b(\d+)(?:ST|ND|RD|TH)\b")


def norm(s: str) -> str:
    s = s.upper().replace("'", "")
    s = re.sub(r"[/–—-]", " ", s)
    s = re.sub(r"[^A-Z0-9 ]", " ", s)
    s = ORDINAL.sub(r"\1", s)
    s = " ".join(WORD_CANON.get(w, w) for w in s.split())
    return re.sub(r"\bB T\b", "BETWEEN", s)


SYSTEM_WIDE = re.compile(
    r"ACROSS (THE REGION|NEW YORK CITY|THE CITY)|CITYWIDE|SYSTEM ?WIDE"
    r"|MULTIPLE STATIONS"
    r"|FLOOD\w*[^.]{0,50}\bIN (MANHATTAN|BROOKLYN|QUEENS|THE BRONX|STATEN ISLAND)"
    r"|\bIN (MANHATTAN|BROOKLYN|QUEENS|THE BRONX|STATEN ISLAND)[^.]{0,50}FLOOD"
)
PLANNED = re.compile(r"FLOOD (PROTECTION|MITIGATION|BARRIER|RESILIENCY|PREVENTION)")
FLOOD_KW = re.compile(r"FLOOD|WATER COND")
ANCHOR = re.compile(r"FLOOD[A-Z]*|WATER CONDITIONS?|WATER MAIN BREAK")

# Cause-clause bridges (all matched against normalized text)
BRIDGE_FWD = re.compile(  # anchor ... AT/NEAR station
    r" (?:S )?(?:(?:ON|IN|INSIDE|CAUSED BY|OF|FROM|THAT IS CAUSING|CAUSING)"
    r"(?:(?!\bAND\b|\bAT\b)[A-Z0-9 ]){0,45} )?(?:AT|NEAR) (?:THE )?"
)
BRIDGE_BACK = re.compile(  # station [is closed because of / while we correct] anchor
    # a bare "due to" must NOT fire: range endpoints sit right before it
    # ("no service b/t A & B due to a water condition at C")
    r" (?:ON THE [A-Z0-9]{1,3} LINE )?(?:IS |ARE )?(?:CLOSED|SKIPPED|SUSPENDED)"
    r" (?:BECAUSE OF|DUE TO|AFTER) (?:A |AN |THE )?(?:HEAVY |STREET LEVEL )?"
    r"|(?: (?:IS |ARE )?)?WHILE WE (?:CORRECT|ADDRESS|INVESTIGATE) (?:A |AN |THE )?"
)
BRIDGE_AFTER_AT = re.compile(r" (?:(?!\bAND\b)[A-Z0-9 ]){0,40} ?")  # pre ends AT/NEAR
BETWEEN = re.compile(r"(?:S| CONDITIONS)? BETWEEN (?:THE )?")

# Former names: alert text uses the name of its era; the station list is
# current-only. Keyed by normalized former name -> current stop_name.
FORMER_NAMES = {
    "149 ST GRAND CONCOURSE": "149 St-Hostos",
}


def load_stations():
    rows = json.load(open(DIR / "stations.json"))
    by_alias = collections.defaultdict(list)

    def add(alias: str, station: dict) -> None:
        if station["station_id"] not in {r["station_id"] for r in by_alias[alias]}:
            by_alias[alias].append(station)

    for r in rows:
        full = norm(r["stop_name"])
        add(full, r)
        # hyphen-segment aliases: "W 4 St-Wash Sq" is written "W 4 St" in alerts
        for seg in r["stop_name"].split("-"):
            n = norm(seg)
            if n and n != full and len(n) >= 4 and (any(c.isdigit() for c in n) or " " in n):
                add(n, r)
    for former, current in FORMER_NAMES.items():
        for r in rows:
            if r["stop_name"] == current:
                add(former, r)
        assert by_alias[former], f"FORMER_NAMES target missing: {current}"
    return by_alias


def parse_routes(affected):
    if not affected:
        return set()
    return {p.strip().upper() for p in affected.split("|") if p.strip()}


def build_pattern(by_alias):
    aliases = sorted(by_alias, key=len, reverse=True)
    return re.compile(r"\b(?:" + "|".join(re.escape(a) for a in aliases) + r")\b")


def is_cause(t: str, m: re.Match, anchors: list) -> bool:
    for a in anchors:
        if a.end() <= m.start() <= a.end() + 70:
            gap = t[a.end():m.start()]
            if BRIDGE_FWD.fullmatch(gap) or BETWEEN.fullmatch(gap):
                return True
        if m.end() <= a.start() <= m.end() + 70:
            bridge = t[m.end():a.start()]
            pre = t[:m.start()].rstrip()
            if BRIDGE_BACK.fullmatch(bridge):
                return True
            pre_ok = (pre.endswith((" NEAR", " BYPASSING", " SKIPPING"))
                      or (pre.endswith(" AT")
                          and not re.search(r"TERMINAT\w* AT$", pre)))
            if pre_ok and BRIDGE_AFTER_AT.fullmatch(bridge):
                return True
    return False


def extract(text: str, affected, by_alias, alias_pat):
    t = norm(text)
    routes = parse_routes(affected)
    anchors = list(ANCHOR.finditer(t))
    taken, matches = [], []
    for m in sorted(alias_pat.finditer(t), key=lambda m: -(m.end() - m.start())):
        if any(m.start() < e and m.end() > s for s, e in taken):
            continue
        taken.append((m.start(), m.end()))
        alias = m.group(0)
        cands = by_alias[alias]
        picked = [c for c in cands if routes & parse_routes(c.get("daytime_routes", ""))] or cands
        cause = is_cause(t, m, anchors)
        # "flooding between A and B": second endpoint is joined to the first by " AND "
        matches.append({
            "alias": alias, "span": [m.start(), m.end()], "cause": cause,
            "complex_ids": sorted({c["complex_id"] for c in picked}),
            "names": sorted({c["stop_name"] for c in picked}),
            "ambiguous": len({c["complex_id"] for c in picked}) > 1,
        })
    # second BETWEEN endpoint: A cause-matched via BETWEEN, then " AND " to B
    by_start = sorted(matches, key=lambda x: x["span"][0])
    for i, a in enumerate(by_start[:-1]):
        b = by_start[i + 1]
        if a["cause"] and not b["cause"] and t[a["span"][1]:b["span"][0]] in (" AND ", " "):
            for anc in anchors:
                if anc.end() <= a["span"][0] and BETWEEN.fullmatch(t[anc.end():a["span"][0]]):
                    b["cause"] = True
    return matches


def run():
    by_alias = load_stations()
    pat = build_pattern(by_alias)
    out = []
    for era, fname, idcols in (
        ("old", "alerts_old.json", ("status_id",)),
        ("new", "alerts_new.json", ("event_id", "update_number", "alert_id")),
    ):
        for r in json.load(open(DIR / fname)):
            text = " ".join(filter(None, [r.get("header"), r.get("description")]))
            tu = text.upper()
            hits = [s for s in re.split(r"(?<=[.!?])\s+", tu) if FLOOD_KW.search(s)]
            out.append({
                "era": era,
                **{k: r.get(k) for k in idcols},
                "date": r["date"],
                "affected": r.get("affected"),
                "text": text,
                "norm_text": norm(text),
                "flags": {
                    "system_wide": bool(SYSTEM_WIDE.search(tu)),
                    "planned_work": bool(PLANNED.search(tu)),
                    "footer_only": bool(hits) and all(
                        s.lstrip().startswith("REMINDER") for s in hits),
                },
                "matches": extract(text, r.get("affected"), by_alias, pat),
            })
    json.dump(out, open(DIR / "extractions.json", "w"), indent=1)

    events = collections.defaultdict(lambda: {"days": set(), "complexes": set(),
                                              "names": set(), "system_wide": False,
                                              "rows": 0})
    for r in out:
        key = ("old", r.get("status_id")) if r["era"] == "old" else ("new", r.get("event_id"))
        e = events[key]
        e["rows"] += 1
        if r["flags"]["planned_work"] or r["flags"]["footer_only"]:
            continue
        e["days"].add(r["date"][:10])
        e["system_wide"] |= r["flags"]["system_wide"]
        for m in r["matches"]:
            if m["cause"]:  # cause-anchored only — mentions are not flood locations
                e["complexes"].update(m["complex_ids"])
                e["names"].update(m["names"])
    dump = [{"era": k[0], "id": k[1], "first_day": min(v["days"]) if v["days"] else None,
             "complex_ids": sorted(v["complexes"]), "names": sorted(v["names"]),
             "system_wide": v["system_wide"], "n_rows": v["rows"]}
            for k, v in sorted(events.items(), key=lambda kv: str(kv[0]))]
    json.dump(dump, open(DIR / "events_stations.json", "w"), indent=1)
    return out, dump


def self_check():
    by_alias = load_stations()
    pat = build_pattern(by_alias)

    def causes(text, affected=""):
        return {n for m in extract(text, affected, by_alias, pat) if m["cause"]
                for n in m["names"]}

    assert "Queens Plaza" in causes(
        "[R] trains are running with delays due to a water condition at Queens Plaza.", "R")
    assert "238 St" in causes(
        "238 St on the 1 line is closed because of a flood at street-level.", "1")
    assert "149 St-Hostos" in causes(
        "flooding caused by overflowing street drains at 149 St - Grand Concourse.", "2|4|5")
    assert "Botanic Garden" in causes(
        "Franklin Av Shuttle suspended both directions because of flooding at Botanic Garden", "FS")
    assert not causes(
        "Train service is extremely limited because of heavy rainfall and flooding across the region")
    # cause-anchoring negatives: mentions must not fire
    assert causes(
        "There is no [D] service b/t 59 St & 205 St due to a water condition at 163 St.", "D"
    ) == {"163 St-Amsterdam Av"}
    assert not causes(
        "[SIR] trains are suspended between Pleasant Plains and Tottenville because of flooding.", "SIR")
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
        "We are working to clear water from the tracks after a water main break at Times Sq-42 St.", "1|2|3")
    got = causes("no [SIR] trains b/t Tottenville and Huguenot, due to flooding conditions "
                 "b/t Prince's Bay and Richmond Valley.", "SIR")
    assert any("Princes Bay" in n or "Prince" in n for n in got) and any("Richmond Valley" in n for n in got) \
        and not any("Tottenville" in n for n in got), got
    assert any("179 St" in n for n in causes(
        "E F trains are running with delays after we addressed flooding in the facility "
        "that controls switches at 179 St.", "E|F"))
    print("self-check: 14/14 ok")


if __name__ == "__main__":
    self_check()
    rows, events = run()
    n_cause = sum(1 for r in rows if any(m["cause"] for m in r["matches"]))
    print(f"{len(rows)} rows -> {n_cause} with >=1 cause station; events: {len(events)}")
