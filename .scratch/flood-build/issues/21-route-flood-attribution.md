# 21 — Route flood attribution, descriptive v1

**What to build:** the join nobody owned. `src/raincheck/flood_route.py` + `make flood-route`
build `gold/route_flood`, one row per `(route_id, direction_id)`: Cells crossed, Cells
flood-prone, share of route length inside DEP's current-sea-level extent, flood events
recorded on the route's Cells, last event day, the three upstream stamps and a
`route_flood_version`. Plus ONE measured exhibit under `research/flood-21-route-exhibit.{md,json}`
— NOT in the Gold table.

**Gate:** flood-build 19 (`silver/stormwater_extent`), SATISFIED — `RUN-LOG.md`'s
"WAVE 6 GATE, PART 1" verifies it landed at `1fbb0d6`, +46, `features_version` unmoved.

**Source:** `DESTINATION.md` §3.F · `DESTINATION-PLAN.md` §0.3 and §1 D6 · `STATUS.md` Q6.
**The claim is DESCRIPTIVE and that is D6's decision, not a shortfall.** The statistical
claim's universe today is TWO events (§1 below); an interval over two events is a number
about the sample. The statistical table is the named upgrade, gated on the backfill.

**Status:** DONE 2026-08-26 — branch `flood-build-21a-route-flood`, **+51 `def test_` / 58
collected, 5 off-root skips**, **29 mutations with FIVE genuine survivors found and all
closed**, 683 rows, all four detector stamps unmoved, table byte-identical across three
builds.

- [x] `gold/route_flood` — one row per `(route_id, direction_id)`, **683 rows**, every id a
      string
- [x] `n_cells` (**1,119 distinct Cells crossed citywide**) and `n_cells_flood_prone`
      (`share_deep + share_nuisance > 0` in `silver/cell_stormwater`; **803 flood-prone
      Cells citywide**)
- [x] `share_len_moderate` — geodesic metres inside DEP's Moderate/current extent, **median
      0.0282, max 0.2825, 35 routes at 0.0**
- [x] `share_len_limited` / `share_len_extreme` — **NULL with the reason in the check batch,
      never 0.0** (§2)
- [x] `share_len_not_analyzed` — **not in the box, and it is the anti-conflation column**
      (§3). Max **0.805**: one route runs four fifths of its length through ground DEP
      EXCLUDED from the model
- [x] `n_flood_events` (distinct `event_id`, `kind = 'cell'`) and `last_event_day`
- [x] `label_version` · `features_version` · `zip_sha256` · `route_flood_version`
- [x] the exhibit, honestly bounded: **N = 2 events**, and the named comparison has an EMPTY
      intersection (§1)
- [x] IMPACT, NEVER A DETECTOR INPUT — all four stamps read on both sides of a real build
- [x] a `checks.Row` batch `route_flood` for orch 10 to expect on
- [x] NO `daily.STAGES` member — 21b is the WAVE 8 GATE's step; the diff is §7

---

## 1. THE EXHIBIT'S UNIVERSE IS TWO EVENTS, AND THE NAMED COMPARISON HAS AN EMPTY INTERSECTION

RE-MEASURED 2026-08-26, as the box asks. `gold/cell_hour_route` holds **two month
partitions and 13 NY-local days**, not two months:

| month | days held | hours |
| --- | --- | --- |
| `2021-09` | 2021-09-02 .. 2021-09-03 | 29 |
| `2026-08` | 2026-08-15 .. 2026-08-25 | 251 |

Exactly **two** of `silver/flood_events`' 206 events have days inside those HOURS:
**`2021-09-01`** (Ida, overlapping on 2021-09-02, 23 hours) and **`2026-08-20`** (23 hours).
`2021-09-24`, `2023-09-11/18/29` and `2026-08-03` all fall outside the hours held.

**DID I BUILD 2023-09 FIRST? NO, AND IT IS NOT BUILDABLE.** The box says to run
`make gold MONTH=2023-09` "if `silver/leg_hours`/`events` cover it". `silver/leg_hours`
DOES (2023-09-01 .. 2023-10-31, on disk). **`silver/events` does NOT: it holds eleven
service dates — `2021-09-02` and `2026-08-15..24` — and not one of them is in 2023.**
`gold.route()` reads `silver/events`, not `leg_hours` (`gold.py:66`), so
`make gold MONTH=2023-09` would write an EMPTY `cell_hour_route/month=2023-09` and add
nothing. `gold.speed()` reads `leg_hours` and 2023-09 is already built there — which is why
`cell_hour_speed` has six months and `cell_hour_route` two. Not attempted.

