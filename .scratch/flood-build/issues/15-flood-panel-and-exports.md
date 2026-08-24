# 15 — Flood panel and exports: the third section, honestly degraded

**What to build:** The flood tick inside the existing 30 s export loop and the panel section it feeds:
three export files, the static-to-live display switch, latched tier chips, the truth tiers beside
the model, every source aging independently, and the fixed claim strings — no new daemons
anywhere. Spec: Real-time detector (serving, claims, logging); Testing seam 3.

**Blocked by:** 11, 12, 13, 14 — and externally on the pipeline build: 11 (live-precip job, as amended with the catch-up fetch) and 13 (page skeleton + the pure-SQL JSON writer / merge-patch path). Explicitly NOT blocked by pipeline 12 (Kafka/streaming) — the spec ships the flood panel ahead of the bus live view: the flood tick joins pipeline 14's 30 s loop if it has landed, else stands the loop up itself with flood keys only and pipeline 14 merges its bus payload into the same process later

**Status:** ready-for-agent

- [ ] the flood tick joins the existing 30 s export loop: one process, one meta file whose flood keys the single writer merges, cycles cannot overlap; the tick skips work unless the newest precip stamp advanced or a truth-source throttle expired (FloodNet 120 s, CO-OPS 360 s, NWS 300 s); every fetch has a hard 3 s timeout; last-good values keep their own age; one hung socket never stalls the bus panel
- [ ] three export files — all Cells as geometry, point Units only at ELEVATED+, the truth payload — written through the same pure-SQL merge-patch path (absent keys, never nulls), payload-then-meta atomic replace, one cycle_id across the set
- [ ] staleness budgets from measured cadences: precip fresh ≤ 90 min from the stamp, stale to 180, down past 180, holes indicated separately; FloodNet 10 min; CO-OPS 30 min; NWS 15 min — every panel source shows its own age and error state
- [ ] the panel: static exposure view (score_index) in dormant weather; an active Window switches to the live within-kind rank; tier chips latched per ticket 12's recorded decision — if the replay dropped v1 to rank-only, the panel renders rank without tier chips and says so; INSUFFICIENT_DATA and HOLES render as their own states ("ranks computed on N of M rainfall hours"); winter-gate suppression with its label; per-kind legends never mix kinds; base rates worded as fit-era frequencies
- [ ] claims as fixed strings: headline "flood-report exposure rank" with the estimand `flooded_reported` named; the always-visible reporting-propensity sentence; the panel trails the storm; rank-only and uncalibrated in v1; the Window named in the tier label; the within-Cell note (live ordering inside a Cell is purely static); the frozen operating-truth string, verbatim and unedited — "raincheck ranks where a flood REPORT is likely from rain that has already fallen, on hour-grain evidence that trails the storm. A rank is not an observation of water, and a quiet panel or a quiet inbox means nothing was flagged, not that nothing flooded." (frozen by notify 01, 2026-08-23; it replaces the retired storm-page claim, which a notifier falsifies, and notify 09's render reuses these exact words so the panel and a message cannot contradict each other); the B2-branch alternate strings selected by the shipped model id
- [ ] version-skew between the coefficient and detector JSONs refuses the model tier with the reason rendered; truth tiers stay up
- [ ] logging: one NDJSON file per day — the full unit-state vector only when the model tier recomputes (~24/day), the flagged subset per cycle, truth snapshots on change; ~3 MB/day, ≤ ~100 MB under the 30-day prune-on-start, inside the data-root byte budget
- [ ] export-file seam tests: absent keys never nulls; one cycle_id across the set; a deleted live root yields error + stale meta, not a crash; skew refusal; tier chips render from file data alone

## Inherited from frontend 02 (prototype, `4ac3ebe`, 2026-08-24) — measured against YOUR code

Frontend 02 built three throwaway variations of the integrated map and, because your three
export files do not exist yet, painted the flood tiers from `flood_truth.truth()` itself
rather than invent a schema. Three things it measured land on this ticket:

- [ ] **Emit COORDINATES on the truth payload's MTA chip.** `flood_truth.chips()` returns
  `{event_id, stations[{complex_id, name, state}], alert_ids, first_seen, last_seen, state,
  age_min}` — nothing spatial — so a page cannot put an affected station on the map without
  a second lookup against `ref/assets`. Measured price of closing it here: **all 445
  complexes with lon/lat = 30,087 B raw**, against the 161,455 B `truth()` already returns.
  (`ref/assets` is the only source of a complex's lon/lat, and it is exactly the join a
  serving page should not have to do.)
- [ ] **Export the staleness budgets as CONSTANTS, not prose.** Only
  `flood_truth.MAX_AGE_MIN = 10` exists in `src/`; the precip 90/180 ladder, CO-OPS 30 min
  and NWS 15 min are frozen in the spec and in no code. The page renders a freshness row
  PER SOURCE off a per-layer TABLE (frontend 01, D2) and has to get those numbers from
  somewhere — so name them where the page can be pointed at them. Until then the page can
  only show a bare AGE with no FRESH/STALE verdict, which is what frontend 02 had to build:
  it added a fifth chip, **AGE** (age known, no budget frozen). Counted off the running
  page: the map has **9 sources**, the repo's two frozen constants cover **3** of them, and
  the other **6 are in that state**.
- [ ] **NAME your three export files and their keys in the close-out.** Both specs describe
  them in prose only ("all Cells as geometry; point Units only at ELEVATED+; the truth
  payload"); nothing in the tree freezes a filename or a field. You are free to choose — and
  you are the one who freezes it, because the map's layer table is written against them.

Nothing here changes the two-meta-file MUST inherited from frontend 01; it sits beside it.


## Inherited from flood 10's build (2026-08-24, branch `flood10-exposure-artifact`)

`gold/flood_exposure` and `research/flood-10-coefficients.json` both exist. Two things on
this ticket's list are now settled by measurement rather than left to the panel:

- **`score_index` is real and bounded (0, 1]** — the within-kind empirical CDF of `score_ref`,
  one row per Unit, 15,166 rows, NO NULLS. That is your dormant-weather static view. The
  matching CDF knots are published in the coefficient JSON under `cdf.by_kind.<kind>`, so the
  panel can place a score on the same curve without reading the Gold table.
- **A score is the LINEAR PREDICTOR, not a probability, and it is NEGATIVE for almost every
  Unit** (real-root ranges: bus_stop -7.39..-3.91, complex -6.54..-4.12, cell -5.27..+1.06).
  **Never render a raw score.** Render `score_index`, or the live rank. A raw eta on a panel
  reads as a broken number, and printing it would also be the calibration claim the honesty
  strings exist to prevent.
- **Your per-kind legends have a fourth thing to say: `flags`.** A closed vocabulary, never
  NULL, empty for 14,726 of 15,166 rows: `elev_ring15_fallback` (36) · `no_dem_footprint`
  (60 — outside the NYC DEM, scored at the kind median, NOT an imputed elevation) ·
  `no_matrix_row` (0 here) · `score_fallback_kind_median` (60) · `no_surge_margin` (404 —
  NULL margin, never a zero). Every flag's own one-line explanation ships in the coefficient
  JSON under `flags`, so the panel can label a fallback row from the artifact it already
  loads rather than inventing wording. **A fallback row must not be presented as a modelled
  rank**; it is the kind's median with a reason attached.
- **`surge_margin_ft` is NULL for 404 Units and that is data, not a hole.** 344 Cells have no
  point child (they are scored through a taxi Zone) and 60 bus stops have no elevation at all.
  Render the absence, never a zero.
- **NO COMPLEX-GRAIN SKILL CLAIM anywhere on the panel.** A complex's number is the MAX over
  its child entrance scores — an aggregate of doorway scores. The independent complex-grain
  set caught 1 of 118 positives, so the strings say what the number IS, never what it was
  proven to do. The coefficient JSON carries no performance metric of any grain (asserted).
- **Version skew (your bullet 17) has a concrete comparison now.** `score_version` is stamped
  on every row of `gold/flood_exposure`, in its parquet footer as `b"score_version"`, and at
  the top of the coefficient JSON. Compare the artifact against the TABLE you actually read.
  It moves only when a published score can move — a reworded flag or a changed scale-band note
  does not bump it, so a refusal means something real.
- **`gate.panel_strings` is pre-selected in the coefficient JSON** (branch MODEL: headline
  "modelled flood exposure", release "v1 ships the fitted L2 logistic exposure score", caveat
  "fitted on reported flooding, 2010-2025 rain events"). The B2-branch alternates in your
  bullet 16 are therefore NOT the live branch; read `gate.branch` rather than choosing.
