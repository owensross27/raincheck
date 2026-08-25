# 03 — exposure_of and the Unit/Carrier rule

**What to build:** Ask how exposed a doorway is and get the published exposure object back
— with the Unit/Carrier distinction enforced, so nobody can ask a station for a score it
does not have. Spec: section 1 (complex grain); CONTEXT.md (Unit, Carrier); SEAM Q.

**Blocked by:** 02 — externally on flood-build 10 (`gold/flood_exposure`).

**Status:** ready-for-agent

- [ ] `exposure_of` returns score_ref, score_severe, score_index, surge_margin_ft and flags for a Unit, stamped with model_id / score_version
- [ ] a complex's answer is the max over its child entrances, matching F10's rule exactly
- [ ] a station returns `not_a_scored_unit` naming the complex to ask instead — stations are Carriers and are never scored independently
- [ ] a bus_stop and a Cell each answer directly
- [ ] no NULL score reaches a payload: F10's fallbacks guarantee coverage and reasons ride the flags
- [ ] the per-asset payload composes with 02's history — one asset, one answer, both stamped


## Inherited from notify 02 (landed 2026-08-24, branch `notify02-query-core`, 13a93ab)

**SEAM Q exists — consume it, never re-derive it.** `src/raincheck/query.py`:

    query(name, params, data_root=None, mode="public") -> dict     # THE entry point
    QUERIES = {"events_for_asset": events_for_asset}                # the registry
    fn(con, root, params, mode) -> dict                             # every implementation
    QueryError(reason, **detail)                                    # e.reason, e.detail

`query()` adds the `query` / `mode` / `versions` envelope, validates the mode (`public`
is `MODES[0]` and the default) and resolves the version stamps BEFORE any answer is
built, so an unstamped payload cannot exist. `REASONS` is the frozen error vocabulary:
the spec's five plus `unknown_query`, `unknown_mode`, `missing_param`; `QueryError`
refuses anything outside it. Helpers to reuse rather than rewrite: `pack(**kv)` (absent,
never null), `jsonable(v)`, `cell_id(int)`, `sources(source_mix)`, `holes(n)`,
`view(con, root, *parts, name=, columns=)`.

**Frozen by that landing:**
- **A Cell id crosses the boundary as its H3 HEX STRING** (`format(cell, "x")`), never
  the int64 — 613229535722209279 is past 2^53 and a JSON reader using doubles corrupts it.
- **The licence boundary is one rule**: `public` ships COUNTS and F05's attachment facts;
  `local` ships the ROWS behind them. Public emits NO observation row at all — that, not
  field filtering, is what keeps the FloodNet depths, the alert row and the subwaydata
  numbers in. Anything you add answers to the same rule.
- **Counts are EVENT-grain** (`event_source_counts`, `event_observations`): F05 stores no
  per-source counts, so an asset-grain count would mean re-attaching flood_obs to
  ref/assets, which is F05's join alone. The `event_` prefix is the guard.
- **Reads are narrowed `create_view` relations, never `rel.arrow()`** (the wave-1
  lazy-reader deadlock), and every value is a bound parameter — `holes(n)` builds
  placeholder lists, values are never formatted into SQL text.
- Fixtures: `tests/fixtures/notify_query_*.parquet` (17 KB, cut from the real tables,
  two real events, real restricted rows) assemble a whole root in `tests/test_query.py`'s
  `root` fixture — extend that fixture rather than cutting a second one.

**Your Unit/Carrier rule is already half-shipped.** `events_for_asset` raises
`QueryError("not_a_scored_unit", asset_id=..., kind=..., ask=<parent_asset_id>)` for any
kind outside `flood_labels.LABEL_KINDS` — reuse that reason and that `ask` detail key, and
reuse the complex rollup it already does (`parent_asset_id`, max depth, union of support)
instead of writing a second one. `score_version` / `model_id` join `versions()` when you
read F10's scores: today they are ABSENT (not null) because no score is read.


## Inherited from flood-build 10 (2026-08-24, branch `flood10-exposure-artifact`)

`gold/flood_exposure` EXISTS — one part file, `<root>/gold/flood_exposure/part-00000.parquet`,
**15,166 rows, one per Unit**, sorted by (kind, asset_id). Read it as a narrowed
`create_view` relation like every other query (never `rel.arrow()`).

Columns, exactly: `asset_id` · `kind` (`bus_stop`|`complex`|`cell`) · `model_id`
(`point:l2_logistic` | `cell:l2_logistic`) · `score_ref` · `score_severe` · `score_index` ·
`surge_margin_ft` · `flags` (LIST of VARCHAR) · `score_version` · `matrix_version` ·
`fits_version`.

