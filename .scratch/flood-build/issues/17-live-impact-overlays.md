# 17 — Live impact overlays: consequence beside cause

**What to build:** The bus and subway impact overlays on the flood panel — Cell-grain bus slowdowns and
complex-grain subway service beside the detector, labelled "impact — never a detector input",
rendered when present and greyed when absent. Spec: Impact signals (live), Real-time detector
(serving); Testing seam 3.

**Blocked by:** 15, 16 — and externally on the pipeline build: 12 (streaming job) + 14 (live export) for bus Gold, and the pipeline wayfinder's ticket-15 TU capture for subway; the overlay renders greyed until each lands, by design

**Status:** ready-for-agent

- [ ] the bus overlay file at Cell grain and the subway overlay file at complex grain, keyed on (Cell | complex, hour_end_utc), showing the last CLOSED Hour; rendered when present, greyed when absent, labelled "impact — never a detector input"; bus stops take the Cell fallback; never two kinds in one legend
- [ ] the conditional live-bus baseline build item activates: cell_hourofweek_baseline over a 2026-era window — never the backfill-era baselines; capture-era baselines accumulate from capture days; ratios NULL until at least two same-weekday baselines exist
- [ ] subway live: the TU-capture stop-row-disappearance inference pass, level-compared against subwaydata on overlapping days BEFORE any cross-source display (Precip-source-style discipline — sources never pooled)
- [ ] export-file seam tests: overlay files parse, absent hours grey rather than zero, the impact label renders from file data

## Inherited from frontend 02 (prototype, `4ac3ebe`, 2026-08-24) — measured against `gold/cell_hour_speed`

Frontend 02 built your bus overlay from `gold/cell_hour_speed` (your own input) because your
two export files do not exist yet, and measured two things you inherit:

- [ ] **Your grain is sparse at the head, and the panel has to say so.** The NEWEST closed
  hour in `gold/cell_hour_speed` carries **24 Cells**; the densest carries **1,169**. An
  overlay that renders "the last closed hour" will usually be a near-empty map. Painting 24
  Cells without saying they are 24 reads as a claim about the city.
- [ ] **You land on the SAME ~1,200 H3 Cells the delay layer already fills**, so a second
  Cell FILL is a direct collision on one geography. Frontend 02's variations resolve it
  either by making the fill channel EXCLUSIVE (the two are the same quantity — a Speed ratio
  — at different time-scales, so they share one frozen ramp) or by moving this overlay to
  the Cell OUTLINE channel. **Do not assume you get the fill**; the choice is Ross's on
  frontend 02 and it decides your paint channel.
- [ ] **Name your two export files and their keys in the close-out** — nothing in the tree
  freezes either today (prose only, no code). Same as flood 15's third bullet.

## MUST from frontend 05 (the chassis landed 2026-08-25, `frontend05-seven-layer-chassis`)

- **The page reads your overlay at `web/files/impact.json`.** That URL is already in the
  live page's `LAYERS` table; land it, or land another name and correct this line, the
  table and your summary line in the same commit.
- **The overlay is on the GATED (`mta-vehicles`) side of the lineage gate** — same side as
  the live fleet, because its lineage is `gold/cell_hour_speed` <- VP. It renders as a
  disabled, explained GATED row today and lights when the terms receipt lands.
- **It gets NO ramp of its own and can never be lit at the same time as the delay fill.**
  This is now structural rather than advisory: `impact` is one of exactly two `fill: true`
  layers, the two are RADIOS in one group, and `toggle()` clears the other in the state as
  well. A test kills the mutation that removes it. Do not ship a second ramp; do not ask
  for a second fill channel.
- **A budget constant is what graduates its freshness row from AGE to FRESH/STALE.** Ship
  one and the page reads a verdict; ship none and it honestly reports an age.

## Forward-context from DESTINATION-PLAN.md (copied verbatim by the WAVE 5 GATE PART 2, 2026-08-25, from this ticket's summary line in waves/wave-3-plus.md)

