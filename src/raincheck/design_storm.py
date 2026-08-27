"""Flood-build ticket 20: the design-storm sentence's DATA - the live MRMS rain rate
placed against DEP's discrete design-storm intensities, on `files/flood.json`'s OPEN side.

WHAT IT CLAIMS (DESTINATION-PLAN D2): "it is raining X mm/h here; DEP's Moderate design
storm is 54.10 mm/h". What it never claims: that water is present, or that a tier moved.
It is DISPLAY, never a detector input - `flood_detect` reads nothing here, the tier
vocabulary stays `fd.TIERS`, and nothing here writes anything `features.features_version()`
reads.

THE COMPARISON IS ARITHMETIC BETWEEN TWO OF THE SAME QUANTITY, settled by forecast 01
(2026-08-26) from DEP's own methodology source (the NYC Stormwater Resiliency Plan, 2021):
DEP's "in/hr" is a ONE-HOUR DEPTH read off an IDF curve at duration = 1 h, the same
estimand as `mm_1h`. Three qualifiers bind, and each has a structural home here:

  1. DEP's intensities are CLIMATE-ADJUSTED planning values, sitting above the historical
     (Atlas 14) frequencies whose names DEP also cites. So the strings quote DEP's LABEL
     only and never a return period - `display.climate_note` says so and a test asserts
     no frequency wording appears.
  2. The driving hyetograph's shape and total duration are never stated, so reaching an
     intensity does not reproduce its mapped extent - `display.extent_note` bounds the
     claim to intensity-vs-intensity.
  3. The rainfall figure is identical at both sea levels (Moderate current and 2050 are
     both one rate; only the tide boundary differs). `scenarios()` folds horizons under
     one rate per scenario and RAISES if DEP ever breaks that, so the sentence cannot
     imply the rain differs.

EVERY INTENSITY IS READ FROM `stormwater_extent.SCENARIOS`, NEVER RETYPED (flood-build
19's MUST; 21a's AST test pattern is copied for this module). The mm values are
`rain_in_hr * MM_PER_INCH` and that conversion happens in exactly one place, here.

THE ONLY OPENABLE EXTENT IS moderate/current: Limited's source is an unreadable
compressed FGDB (`stormwater_extent.UNREADABLE`) and Extreme exists only at 2080
sea-level rise (D3 keeps SLR horizons off the public host). `display.bracket_note` says
so rather than implying three rungs - and it does NOT restate the planning-grade honesty
line frontend2 03 already renders in the zone legend (that would be the page saying the
same thing twice, slightly differently).

THE IMPORT IS LAZY ON PURPOSE. `stormwater_extent` pulls `features` and builds a pyproj
Transformer at import time; this module runs inside the live pod (768 Mi limit, tick
peak 410 MiB with flood 17's overlays). The import is paid once per process, inside
`scenarios()`, and a test pins that importing this module alone pulls neither
`stormwater_extent` nor `features`. (pyproj itself is already on flood_panel's import
graph via `query` -> `ref`, so it is not part of this module's bill.)

NO NEW READ. The per-Cell rate is the newest landed hour of the rows `flood_panel._tick`
already materialised for the detector (`cell_hours`), so this module opens no file, no
connection and no socket - the RSS cost is the lazy import, measured in the ticket entry.

BASE RATE, measured by the ticket file (456,543 live Cell-hours, 2026-08-26): Limited
reached in 0.0039% of Cell-hours, Moderate and Extreme never; highest live mm_1h 53.93.
So the default wording is sized for "below every scenario" - `bracket` is ABSENT below
Limited, and a per-Cell dict exists only while it is actually raining there.
"""
from datetime import datetime
from functools import lru_cache

from raincheck.query import pack


@lru_cache(maxsize=1)
def scenarios() -> tuple[dict, ...]:
    """DEP's intensities, one row per SCENARIO (horizons folded), ordered by rate.

    Derived from `stormwater_extent.SCENARIOS` / `UNREADABLE` / `CURRENT` - no literal
    here to drift. `extent_open` is "a reader can open this extent today": declared at
    current sea level AND readable. `reason` rides only on a closed one.
    """
    from raincheck import stormwater_extent as se
    from raincheck.flood_obs import MM_PER_INCH

    out = []
    for name in dict.fromkeys(s.scenario for s in se.SCENARIOS):
        rows = [s for s in se.SCENARIOS if s.scenario == name]
        rates = {s.rain_in_hr for s in rows}
        if len(rates) != 1:   # qualifier 3 is structural: one rate per scenario, or stop
            raise RuntimeError(f"{name} carries {len(rates)} rates across horizons; the "
                               "one-rate-per-scenario fold no longer holds")
        at_current = [s for s in rows if s.horizon == se.CURRENT]
        if not at_current:
            reason = ("published at " + "/".join(sorted(s.horizon for s in rows))
                      + " sea-level rise only")
        elif at_current[0].key in se.UNREADABLE:
            reason = "source unreadable (compressed FGDB, no open driver)"
        else:
            reason = None
        rate = rates.pop()
        out.append(pack(scenario=name, rain_in_hr=rate,
                        mm_1h=round(rate * MM_PER_INCH, 2),
                        horizons=sorted(s.horizon for s in rows),
                        extent_open=reason is None, reason=reason))
    return tuple(sorted(out, key=lambda s: s["mm_1h"]))