- **Your complex rollup is ALREADY DONE — read the row, do not re-derive it.** A complex's
  score IS the max over its child entrance scores; that is what the `kind='complex'` row
  holds, computed at build and verified against an independent SQL recomputation for all 445.
  Re-doing the max in `exposure_of` would be a second implementation of a rule that has one
  home. Your `parent_asset_id` rollup from `events_for_asset` stays the right shape for the
  HISTORY half; for the SCORE half, one lookup by `asset_id` answers.
- **Entrances and stations publish NO row here** — asserted in flood 10's tests. So your
  `not_a_scored_unit` reason (reusing notify 02's `QueryError` reason and its `ask` detail
  key) fires exactly when `asset_id` is absent from this table AND the kind is a Carrier.
  Do not special-case: the table's membership IS the Unit/Carrier rule made concrete.
- **NO NULL scores, guaranteed and gated at build.** `score_ref`, `score_severe` and
  `score_index` are non-null for all 15,166 rows. `surge_margin_ft` IS nullable — 404 rows
  (344 Cells with no point child, 60 bus stops with no elevation) — and those rows carry the
  `no_surge_margin` flag. Emit it as ABSENT via notify 02's `pack(**kv)` (absent, never null),
  with the flag carrying the reason.
- **`flags` is a closed vocabulary and the reasons ride it**, exactly as your "no NULL score
  reaches a payload" bullet expects: `elev_ring15_fallback` · `no_dem_footprint` ·
  `no_matrix_row` · `score_fallback_kind_median` · `no_surge_margin`. Pass the list through;
  every flag's one-line meaning is published in `research/flood-10-coefficients.json` under
  `flags`, so a payload consumer can render it without wording anything itself. **60 bus stops
  carry a fallback score (the kind median, not a model evaluation) — a payload must not
  present those as a modelled rank.**
- **`score_version` and `model_id` are COLUMNS on the row**, so your `versions()` envelope
  reads them from the answer rather than from a side channel — and `score_version` is
  identical across every row (asserted). It also matches the top-level `score_version` in the
  coefficient JSON, which is how a stale read is detected.
- **A score is the LINEAR PREDICTOR (eta), not a probability**, and it is negative for nearly
  every Unit (bus_stop -7.39..-3.91, complex -6.54..-4.12, cell -5.27..+1.06). Ship
  `score_index` (the within-kind percentile, bounded (0, 1]) as the human-facing number;
  `score_ref`/`score_severe` travel as the raw model output they are.
- **NO COMPLEX-GRAIN SKILL CLAIM in any payload or docstring.** The complex number is an
  aggregate of doorway scores; the independent complex set caught 1 of 118 positives.
- **A Cell's `asset_id` is `cell:<h3 hex>`** and already matches notify 02's frozen hex-string
  boundary rule — no int64 crosses anything.

## From frontend 06's landing (2026-08-25, `frontend06-discovery-contract`, `8bd82db`) — your stamps reach a PUBLISHED document

`query.versions(con, root)`'s own docstring names this ticket: "`score_version` /
`model_id` join this when F10's scores are read (ticket 03), which is why score is absent
here rather than null." What changed underneath that sentence is that `versions()` now has
a **second consumer on the public read surface**: `src/raincheck/contract.py`'s `index()`
calls it to stamp `files/index.json`, the discovery document written by the same
`make export` run as the insight trio and published LAST in the `insight` family.

So the moment you add `score_version` / `model_id` to `versions()`, the published
`index.json` carries them too. Three consequences:

- **No `contract.CONTRACT` bump is owed.** `contract.PROMISE[1]` freezes a set of
  `(family, key, content type)` triples — the discoverable SURFACE — not payload internals.
  Adding keys inside a document that is already promised does not break the subset check.
  (The contract's own named limit says exactly this: it cannot see payload-internal
  changes, which is why every key carries a `schema` pointer instead.)
- **Keep the ABSENT-never-null convention.** An unresolvable stamp is a MISSING key beside
  a reason, never a null — `index.json` renders that as `versions_unresolved`, and a
  consumer refuses on the missing key rather than reading a placeholder. Do not introduce a
  null-valued stamp to make a shape uniform.
- **No wall clock.** `index.json` and the per-asset history payloads are both required to
  re-export byte-identically; a stamp resolved from a clock would break both.

Read `docs/read-api-contract.md` before changing the shape of `versions()` — it is the
written contract that document is published under, and its stamps paragraph describes
exactly these keys. Your own cost MUST (resolve the stamps ONCE and reuse one connection —
`query()` re-resolves them on every call, 0.097 s of a 0.115 s call) is unchanged and
unaffected by any of this.
