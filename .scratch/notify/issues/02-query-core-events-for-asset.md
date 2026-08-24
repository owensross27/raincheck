# 02 — Query core: one entry point, events_for_asset, and the licence boundary

**What to build:** Ask the dataset for one Unit's flood history and get back a stamped,
licence-safe answer. This is the tracer bullet for the whole query path: the single entry
point every later consumer renders over, its boundary mode, its version stamps and its
typed errors, proven end to end on one query. Spec: sections 1 and 2; SEAM Q.

**Blocked by:** None in this effort — externally on flood-build 05 (`gold/flood_labels`).

**Status:** DONE 2026-08-24 (branch `notify02-query-core`)

- [x] one query entry point taking (query name, params, data root, boundary mode) and returning a JSON-able dict; `public` is the default mode, so a caller that forgets is safe
- [x] `events_for_asset` returns the Unit's attached events with their UTC windows, read from `gold/flood_labels` joined to `silver/flood_events` — it NEVER re-attaches `silver/flood_obs` to `ref/assets`, because F05 owns that join
- [x] an asset with no attached events returns an explicit empty event list with a stated reason (not an absent key, not an error); an unknown id raises `unknown_asset`
- [x] every payload carries its version stamps (assets, spine, label, plus score where one is present); an unresolvable stamp raises `version_unresolved` rather than returning an unstamped answer
- [x] no null values in any payload — an unpublishable value is an ABSENT KEY, per the repo's pure-SQL JSON convention
- [x] `public` returns per-source observation COUNTS; `local` may return the rows behind them
- [x] the fixture root contains real FloodNet, MTA-alert and subwaydata-derived rows, and the boundary test asserts `local` returns them while `public` does not — a fixture with no restricted rows fails this criterion, because the test would pass for the wrong reason
- [x] the fixture is built so that the wrong join (flood_obs to ref/assets) returns a detectably different answer than the right one
- [x] reads go through the existing DuckDB helpers (UTC session, `union_by_name`, hive keys as strings); no Spark on the read path

## Inherited from the wave-1 landing (2026-08-24, recorded by the gate)

- **Gate satisfied**: flood 05 verified at the gate (23/23 green in the 557/0/0
  suite, master `7b7bfc8`); gold/flood_labels' shape is proven, positives only,
  no `flooded` column.
- **DuckDB read-path trap (the whole ticket is a DuckDB read path)**: `rel.arrow()`
  is a LAZY RecordBatchReader on the relation's own connection — registering
  unconsumed readers back and querying them deadlocks at 0% CPU. Use `.read_all()`
  immediately or `rel.select(...).create_view(name)`; and never hold two lazy
  `rel.query("t", ...)` relations on one connection (the shared virtual name "t"
  rebinds). Full mechanism: KNOWN TRAPS in the runbook.


## Close-out (2026-08-24) — what shipped, and the calls a later ticket must honor

`src/raincheck/query.py` (SEAM Q) + `tests/test_query.py` (20 tests, 0.9 s, no Spark, no
JVM, no network). Every criterion above is green and each was mutation-checked: seven
mutants (public emits the depth · public emits the rows · no stamps · null instead of
absent · Cell as int64 · no complex rollup · a station answers like a Unit) each turned
the suite RED, so no criterion is passing on an accident.

**The exact signature.** `query(name, params, data_root=None, mode="public") -> dict`;
raises `QueryError(reason, **detail)` and nothing else. `QUERIES` is the registry a new
query name is added to — `{"events_for_asset": events_for_asset}` today, and each
implementation has the shape `fn(con, root, params, mode) -> dict` (the envelope keys
`query` / `mode` / `versions` are added by `query()`, never by the implementation).

**Payload of `events_for_asset`** (absent, never null; every value JSON-able):
`asset{asset_id,kind,name,cell,complex_id}`, `n_events`, `events[]`, `reason`
(`"no events on record"`, only when the list is empty), `versions{assets_version,
spine_version,label_version}`. Each event: `event_id, day_start, day_end, n_days,
window_start_utc, window_end_utc, event_class, flood_cause, sources[], label_support[],
event_source_counts{source: n}` — plus, in `local` only, `depth_mm`,
`event_observations[]` and (complexes) `impact{n_hours,min_service_ratio,max_gap_ratio}`.