**AND THE TWO HALVES OF THE NAMED COMPARISON DO NOT OVERLAP.** This is the exhibit's finding:

| event | `late_share` / `ewt_s` | `cell_hourofweek_baseline` |
| --- | --- | --- |
| `2021-09-01` (Ida) | **NULL on all 86,914 rows** of `month=2021-09` | **`w1` exists** |
| `2026-08-20` | present on **345 of 346 routes** | **ABSENT** |

- **2021-09's delay columns are structurally NULL.** `late_share`, `ewt_s`,
  `mean_segment_excess_s`, `bunched_share` and `coverage` are NULL on every one of its
  86,914 rows; only `n_events` and `vp_coverage` are populated. `gold.route()`'s own
  docstring names the cause — unmatched / `pick_gap` rows carry NULL delay and headway
  columns throughout — and no Pick covers 2021.
- **2026-08 has no dry baseline and cannot get one.** `gold.baseline()` masks dry hours with
  `silver/precip_cell_hourly WHERE src = 'aorc'`, and AORC ends 2025-12-31 while the capture
  era is MRMS-only. The only partitions on disk are `w1` (2021-08-16..2021-10-15) and `w2`
  (2023-09-01..2023-10-31). flood 17 measured the same wall from the other side.

So the exhibit reports what each half CAN say and names the gap on the other:
**Ida gets a speed ratio** against `w1` (`gold/cell_hour_speed` event-hour speed over
`speed_dry` at the same (cell, hour_of_week); the ten slowest run **0.619 .. 0.751** of
their own dry speed, B70 lowest), and **2026-08-20 gets `late_share` / `ewt_s`** beside the
same route's other WEEKDAYS in the same month partition. That substitute is labelled as one
everywhere it appears: it is NOT `cell_hourofweek_baseline` and it is NOT hour-of-week
matched — **2026-08-20 is the only Thursday `month=2026-08` holds**, so an hour-of-week
match has n = 0 other days. No interval, no CSI, no cross-universe comparison.

**THE BASELINE IS NOT INDEPENDENT OF THE EVENT, AND THE ASSET SAYS SO.** `gold.baseline()`
masks by WETNESS, not by date, so an event day's own post-storm dry hours enter its own
baseline. Measured: of `w1`'s **668,847 Thursday dry Cell-hours, 64,160 (9.59%) are
2021-09-02 itself** — the event day is one of the window's nine Thursdays. It dilutes toward
NO difference, so a ratio below 1 is if anything understated. Stated, not corrected.

**WHAT THE STATISTICAL TABLE IS ACTUALLY GATED ON — three things, not one.** The box says
"the full backfill (pipeline-build 17) landing `cell_hour_route` for the event months". Row
count is the first of three: the backfilled months must also carry **schedule-matched delay
columns** (a 2021-shaped rebuild would land 86,914 more NULL rows), and an **AORC-era
`cell_hourofweek_baseline` window must cover them** — which for any capture-era month needs
a decision about switching the dry mask to MRMS, i.e. a different instrument deciding what
"dry" means. All three are written into the asset's `universe.gated_on`.

## 2. TWO OF THE THREE `share_len_*` COLUMNS HAVE NO SOURCE, AND NULL IS NOT 0.0

DERIVED from flood-build 19's own `SCENARIOS` / `UNREADABLE`, never retyped, so both
sentences follow that module if it changes:

| scenario | rain | current sea level | column | reason published |
| --- | --- | --- | --- | --- |
| `limited` | 1.77 in/hr | declared, UNREADABLE | **NULL** | `se.UNREADABLE[("limited","current")]` — compressed FGDB, no open driver |
| `moderate` | 2.13 in/hr | readable | measured | — |
| `extreme` | 3.66 in/hr | **not published at all** | **NULL** | DEP publishes 3.66 at horizon 2080 only |

