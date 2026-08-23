"""Alert-station extractor (flood-build ticket 02 / spec "Labels and the event spine").

MTA alert prose -> station-named flood observations. Cause-anchored matching against the
ref/assets station names: a station counts only when a bridge ties it to a water anchor,
never because the text merely mentions it (mention-grain precision measured 0.195).

Two anchor eras, both live in ANCHOR:
  LEGACY_ANCHOR  flood* / water condition(s) / water main break — the Socrata history.
  LIVE_ANCHOR    "remove|removing|removed water from the tracks" — the only phrasing the
                 live LMM feed uses. Zero rows of the 1,929,727 captured subway_alerts
                 rows carry the legacy literals (measured 2026-08-23); the panel's alert
                 tier (ticket 13) filters on LIVE_ANCHOR alone.
Informed-entity is no shortcut: stop_id was NULL in 410/410 captured water rows, so the
station has to come out of the prose.

Grain: one observation per (event_id, complex_id) — OBSERVATION_KEY. Entrances inherit
for display only; cross-event merging of one physical flood is the spine's job (04).
A match that does not resolve to exactly ONE complex after route filtering mints no
observation: recall costs labels, ambiguity contaminates them.

Captured rows fold twice before any of that, and both folds are load-bearing — see
revisions(). The second one is the trap: alert_id does not identify a text.

Run: python -m raincheck.flood_alerts            (measure over <root>/archive/subway_alerts)
"""
import argparse
import collections
import json
import re
from pathlib import Path

from raincheck import duck
from raincheck.paths import data_root

# ---- frozen normalization (ported verbatim from the measured prototype) ----
WORD_CANON = {
    "AVENUE": "AV", "AVENUES": "AVS", "AVE": "AV", "STREET": "ST",
    "STREETS": "STS", "ROAD": "RD", "BOULEVARD": "BLVD", "PARKWAY": "PKWY",
    "SQUARE": "SQ", "CENTER": "CTR", "CENTRE": "CTR", "HEIGHTS": "HTS",
    "FORT": "FT", "MOUNT": "MT",
}
ORDINAL = re.compile(r"\b(\d+)(?:ST|ND|RD|TH)\b")

# ---- frozen vocabulary ----
# LIVE_ANCHOR is the measured live family, verbatim over the full capture: the verb is
# REMOVE / REMOVING / REMOVED and the object always "water from the tracks", bridged
# AT/NEAR <station>. "working to remove ..." and "while we remove ..." are prefixes of
# the same phrase, so the anchor needs no variant for them. ES is the one inflection
# never observed, carried defensively — dropping a label costs more than matching it.
LIVE_ANCHOR = r"REMOV(?:E|ES|ING|ED) WATER FROM THE TRACKS"
LEGACY_ANCHOR = r"FLOOD[A-Z]*|WATER CONDITIONS?|WATER MAIN BREAK"
ANCHOR = re.compile(f"{LIVE_ANCHOR}|{LEGACY_ANCHOR}")
LIVE = re.compile(LIVE_ANCHOR)
# row prefilter: cheap, upper-cased, before normalization
FLOOD_KW = re.compile(r"FLOOD|WATER COND|WATER FROM THE TRACKS")

# ---- frozen cause bridges (prototype rules, unchanged: the holdout is scored on these) ----
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

# ---- frozen row flags ----
SYSTEM_WIDE = re.compile(
    r"ACROSS (THE REGION|NEW YORK CITY|THE CITY)|CITYWIDE|SYSTEM ?WIDE"
    r"|MULTIPLE STATIONS"
    r"|FLOOD\w*[^.]{0,50}\bIN (MANHATTAN|BROOKLYN|QUEENS|THE BRONX|STATEN ISLAND)"
    r"|\bIN (MANHATTAN|BROOKLYN|QUEENS|THE BRONX|STATEN ISLAND)[^.]{0,50}FLOOD"
)
PLANNED = re.compile(r"FLOOD (PROTECTION|MITIGATION|BARRIER|RESILIENCY|PREVENTION)")

# Active vs cleared, measured on the live family: the removal is finished only in the
# past tense ("after we removed", "we removed") or under a "What Happened?" heading;
# every present/progressive form is still ongoing. Ticket 13 renders the distinction.
CLEARED = re.compile(r"REMOVED WATER FROM THE TRACKS|WHAT HAPPENED")
ACTIVE, CLEARED_STATE = "active", "cleared"