**FROM DESTINATION-PLAN (2026-08-25):** you are the ONLY editor of `live_loop.py`/`flood_truth.py` in wave 7 (flood-build 20 was held to wave 8 for that reason); where `impact.json` lives in `publish.FAMILIES` is your call — frontend 05 froze the filename, not the family. Route-grain attribution is NOT yours: flood-build 21 owns it (descriptive v1); your Cell-grain caveats (median event day indistinguishable; only the tail reads) are inherited by it verbatim.

## FROM FLOOD 15 (2026-08-25, `flood15-panel-exports`, `5925813`) — THE TICK YOU MERGE INTO

You are the ONLY editor of `live_loop.py` and `flood_truth.py` in wave 7, and the flood
tick is already inside the loop. **Do not add a second call to `cycle()`** — merge into
the one that exists, the same way this ticket merged into cloud 05's.

**THE SEAM.** `live_loop.cycle()` now ends:

    flood = flood_panel.tick(con, root, out_dir, state.get("flood"), now, detected)
    return {"meta": ..., "detector": detected, "detected_at": ..., "flood": flood,
            "publish": ship(out_dir, state), "at": now}

`flood_panel.tick(con, root, out_dir, prev, now, detector=None, ship_=None) -> state`.
It NEVER raises: an outage comes back as `state["error"]` and the loop carries on. It
SKIPS unless the newest `valid_ts=` partition name moved or the artifact's
`throttles.floodnet_s` (120 s) expired — measured 6 work cycles in 21 ticks, the rest
returning in under 10 ms. `detector` is the loop's own `flood_live.live()` read, already
fetched on the 360 s `DETECT_S` cadence; take yours from there rather than fetching again
at the render rate (that is the false-OUTAGE failure `DETECT_S` exists to prevent).

**WHERE YOUR TWO OVERLAYS GO.** `publish.FAMILIES` now has `flood` (open) and `flood-mta`
(GATED with `live.geojson`). Your overlays are BOTH VP/TU-derived, so they are on the
GATED side: either append to `flood-mta`'s `files` tuple (it is `("flood-mta.json",
"flood-mta-meta.json")`, meta LAST — a third payload goes BEFORE the meta) or add your
own gated family for `files/impact.json` (frontend 05 froze that filename; the family is
your call). **Do not put anything MTA- or VP-derived into `flood`** — `make
release-check` has a row that fails if an alert id, a complex id or the word `mta`
reaches the open side, and that row is the whole point of the split.

**FOUR THINGS THAT WILL SAVE YOU A DAY.**

1. **The pod is limited to 768 MiB and this tick already peaks at ~500 MiB** (raised from
   384Mi to a measured 512Mi request in `deploy/k8s/raincheck/live.yaml`). Three reads in
   this path cost **6,576 MiB** before they were rewritten. The rule, and it is not
   style: **projection and predicate go INSIDE the read's own statement.**
   `duck.table()` binds the path as a PARAMETER, so a `.filter()/.project()` chain or a
   view queried afterwards cannot push into the scan — `flood_truth.alert_rows` was
   5,000 MiB and 9.4 s for SIX rows that way, and 173 MiB / 0.25 s in one statement. Use
   `flood_panel._rows(con, sql_with_{read}, path)`, and MEASURE your read's peak RSS.
2. **Your grain is sparse at the head, and the panel has to say so** (frontend 02): the
   newest closed hour of `gold/cell_hour_speed` carries 24 Cells, the densest 1,169.
3. **The Cell fill is an exclusive channel** — the delay layer already fills the same
   ~1,200 Cells. `cells` in `flood.json` is keyed by the H3 HEX string, the same spelling
   `cells.geojson` uses; key yours the same way so all three join without a lookup.
4. **`flood_truth.mta()` now attaches lon/lat/cell to every chip station** via
   `complex_points(root)` + `place()`. If you touch that module, keep it: a payload that
   names an asset a consumer cannot locate is a defect this repo has now shipped twice.

The honesty strings you owe (median event day indistinguishable; weekends unreadable;
only the tail reads — Ida 157) are yours to write, but put them where this ticket put
its own: **under `display` in the detector artifact if the panel branches on them, or in
your payload's `strings` object** — never typed into a JS file, because `display.*` is
outside `detector_version` and a reworded label must not roll a live Window.