The three columns are ALWAYS present and always in this order, so a consumer's schema does
not move; the day a re-encoded Limited source is pinned into `stormwater_extent.SCENARIOS`,
the column fills itself with **no code change here** (driven by a test that empties
`se.UNREADABLE` and watches `sourced()` grow). The two unsourced rows in the check batch are
**INCONCLUSIVE, never FAIL** — a container no driver can open says nothing about the data —
so **`make flood-route` exits 2 in its steady state**. §7 is why that decides the stage kind.

## 3. `not_analyzed` IS A CATEGORY, AND `share_len_not_analyzed` IS NOT IN THE BOX

`features.sample()` refuses to impute DEP's exclusion mask to "no flooding". This table
would have undone that from the other side: a route whose footprint is largely inside the
mask has an UNKNOWABLE flooded share, not a low one, and `share_len_moderate` alone cannot
tell those apart. **Measured: max 0.805** — one route runs four fifths of its length through
excluded ground with a perfectly honest `share_len_moderate` beside it. The column is
published, it is never summed into a flooded share, and a fixture route that runs the full
width of a masked Cell drives both halves.

## 4. TWO DEFECTS THE MEASUREMENTS FOUND, BOTH FIXED IN THIS TICKET

**(a) THE TABLE WAS NOT REPRODUCIBLE FROM ITS OWN INPUTS.** Two builds of the same code on
the same root DIFFERED: **74 of 683 `length_m`, 70 `share_len_moderate`, 64
`share_len_not_analyzed`, max relative 1.46e-15** — one ULP. GEOS's cascaded union is
order-dependent in the last bit and an aggregate's group is unordered, so `ST_Union_Agg`
picked a different input order per process. This is orch 11's `leg_hours.dist_m_sum`
arithmetic in a new place — but there the two sides were two RUNTIMES and the answer was a
stated `FLOAT_TOL`; here both sides are one module, so the fix is a TOTAL ORDER and the
digest stays exact. `ORDER BY s.pick_id, s.shape_id` inside both aggregates. **Three
consecutive builds are now byte-identical**, and a test is the gate.

**(b) A CELL THE ROUTE ONLY TOUCHED COUNTED AS A CELL IT CROSSED.** `ST_Intersects` is true
where a route ends exactly on a Cell boundary, and because `n_flood_events` JOINS through
the route-Cell table, a zero-length graze would put that neighbour Cell's whole flood
history on the route. The rule is now `ST_Length(ST_Intersection(...)) > 0` (a comparison to
0 is scale-free, so degrees answer it and no projection is owed). **On the real root the two
rules agree exactly — 14,217 = 14,217 route-Cell pairs** — so no published number moved
today; only the fixture can see it, which is what the fixture is for.

## 5. HOW THE GEOMETRY IS BUILT, AND WHAT IT IS A UNION OF

- **The route's ground is the UNION of every shape its trips use, across all six Picks.**
  Six Picks trace nearly the same street; summing would count it six times. `n_shapes` rides
  on the row (1,189 shapes over 683 route-directions). Every `shape_id` in `silver/shapes` is
  globally unique (**1,189 of 1,189**), so a shape belongs to exactly one (route, direction).
- **`(A ∪ B) ∩ C = (A ∩ C) ∪ (B ∩ C)`**: intersect per shape, where the geometries are
  small, then union at the route grain. That is what stops a street two Picks share being
  counted twice inside the extent while being counted once in the denominator.
- **Geodesic metres, from `schedule.GEOD` — the same `Geod(ellps="WGS84")` that computed
  `silver/shapes.length_m`** — so numerator and denominator are the same measure. Validated
  against that stored column as an independent oracle: **max relative difference 5.77e-08
  over all 1,189 shapes** (max absolute 0.00195 m), which is float32 rounding in the column.
  DuckDB does the topology, pyproj does the metric.
- **`hour_of_week` is the cross-engine trap and it is pinned.** `gold.baseline()` builds it
  in Spark as `((dayofweek(local) + 5) % 7) * 24 + hour(local)`, Monday 00 = 0; Spark's
  `dayofweek` is 1=Sunday and **DuckDB's is 0=Sunday**, so copying that expression shifts
  every hour by a day — measured, Monday 00:00 local reads **144** under the copied form.
  This module uses `isodow` (1=Monday). Confirmed against real data: Ida is a Thursday and
  its 24 hours land on 72..95, exactly Thursday's block.