# Former names: alert text uses the name of its era; ref/assets is current-only.
# Keyed by normalized former name -> current asset name.
FORMER_NAMES = {
    "149 ST GRAND CONCOURSE": "149 St-Hostos",
}

# ---- frozen dedupe keys (this ticket owns them; 04 and 13 consume them) ----
# Live alert ids are "lmm:alert:<event>:<update>": one physical incident keeps its event
# component across updates (264026 seen as updates 26/29/30/34), mirroring the Socrata
# new era's event_id/update_number.
# The event component is a TOKEN, not a number (widened by ticket 04, 2026-08-23): the
# 2012-2020 Socrata archive keys its incidents by a status_id GUID, and rendering that era
# into this grammar is what lets ONE extractor, with one measured precision, serve all
# three eras. The live feed's ids stay a strict subset.
ALERT_ID_RE = re.compile(r"^lmm:alert:(?P<event>[^:]+):(?P<update>\d+)$")
INCIDENT_KEY = ("event_id",)                # one panel chip per incident (13)
# the grain THIS module mints. Ticket 04 then merges concurrent events naming one complex
# into a single flood_obs row — reconciling them is the spine's job, not this module's.
OBSERVATION_KEY = ("event_id", "complex_id")
# alert_id is NOT a stable text key — see revisions(). The text belongs in the key.
REVISION_KEY = ("alert_id", "header", "description")

MIN_PRECISION = 0.90  # the label-grade gate (spec: Labels and the event spine)


def norm(s: str) -> str:
    # both apostrophes: two assets are spelled with one ("Prince's Bay"), and a curly one
    # falling through to the strip below would split PRINCES into PRINCE S and never match
    s = s.upper().replace("'", "").replace("’", "")
    s = re.sub(r"[/–—-]", " ", s)
    s = re.sub(r"[^A-Z0-9 ]", " ", s)
    s = ORDINAL.sub(r"\1", s)
    s = " ".join(WORD_CANON.get(w, w) for w in s.split())
    return re.sub(r"\bB T\b", "BETWEEN", s)


def alert_key(alert_id: str | None) -> tuple[str, int] | None:
    """'lmm:alert:264026:29' -> ('264026', 29). None when the grammar does not hold."""
    m = ALERT_ID_RE.match(alert_id or "")
    return (m["event"], int(m["update"])) if m else None


def load_aliases(root: Path | None = None) -> dict[str, list[dict]]:
    """ref/assets station rows -> alias -> candidate stations. Hyphen segments become
    their own aliases ("W 4 St-Wash Sq" is written "W 4 St" in alerts)."""
    root = root or data_root()
    con = duck.connect()
    rows = duck.table(con, Path(root) / "ref" / "assets").filter(
        "kind = 'station'"
    ).project("asset_id, name, complex_id, daytime_routes").fetchall()
    stations = [{"asset_id": a, "name": n, "complex_id": c, "daytime_routes": d or ""}
                for a, n, c, d in rows]
    con.close()
    return build_aliases(stations)


def build_aliases(stations: list[dict]) -> dict[str, list[dict]]:
    by_alias: dict[str, list[dict]] = collections.defaultdict(list)

    def add(alias: str, s: dict) -> None:
        if s["asset_id"] not in {r["asset_id"] for r in by_alias[alias]}:
            by_alias[alias].append(s)

    for s in stations:
        full = norm(s["name"])
        add(full, s)
        for seg in s["name"].split("-"):
            n = norm(seg)
            if n and n != full and len(n) >= 4 and (any(c.isdigit() for c in n) or " " in n):
                add(n, s)
    for former, current in FORMER_NAMES.items():
        for s in stations:
            if s["name"] == current:
                add(former, s)
        # a rename in ref/assets must fail loudly here, not silently stop resolving the
        # historic name (the prototype's guard; dropping it hid the rename entirely)
        if not by_alias[former]:
            raise KeyError(f"FORMER_NAMES target missing from ref/assets: {current}")
    return by_alias


def build_pattern(by_alias: dict) -> re.Pattern:
    aliases = sorted(by_alias, key=len, reverse=True)
    return re.compile(r"\b(?:" + "|".join(re.escape(a) for a in aliases) + r")\b")