def bracket(mm: float) -> str | None:
    """The highest DEP scenario whose one-hour depth this rate reaches; None below all,
    which is the live table's near-permanent state."""
    hit = None
    for s in scenarios():
        if mm >= s["mm_1h"]:
            hit = s["scenario"]
    return hit


def cell(mm: float | None) -> dict | None:
    """One Cell's `design_storm` member, or None (= an absent key) while it is not
    raining there. `bracket` is itself absent below Limited - `pack` drops it."""
    if mm is None or mm <= 0:
        return None
    return pack(mm_1h=round(mm, 2), bracket=bracket(mm))


def rates(rows: list[dict], now: datetime) -> tuple[dict[str, float], datetime | None]:
    """{hex Cell id -> mm_1h} at the newest landed hour <= now, plus that hour.

    The rows are `flood_panel.cell_hours`' output, already deduped to the newest
    `fetched_at` per (Cell, hour) by `parts()` - no second read and no second dedupe.
    Keyed by the H3 HEX string because that is what crosses the serving boundary
    (`fd.hexcell`; an int64 H3 id is past 2^53 and JSON corrupts it).
    """
    from raincheck.flood_detect import hexcell

    hours = [r["hour_end_utc"] for r in rows if r["hour_end_utc"] <= now]
    if not hours:
        return {}, None
    newest = max(hours)
    return ({hexcell(r["cell"]): r["mm_1h"] for r in rows
             if r["hour_end_utc"] == newest and r["mm_1h"] is not None}, newest)


def block(asof: datetime | None) -> dict:
    """`flood.json`'s top-level `design_storm`: the scenario table and the display
    strings frontend 08 renders the sentence from. Static per artifact; ~1 KB.

    The sentence anchors on the OPEN scenario (the one whose extent is on the page), with
    `{mm_1h}` the per-Cell placeholder. Every number in the strings is interpolated from
    `scenarios()` at write time - the strings hold no third copy of an intensity.
    """
    rows = scenarios()
    open_ = [s for s in rows if s["extent_open"]]
    closed = [s for s in rows if not s["extent_open"]]
    anchor = open_[0] if open_ else rows[0]
    display = {
        "sentence": (f"It is raining {{mm_1h}} mm/h here; DEP's "
                     f"{anchor['scenario'].title()} design storm is "
                     f"{anchor['mm_1h']:.2f} mm/h."),
        "bracket_sentence": "This hour's rate reaches DEP's {bracket} design intensity.",
        "bracket_note": (
            f"Of DEP's intensities, only the {anchor['scenario'].title()} extent at "
            "current sea level can be drawn: " + "; ".join(
                f"{s['scenario'].title()} ({s['mm_1h']:.2f} mm/h) {s['reason']}"
                for s in closed) + "."),
        "climate_note": ("DEP's intensities are climate-adjusted planning values, not "
                         "historical rainfall frequencies."),
        "extent_note": ("Reaching an intensity does not reproduce its mapped extent: "
                        "DEP's modelling drives a full storm profile that a one-hour "
                        "rate does not carry."),
    }
    return pack(scenarios=[dict(s) for s in rows],
                asof=asof.isoformat() if asof else None, display=display)


def read(rows: list[dict], now: datetime) -> dict:
    """One cycle's design-storm snapshot: {block, rates, summary}. Pure - no file, no
    connection - so it needs no wrapping of its own; `flood_panel.tick`'s catch covers it.
    `summary` is what rides on the tick's state for the one log line."""
    per_cell, newest = rates(rows, now)
    wet = {h: mm for h, mm in per_cell.items() if mm > 0}
    return {"block": block(newest), "rates": per_cell,
            "summary": pack(cells=len(wet),
                            max_mm_1h=round(max(wet.values()), 2) if wet else None)}


def line(summary: dict | None) -> str:
    """This module's fragment of the ONE log line per tick (the supervision surface)."""
    s = summary or {}
    n = s.get("cells", 0)
    return f"ds={n}" + (f"@{s['max_mm_1h']}" if n else "")