## 6. `route_flood_version` — WHAT IS IN, WHAT IS OUT, WHAT IS NOT COVERED

sha1 over **exactly the inputs that can move a number**, and it hashes what the build READ
rather than what it declared — flood 18's finding is that a stamp over a declared input list
cannot see a tree that went missing, and a digest over the scan can.

**IN:** seven `md5` digests of the rows actually scanned (`trips` route→shape mapping ·
`shapes` geometry · `ref/cells` grid · current-horizon `extent` geometry · `cell_stormwater`
deep/nuisance shares · `cell_event` labels · `event_day`), the four upstream identities
(`label_version` · `spine_version` · `features_version` · `zip_sha256`), and the two rules
that decide what a number MEANS (`FLOODED` and `PRONE`).
**OUT, deliberately:** this module's prose, the check-row detail sentences, the column names
and the exhibit — flood 10's rule, rewording a sentence must not move a digest.
**NOT COVERED, and it is a real limit:** this hashes VALUES, so the module's own SQL rides
only as labels. Editing `footprint()` moves a share without moving the digest; the tests hold
that, not the stamp.

**Mutation-checked from BOTH sides**, which is what makes it worth reading: four inputs that
decide a number must move it, and **two real columns of hashed tables that decide nothing —
`share_not_analyzed` and `frozen_at` — must NOT**. Today's value:
**`30caaa170f4633f8ea6bbcbfb265deb8b292ae64`**.

**The four stamps this build must not move, read on both sides of the real run:**
`features_version 6b6f61e0231d6237ba93e9126eeb08fc0e16de21` (flood-build 19's known-good
value, asserted as a literal in the real-root test) · `matrix_version
8bc1e8912b1badadb69fa0bb5c676a65e0b8200b` · `score_version
dda793c2c8c7fb7bb27438e4dce16a120354a3aa` · `detector_version
01197991471fe33917ac4c583e56209db1d8c283`. All four unmoved.

---

## 7. FLOOD-BUILD 21b — THE EXACT DIFF, FOR THE WAVE 8 GATE

**NOT APPLIED HERE.** Registering the stage lands into a DAG orch 12 is cutting over, and
the WAVE 8 GATE applies it once orch 12's seven clean days are recorded (they now ARE —
`RUN-LOG.md`, orch 12, 2026-08-26 — but the CUTOVER itself is blocked on four refusing
writers plus a `gapfill` OOMKill, both measured there).

**READ THIS BEFORE APPLYING IT — the box's diff needs two corrections and one decision.**