def parse_routes(affected) -> set[str]:
    """Route sets are written '1 2 3' in ref/assets and '1|2|3' in the Socrata export."""
    if not affected:
        return set()
    return {p.strip().upper() for p in re.split(r"[|\s]+", affected) if p.strip()}


def _is_cause(t: str, m: re.Match, anchors: list) -> bool:
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


def extract(text: str, affected, by_alias: dict, alias_pat: re.Pattern) -> list[dict]:
    """Station matches with a cause flag, over header AND description joined."""
    t = norm(text)
    routes = parse_routes(affected)
    anchors = list(ANCHOR.finditer(t))
    taken: list[tuple[int, int]] = []
    matches: list[dict] = []
    for m in sorted(alias_pat.finditer(t), key=lambda m: -(m.end() - m.start())):
        if any(m.start() < e and m.end() > s for s, e in taken):
            continue
        taken.append((m.start(), m.end()))
        cands = by_alias[m.group(0)]
        picked = [c for c in cands if routes & parse_routes(c["daytime_routes"])] or cands
        matches.append({
            "alias": m.group(0), "span": [m.start(), m.end()],
            "cause": _is_cause(t, m, anchors),
            "complex_ids": sorted({c["complex_id"] for c in picked}),
            "names": sorted({c["name"] for c in picked}),
            "ambiguous": len({c["complex_id"] for c in picked}) > 1,
        })
    # "flooding between A and B": the second endpoint is joined to the first by " AND "
    by_start = sorted(matches, key=lambda x: x["span"][0])
    for i, a in enumerate(by_start[:-1]):
        b = by_start[i + 1]
        if a["cause"] and not b["cause"] and t[a["span"][1]:b["span"][0]] in (" AND ", " "):
            for anc in anchors:
                if anc.end() <= a["span"][0] and BETWEEN.fullmatch(t[anc.end():a["span"][0]]):
                    b["cause"] = True
    return matches


def flags(text: str) -> dict:
    tu = text.upper()
    hits = [s for s in re.split(r"(?<=[.!?])\s+", tu) if FLOOD_KW.search(s)]
    return {
        "system_wide": bool(SYSTEM_WIDE.search(tu)),
        "planned_work": bool(PLANNED.search(tu)),
        "footer_only": bool(hits) and all(s.lstrip().startswith("REMINDER") for s in hits),
    }


def state_of(t: str) -> str:
    """ACTIVE unless the text names a finished removal and no ongoing one."""
    if CLEARED.search(t) and not re.search(r"REMOV(?:E|ES|ING) WATER FROM THE TRACKS", t):
        return CLEARED_STATE
    return ACTIVE


def revisions(rows: list[dict]) -> list[dict]:
    """Captured rows -> one entry per REVISION_KEY. Two folds, both load-bearing.

    Rows are one per (alert x informed_entity), so the route set that disambiguates a
    station name only exists once the entities are folded back together. And alert_id is
    NOT a stable text key: the MTA edits header/description in place under the same id
    (50 distinct texts across the 24 captured water alert_ids, measured 2026-08-23), so
    the text belongs in the key — folding on alert_id alone keeps one arbitrary revision
    and silently loses every station named only in the others.
    """
    # Routes fold per alert_id, NOT per revision. An in-place edit splits the entity rows
    # of one alert across revisions, so a revision on its own sees only the routes that
    # happened to be captured while that text was live — a narrower set resolves fewer
    # station names and manufactures ambiguity the alert never had. Measured: folding
    # routes per revision costs two true labels ("79 St" under {2,3} instead of {1,2,3}).
    routes: dict = collections.defaultdict(set)
    for r in rows:
        if r.get("route_id"):
            routes[r.get("alert_id")].add(r["route_id"])

    folded: dict[tuple, dict] = {}
    for r in rows:
        key = tuple(r.get(k) for k in REVISION_KEY)
        a = folded.setdefault(key, {
            "alert_id": r.get("alert_id"), "header": r.get("header"),
            "description": r.get("description"),
            "routes": routes[r.get("alert_id")],
            "first_seen": None, "last_seen": None, "n_rows": 0,
        })
        a["n_rows"] += 1
        ts = r.get("fetched_at")
        if ts is not None:
            a["first_seen"] = ts if a["first_seen"] is None else min(a["first_seen"], ts)
            a["last_seen"] = ts if a["last_seen"] is None else max(a["last_seen"], ts)
    return sorted(folded.values(), key=lambda a: (a["first_seen"] or 0, a["alert_id"] or ""))