**Decisions this ticket had to make, and why** (they bind 03/04/05/06):
- **Counts are EVENT-grain.** F05 stores a bitmask and a max depth, not per-source counts
  at the asset, and producing them at the asset would mean re-attaching `flood_obs` to
  `ref/assets` — the one join this ticket may not do. So `event_source_counts` /
  `event_observations` are the observations inside the EVENT's window, city wide, and the
  `event_` prefix is the guard against reading them as "seen at this asset". The
  asset-grain facts are `sources` (F05's `source_mix`, decoded through `fl.SOURCE_BIT`),
  `label_support` and `depth_mm`.
- **A complex answers over its child entrances** (`parent_asset_id`, `max` depth, union of
  support) — spec section 1's complex grain and story 4. Proven on `stn:409`, which owns
  no label row and inherits one event from two of its four entrances.
- **A station raises `not_a_scored_unit`** with `detail["ask"]` = its `parent_asset_id`,
  rather than answering "no events on record" — a Carrier has no history of its own and
  the false-dry answer is exactly what story 4 forbids. Ticket 03 must reuse this reason
  and this detail key for `exposure_of`.
- **Cell ids cross the boundary as H3 HEX STRINGS** (`format(cell, "x")`), never the
  int64: `613229535722209279` does not survive a JSON reader that uses doubles, and the
  hex is the same string `cell:<h3>` asset ids already carry. Ticket 04 takes Cell ids in
  this form.
- **Three reasons beyond the spec's five**: `unknown_query`, `unknown_mode`,
  `missing_param`. `REASONS` is the frozen vocabulary and `QueryError` refuses anything
  outside it.
- **`obs_near` is not registered** (ticket 04 owns it) — asking for it today raises
  `unknown_query`, not a traceback.

**Measured for ticket 05, so it does not have to guess** (real root, 60-asset sample,
2026-08-24): **7,955 assets have history**; a `public` payload is **mean 1,373 B, median
746 B, max 7,625 B** → **~10.9 MB across 7,955 files**. Bytes are the same order as
today's 2.6 MB insight surface; the FILE COUNT is the part that may be unwieldy for the
static host's sync, which is the escape the spec already names (shard by kind + H3
prefix). Wall clock is **0.115 s per call, 0.097 s of it `versions()`** — the same three
stamps every time — so a 7,955-asset export costs ~16 min unless the renderer resolves
stamps once and reuses one connection (marked `ponytail:` at the call site).

**Fixture provenance** (`tests/fixtures/notify_query_*.parquet`, 17 KB, cut from
`/Users/ross/raincheck/data` on 2026-08-24, one-off): two small REAL events (2023-08-29,
2023-11-24), every observation inside their windows (12), eleven assets, the 7 labels on
them, and complex 611's 48 real subwaydata impact hours. Nothing is synthesised — the
licence test bites on production rows: FloodNet depths 309.88 / 46.99 mm, sensor
`Q-beach-84-st-0me680`, alert `117601+117595+117596+117605:611`. The cast makes the WRONG
JOIN detectable in both directions: `bus:400081` is labelled by F05's radius from a report
in a DIFFERENT H3 cell (a cell re-attachment LOSES it), and `bus:400021` shares its cell
with an in-window report but is >100 m from it (the same re-attachment INVENTS a flood).
`test_the_wrong_join_gives_a_detectably_different_answer` asserts both memberships.

**One thing the fixture taught**: `flood_obs.text` on an `mta_alert` row is the STATION
NAME the alert named ("Times Sq-42 St"), not the alert prose — and that string is also the
complex's public `name` in `ref/assets`. So a substring sweep cannot use it as the
MTA-derived token; what `public` withholds is the alert ROW (its `<alert_ids>:<complex_id>`
source id, its timestamp, its existence), structurally, by never emitting an observation
row at all. The prose stays in the archive snapshot and reaches no payload.