**CORRECTION 1: the stage is a `gate`, not `"transport"`.** `make flood-route` exits **2 in
its steady state** (two of DEP's three scenarios have no current-sea-level source, §2), and
`daily.py` treats any non-zero as a FAILED stage. A `transport` stage would fail the nightly
every night on a designed INCONCLUSIVE. `eras` is the precedent and the reason is identical
— "a GATE with an argv, because both of its non-verdicts are INCONCLUSIVE rather than red,
and `make` would flatten that 2 into the same 2 a broken recipe exits with"
(`daily.py:122-128`). The `argv` is not optional.

**CORRECTION 2: the step-list property test needs NO edit.**
`tests/test_daily.py::test_the_driver_names_its_steps_from_the_declaration` is a PROPERTY
derived from `daily.STAGES` (it was a literal at line 240-241 when the box was written;
orch 06/07 made it a property). What DOES enforce the same-commit rule is
`tests/test_dag_nightly.py:150` — `raincheck_stage.shape_of(stage["name"])` raises
`KeyError` on a stage no `raincheck.io/stages` annotation places — and `test_daily.py:288`,
which requires the make target to exist. **Both go red on a one-part change**, which is the
coupling the box wanted; it just already exists.

**THE DECISION, AND IT IS THE GATE'S: none of this table's seven inputs is written by any
nightly stage, so a nightly rebuild is byte-identical work.** Measured against
`daily.STAGES` (gapfill · gapverify · gapcheck · coldpush · coldcheck · events · gold ·
precip · prune · eras · gxcheck): `silver/trips` and `silver/shapes` move only when
`make picks` lands a new Pick (401-blocked); `ref/cells` is frozen; `silver/stormwater_extent`
and `silver/cell_stormwater` are pinned to a sha'd DEP snapshot; `gold/flood_labels` and
`silver/flood_events` are the flood build chain, which is not nightly. **So a nightly
`flood_route` buys a burst node to rebuild an identical part file, every night.** The two
honest alternatives, both cheaper than the diff below:
(a) leave it a hand target and run it after `make flood-labels`, with the flood chain;
(b) register it and let it write, but only where `route_flood_version` moved — which is a
new predicate nothing in `daily.py` has today.
**The diff is written as asked; the recommendation is (a), and it is the gate's call.**

> **DECIDED — WAVE 8 GATE, PART 1 (2026-08-26): (a). The diff is NOT applied;
> `make flood-route` stays a hand target run with the flood chain, beside
> `make flood-labels`.** The measured case above is the whole reason: none of the seven
> inputs is written by any nightly stage, so a nightly `flood_route` buys a burst node to
> rebuild a byte-identical file every night. Option (b)'s moved-version predicate is new
> machinery `daily.py` does not have and nothing else needs. The diff above stays ready,
> verbatim, for the day an input starts moving nightly (a working Pick path, an unfrozen
> flood chain) — re-decide then, do not inherit this. Consequence at this gate:
> `raincheck_daily` stays FOURTEEN tasks and the `raincheck-stage` annotation is
> untouched. Recorded on STATUS by the same gate entry.

**Part 1 — `src/raincheck/daily.py`**, after the `gold` reduce and before `precip`
(it reads Gold and Silver, writes Gold, and stands in front of `gxcheck`, which reads
batches):

```diff
     Stage("gold", "py:raincheck.daily:gold", "transport", argv=("daily", "gold"),
           reduces="service_date"),
+    # flood-build 21b. A GATE with an argv for `eras`' reason and not by preference: two of
+    # DEP's three scenarios have no current-sea-level source, so this stage's steady-state
+    # rc is 2 = INCONCLUSIVE, and `make` would flatten that into the same 2 a broken recipe
+    # exits with. It writes gold/route_flood and emits the `route_flood` check batch.
+    Stage("flood_route", "make:flood-route", "gate", argv=("flood_route",)),
     Stage("precip", "py:raincheck.daily:precip", "transport", fanout="month", argv=("daily", "precip")),
```

**Part 2 — `deploy/k8s/raincheck/build.yaml`, the `raincheck-stage` template's
`raincheck.io/stages` annotation (line 35), in the SAME commit.** `raincheck-stage` and not
`raincheck-spark`: this module opens **no JVM** (DuckDB + pyproj + shapely only), so orch
09's `eras` reasoning does not apply. **MEASURED on the real root: peak RSS 396,394,496 B =
378 MiB in 13.77 s**, against that shape's `limits.memory: 1Gi` — it fits, and the number is
here because orch 12 found four of five `gapfill` kinds OOMKilled in this same shape for
exactly the want of one.

```diff
-    raincheck.io/stages: "gapfill, gapverify, gapcheck, coldpush, coldcheck, prune, gxcheck"
+    raincheck.io/stages: "gapfill, gapverify, gapcheck, coldpush, coldcheck, prune, flood_route (measured 378 MiB / 13.8 s on the real root), gxcheck"
```

**Part 3 — no test edit is owed** (Correction 2). To VERIFY the two-part change rather than
trust it, in the airflow-pinned venv:

```
python -m pytest tests/test_daily.py tests/test_dag_nightly.py tests/test_dag_delivery.py -q
python -c "import sys; sys.path.insert(0,'dags'); import raincheck_stage as s; print(s.shape_of('flood_route'))"
```

The second must print `raincheck-stage`; before Part 2 it raises `KeyError`, which is the
coupling working.

---

## 8. WHAT THIS TICKET DELIBERATELY DID NOT DO

- **No `publish.FAMILIES` entry and no `contract.SCHEMA` edit.** `gold/route_flood` is a
  Gold table; **frontend2 04 (wave 8) is the ticket that turns it into `files/summary/routes.json`**
  and owns that family. Adding one here would collide with flood 17's `impact` family in the
  same wave for no gain.
- **No `web/` edit and no route rendered.** frontend2 03 owns the page this wave.
- **No GX suite.** orch 10 has landed and will not see this batch; §9 hands orch 13 the
  exact `CHECK_COLUMNS` and a measured row table instead, the way flood-build 19 did.
- **No `daily.STAGES` member** (§7).
- **No `query.QUERIES` entry.** The seam is frozen for wave 7 by notify 06's box.

## 9. THE CHECK BATCH, FOR ORCH 13 / A LATER SUITE TICKET

Producer name **`route_flood`**, written to `<root>/checks/check=route_flood/run=<ts>.jsonl`.

`CHECK_COLUMNS = checks.CORE + ("scenario", "horizon", "rain_in_hr", "share_len_min",
"share_len_median", "share_len_max", "routes", "routes_zero_geometry", "routes_no_cells",
"cells_crossed", "cells_flood_prone", "flood_events", "label_version", "features_version",
"zip_sha256", "route_flood_version")`

**Four rows, measured on the real root 2026-08-26 (rc 2):**

| subject | outcome | the measures that carry a value |
| --- | --- | --- |
| `table` | `ok` | routes **683** · routes_zero_geometry **0** · routes_no_cells **0** · cells_crossed **1,119** · cells_flood_prone **803** · flood_events **206** |
| `limited current` | **`inconclusive`** | rain_in_hr 1.77 · every `share_len_*` **NULL** |
| `moderate current` | `ok` | rain_in_hr 2.13 · min **0.0** · median **0.0282** · max **0.2825** |
| `extreme current` | **`inconclusive`** | rain_in_hr 3.66 · every `share_len_*` **NULL** |

**A SUITE OVER THIS BATCH BELONGS ON `gx.NON_NIGHTLY`, NEVER `gx.SUITES`** — appending to
`SUITES` makes it nightly and judges it off whatever batch last landed. Two rules it
inherits, both already paid for elsewhere:

- **The judged frame is 2 rows, not 4** — the two INCONCLUSIVE scenario rows are held out,
  exactly as flood-build 19's `stormwater_extent` batch is 12 rows with an 11-row judged
  frame. An `ExpectColumnDistinctValuesToEqualSet` over the three scenarios goes RED for that
  reason alone. **Every PER-ROW claim goes to the judged subset and every BATCH-LEVEL claim
  (row count, "one row per declared scenario") must be made over the WHOLE batch, before the
  split** (orch 08's rule).
- **NULL is the could-not-check convention, so pair every between-expectation with a
  not-null** — a between counts nulls as MISSING and succeeds without them.
- **A named run must render `<root>/gx/docs-route_flood` and leave `<root>/gx/data_docs`
  alone**: that directory is `publish.FAMILIES["docs"].src()` and `build_data_docs()`
  rebuilds the WHOLE site, so a named run writing there DELETES the nightly's published pages
  (orch 10's `docs` parameter exists for this).

## 10. THE COLUMNS, FOR frontend2 04

`gold/route_flood/part-00000.parquet`, 683 rows, read with
`duck.table(con, root / "gold" / "route_flood")` or `read_parquet`.

| column | type | note |
| --- | --- | --- |
| `route_id` | string | a FACT and safe to render as text — see §11 |
| `direction_id` | string | `"0"` / `"1"`, never an int |
| `n_shapes` | int32 | shapes unioned into the footprint, across all six Picks |
| `length_m` | double | geodesic; **a share is unreadable without its denominator** |
| `n_cells` | int32 | Cells crossed with POSITIVE length (min 3 · median 16 · max 70) |
| `n_cells_flood_prone` | int32 | of those, `share_deep + share_nuisance > 0` |
| `share_len_limited` | double | **NULL today** — no current-SL source, §2 |
| `share_len_moderate` | double | 0.0 .. 0.2825, median 0.0282 |
| `share_len_extreme` | double | **NULL today** — no current-SL source, §2 |
| `share_len_not_analyzed` | double | **read it beside `share_len_moderate` or you will call excluded ground dry**, §3 |
| `n_flood_events` | int32 | distinct `event_id`; min 16 · median 80 · max 152 |
| `last_event_day` | date32 | min 2025-10-30 · max 2026-08-20 — every route has a recent one |
| `label_version` | string | `46bbfd665b78129a1c604756b58da6523c018ca4` |
| `features_version` | string | `6b6f61e0231d6237ba93e9126eeb08fc0e16de21` |
| `zip_sha256` | string | the DEP snapshot the extents came from |
| `route_flood_version` | string | `30caaa170f4633f8ea6bbcbfb265deb8b292ae64` |

**A NULL share is not a zero and a published payload must not flatten it to one.** Emit the
key ABSENT or null with the reason; `0.0` is a claim that the route is dry.

## 11. LICENCE — A ROUTE ID IS A FACT; A ROUTE BULLET IS MTA IP

Ross read the MTA website T&C 2026-08-26 (`STATUS.md` [YOU] item 5). Its *Trademarks and
permissions* section names the subway line logos and MTA official maps as usable only with
prior written permission. **This ticket is route-grain and therefore the one most likely to
trip it.** A `route_id` as a string in a table, a check row or a payload is a FACT and is
fine. Rendering it as a coloured circular bullet or roundel, or borrowing MTA's official
line colours as a palette, is not. **This build ships no colour, no bullet, no
`route_color` and no `daytime_routes` — the tree is clean and this ticket kept it that way.**

## 12. RUN

```
make flood-route            # gold/route_flood + the check batch; rc 2 is the steady state
make flood-route-exhibit    # research/flood-21-route-exhibit.{md,json}; reads only
```

The TABLE needs no `make gold` — none of its inputs is a Gold table. **The EXHIBIT does**:
it reads `gold/cell_hour_route`, `gold/cell_hour_speed` and `gold/cell_hourofweek_baseline`.

## DONE 2026-08-26

Branch `flood-build-21a-route-flood`, worktree `/Users/ross/raincheck-wt/fb21a`.
683 rows · exhibit N = 2 · **+51 `def test_` / 58 collected / 5 off-root skips** · three
byte-identical builds · all four detector stamps unmoved · 13.77 s / 378 MiB peak.

**TWO DEFECTS FOUND BY MEASURING THE BUILD** — the unordered union aggregate (§4a) and the
touch-counts-as-a-crossing rule (§4b).

**AND FIVE MUTATION SURVIVORS, EVERY ONE A REAL HOLE. 29 mutations over six rounds, all
killed; pristine control green at both ends of every round; tree clean after every restore.**
Harness under every TRAPS rule: refused a dirty tree, snapshotted from git (and asserted the
working file equals `HEAD`), `PYTHONDONTWRITEBYTECODE=1`, `git checkout` AND `git clean`
after each row, and proved each mutant LANDED before believing a survivor.
1. **`late_share` weighted over ALL `n_events` instead of over the rows that HAVE one.**
   On the real root only 3,161 of 1.36 M rows are NULL, so the two answers differ in the
   fourth digit and nothing could see it — the Gold-table fixture has no `cell_hour_route` at
   all. Closed by planting one: 100 arrivals with a share and 900 without, so the two
   readings are 0.5 and 0.05.
2. **The same rule again, in `other_days`' own copy of it.** Killing (1) left (1b) alive:
   two functions hold the rule and the substitute dry side needed its own discriminating
   pair.
3. **`ewt_s`, the third copy** — found by mutating it once (1) and (2) were closed.
4. **A baseline window NAMED without checking it is on disk.** The join is silently empty
   either way, so only the reported name tells them apart. Closed with an event whose day is
   inside `w2`'s declared span while no `w2` partition exists.
5. **The linear-parts guard in `geodesic_m`, and the fixture was DEGENERATE FOR EXACTLY THE
   TERM IT PINNED.** `GEOD.geometry_length` of a POINT is **0.0**, so a collection of a line
   and a point cannot see the guard at all. A POLYGON can: pyproj returns its PERIMETER,
   3,911 m against the line's 845 — a 5.6x over-count. The fixture now carries both.
Plus one the harness lied about: a "drop the batch row" mutation written as `out = [] or
[...]`, which is a no-op. Re-run properly, it kills 4.

Every acceptance row above is ticked with what is behind it.