def scan(revision: dict, by_alias: dict, alias_pat: re.Pattern) -> dict:
    """One folded revision -> matches + flags + state, over header AND description."""
    text = "\n".join(filter(None, (revision.get("header"), revision.get("description"))))
    t = norm(text)
    return {
        **revision,
        "text": text,
        "flags": flags(text),
        "live": bool(LIVE.search(t)),
        "state": state_of(t),
        "matches": extract(text, " ".join(sorted(revision.get("routes") or ())),
                           by_alias, alias_pat),
    }


def observations(rows: list[dict], by_alias: dict, alias_pat: re.Pattern,
                 live_only: bool = True) -> list[dict]:
    """Captured rows -> one row per OBSERVATION_KEY. A match that does not resolve to
    exactly one complex mints nothing. State comes from the newest revision that named
    this complex, so a later "we removed" supersedes an earlier "we are removing"."""
    obs: dict[tuple, dict] = {}
    for revision in revisions(rows):
        key = alert_key(revision["alert_id"])
        if key is None:
            continue
        s = scan(revision, by_alias, alias_pat)
        if (live_only and not s["live"]) or s["flags"]["planned_work"] \
                or s["flags"]["footer_only"]:
            continue
        # one revision naming two aliases of the same complex is ONE sighting, not two
        hit = {m["complex_ids"][0]: m for m in s["matches"]
               if m["cause"] and not m["ambiguous"]}
        # ties on last_seen break on the update number: the higher update is the newer text
        rank = (s["last_seen"] or 0, key[1])
        for complex_id, m in hit.items():
            o = obs.setdefault((key[0], complex_id), {
                "event_id": key[0], "complex_id": complex_id,
                "name": m["names"][0], "first_seen": s["first_seen"],
                "last_seen": s["last_seen"], "state": s["state"],
                "alert_ids": set(), "n_revisions": 0, "n_rows": 0, "_rank": rank,
            })
            o["alert_ids"].add(revision["alert_id"])
            o["n_revisions"] += 1
            o["n_rows"] += revision["n_rows"]
            seen = [t for t in (o["first_seen"], s["first_seen"]) if t is not None]
            o["first_seen"] = min(seen) if seen else None
            if rank >= o["_rank"]:  # newest revision owns the state
                o["_rank"], o["last_seen"], o["state"] = rank, s["last_seen"], s["state"]
    return [{k: v for k, v in {**o, "alert_ids": sorted(o["alert_ids"])}.items()
             if k != "_rank"} for _, o in sorted(obs.items())]


def measure(root: Path | None = None) -> list[dict]:
    """Read every captured water row and print the observation table."""
    root = Path(root or data_root())
    by_alias = load_aliases(root)
    pat = build_pattern(by_alias)
    con = duck.connect()
    t = duck.table(con, root / "archive" / "subway_alerts")
    rows = [dict(zip(("alert_id", "header", "description", "route_id", "fetched_at"), r))
            for r in t.filter(
                "regexp_matches(upper(coalesce(\"header\", '') || ' ' "
                "|| coalesce(description, '')), 'FLOOD|WATER COND|WATER FROM THE TRACKS')"
            ).project('alert_id, "header", description, route_id, fetched_at').fetchall()]
    con.close()
    obs = observations(rows, by_alias, pat)
    print(f"rows {len(rows)}  alert_ids {len({r['alert_id'] for r in rows})}  "
          f"incidents {len({o['event_id'] for o in obs})}  observations {len(obs)}")
    for o in obs:
        print(f"  {o['event_id']} {o['complex_id']:>4}  {o['name']:<34} {o['state']:<8} "
              f"{o['n_rows']:>4} rows")
    return obs


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root", default=None)
    p.add_argument("--json", action="store_true", help="dump observations as JSON")
    a = p.parse_args()
    obs = measure(a.root)
    if a.json:
        print(json.dumps(obs, indent=1))


if __name__ == "__main__":
    main()
