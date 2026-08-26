# 17 — Live impact overlays: consequence beside cause

**What to build:** The bus and subway impact overlays on the flood panel — Cell-grain bus slowdowns and
complex-grain subway service beside the detector, labelled "impact — never a detector input",
rendered when present and greyed when absent. Spec: Impact signals (live), Real-time detector
(serving); Testing seam 3.

**Blocked by:** 15, 16 — and externally on the pipeline build: 12 (streaming job) + 14 (live export) for bus Gold, and the pipeline wayfinder's ticket-15 TU capture for subway; the overlay renders greyed until each lands, by design

**Status:** DONE — landed 2026-08-26, branch `flood17-live-impact-overlays`, `bb8d76f`,
`src/raincheck/flood_overlay.py` + the merge into `flood_panel.tick`.

- [x] the bus overlay file at Cell grain and the subway overlay file at complex grain, keyed on (Cell | complex, hour_end_utc), showing the last CLOSED Hour; rendered when present, greyed when absent, labelled "impact — never a detector input"; bus stops take the Cell fallback; never two kinds in one legend
      — `files/impact.json` (`cells`, keyed by the H3 HEX STRING) and
      `files/impact-subway.json` (`complexes`, keyed by `complex_id`), each carrying its
      own `hour_end_utc` for the last CLOSED hour. There is no bus-stop row to fall back:
      the bus overlay is Cell grain end to end, so a stop reads its Cell by construction.
      Two files, two grains, two legends. `label` rides on both documents at the top level
      AND at `strings.label`.
- [ ] **the conditional live-bus baseline build item activates: cell_hourofweek_baseline over a 2026-era window — never the backfill-era baselines; capture-era baselines accumulate from capture days; ratios NULL until at least two same-weekday baselines exist**
      — **THE READER IS BUILT AND THE RULE IS ENFORCED; THE BUILD IS BLOCKED, AND NOT ON
      TIME.** `flood_overlay.LIVE_WINDOW = "live"` names the ONE partition this overlay may
      read and `MIN_BASE_DAYS = 2` is the same-weekday floor; a mutation-checked test
      writes joinable rows under BOTH backfill windows (`w1`, `w2`, read out of `gold.py`'s
      own source) and requires no `ratio`. **The blocker is a SOURCE gap, not a day count**:
      `gold.baseline()` masks dry hours with `silver/precip_cell_hourly WHERE src = 'aorc'`,
      and AORC ends **2025-12-31** while the capture era is 2026-08 — measured, the join is
      empty, so `make baseline WINDOW=<2026 window>` would write nothing whatever the day
      count. Ten capture days exist (2026-08-15 .. 2026-08-24) and three weekdays already
      have two, so the DAYS are there. Activating this needs two decisions that are not
      this ticket's: switch the capture-era dry mask to MRMS (the only capture-era source),
      and add the window name to `gold.WINDOW`, whose subparser `choices` would otherwise
      refuse it. Until then `state` is `no_baseline`, `ratio` is an ABSENT key on every
      Cell, and `baseline.reason` says so in a sentence the panel renders.
- [x] subway live: the TU-capture stop-row-disappearance inference pass, level-compared against subwaydata on overlapping days BEFORE any cross-source display (Precip-source-style discipline — sources never pooled)
      — the pass is `flood_overlay.SUBWAY_SQL`: a planned stop row that vanished while its
      run was STILL being reported and its arrival was STILL ahead. Both guards are
      mutation-checked. **The level comparison is MEASURED and it has ZERO overlapping
      days**: `archive/subway_tu` starts 2026-08-26 and the subwaydata agg corpus ends
      2026-08-10 (646 days, `ERA_HI` 2026-08-15). So no absolute rate is displayed at all —
      what ships is `rel`, the complex against the CITYWIDE MEDIAN of the same hour of the
      SAME feed, which is within-source and needs no calibration. `level_check` states the
      count it measured every cycle and is `no_overlap` today. No subwaydata number crosses
      into either payload, and `flood_impact` is not imported.
- [x] export-file seam tests: overlay files parse, absent hours grey rather than zero, the impact label renders from file data
      — `tests/test_flood_overlay.py`, 31 tests, real parquet fixtures read through DuckDB.
      Nine mutations were run against the harness; the first pass left THREE alive (the
      capture-era window, the two-day floor and the planned floor were each pinned against
      their own constant) and all nine die now.

## Inherited from frontend 02 (prototype, `4ac3ebe`, 2026-08-24) — measured against `gold/cell_hour_speed`

Frontend 02 built your bus overlay from `gold/cell_hour_speed` (your own input) because your
two export files do not exist yet, and measured two things you inherit:

- [x] **Your grain is sparse at the head, and the panel has to say so.** RE-MEASURED
  2026-08-26: newest closed hour **19 Cells**, densest **1,169** — and both ride the
  payload every cycle as `n_cells` / `densest_cells` / `densest_hour_end_utc`, so the
  sentence is a measurement rather than a frozen string.
- [x] **You land on the SAME ~1,200 H3 Cells the delay layer already fills.** RESOLVED by
  frontend 05 before this ticket ran and honoured here: the Cell FILL is one EXCLUSIVE
  radio sharing `RATIO_STOPS`, and this overlay ships **no ramp of its own** — the only
  colourable key is `ratio`, which is the same Speed-ratio quantity. Cells are keyed by
  the H3 hex string so `impact.json`, `flood.json`'s `cells` and `cells.geojson` join with
  no lookup. The subway overlay is complex-grain POINTS, a different channel entirely, so
  it does not touch the radio.
- [x] **NAMED AND FROZEN:** `files/impact.json` — `cells{<h3 hex>: {speed_mps, n_legs,
  n_vehicles, ratio?, baseline_days?}}` — and `files/impact-subway.json` —
  `complexes{<complex_id>: {name, lon, lat, cell(hex), planned, dropped, runs, drop_share,
  rel?}}`. Family `impact` in `publish.FAMILIES`, GATED, no meta. `contract.SCHEMA` names
  both; `contract.CONTRACT` stays `1` (additive under `PROMISE[1]`).
  (This closes frontend 02's "name your two export files" bullet: they are code now, not
  prose — `flood_overlay.FILES`, pinned to `publish.FAMILIES` by a test.)

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

**ANSWERED, 2026-08-26 (`bb8d76f`) — all four:** `files/impact.json` landed at that exact
name, so no page edit was owed. The family is GATED (`mta-vehicles`). No ramp and no second
fill channel were added — `ratio` is the only colourable key and it is the delay layer's own
quantity. **TWO budget constants shipped, both DERIVED:** `impact_bus` **122400 s** (34 h =
one nightly cycle + `daily.TAIL_H`, imported) and `impact_subway` **4200 s** (the hour +
`archiver.WINDOW`, pinned to that module by a test rather than imported — `archiver` pulls
the protobuf decoders and this tick has no other reason to hold them). Both ride `budgets_s`
beside a `staleness` verdict already computed at the READER, so the page can render the
verdict directly or recompute it. **A SECOND FILE was added that the LAYERS table does not
name: `files/impact-subway.json`** — complex-grain points, no layer yet; frontend 08 owns
declaring it, and the MUST is on its ticket file.

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
