# 02 — Alert-station extractor: the remove-water era

**What to build:** The cause-anchored station-name extractor extended to the live alert vocabulary and
re-measured, so MTA alert prose keeps producing label-grade station observations — and the frozen
LIVE vocabulary the panel's alert tier will filter on. Spec: Labels and the event spine (extractor
decision); Testing seam 2.

**Blocked by:** None — can start immediately

**Status:** ready-for-agent

- [ ] the anchor vocabulary extends to the "remove water from the tracks" family and the extractor scans header AND description — zero live alerts carry the legacy 'flood'/'water cond' phrasing (measured over 449,737 captured rows), and informed-entity is no shortcut (stop_id NULL in 104/104 captured water alerts)
- [ ] precision is re-measured on the remove-water family and on the archiver's parquet serialization; the gate is ≥ 0.90 to stay label-grade; the frozen-rule holdout re-runs green against both
- [ ] output is station-named alert flood events, each landing ONE observation row at the complex (entrances inherit for display only); this ticket DEFINES the alert-incident dedupe keys as frozen named constants beside the live vocabulary — the spine (ticket 04) and the live alert tier (ticket 13) consume them, they do not define them
- [ ] the live vocabulary and match rules are frozen as named constants, ready to fold into the detector constants artifact (ticket 11)
- [ ] fixture tests on captured alert rows — no network in tests, matching the decode-census precedent

---

**Claim note (2026-08-22, busy-goldstine session — orientation only, no implementation).**
Stood down at Ross's usage-limit round-up after reading the spec, verdicts, prototype and
live capture. Findings for the implementing session:

- Port target is `research/flood-02-station-prototype/matcher.py` (+ README): norm rules,
  alias table off hyphen segments, cause bridges, flags. Holdout precision 1.000 / recall
  0.778 with rules frozen; the B1 " AND "-conjunct recall candidate needs a THIRD fresh
  sample before adoption (holdout is spent).
- Live capture re-measured this session over `archive/subway_alerts` (now 1,793,172 rows;
  the ticket's 449,737 was an earlier snapshot): legacy 'flood'/'water cond' phrasing =
  0 rows on the FULL capture; water rows 410 = 24 alert_ids = 9 incidents; stop_id NULL
  in 410/410 (informed-entity no-shortcut re-confirmed).
- alert_id grammar: `lmm:alert:<event>:<update>` (e.g. 264026 across updates 26/29/30/34)
  — the incident dedupe key is the event component, mirroring the Socrata new era's
  event_id/update_number. Freeze the parse + key as the named constants this ticket owns.
- Live vocabulary family, measured verbatim: REMOVE|REMOVING|REMOVED WATER FROM THE
  TRACKS, always bridged AT/NEAR <station>. Active-vs-cleared maps cleanly: present
  forms / "What's Happening?" = active; "after we removed" / "What Happened?" = cleared.
- One physical flood mints several event ids (WTC/Chambers 2026-08: 264031 E-line,
  264043 F, 264050 B/D) — one observation row per (event, complex); cross-event merging
  is the spine's (04), not this ticket's.
- "near World Trade Center/Chambers St" slash-pair: check whether both aliases resolve
  to ONE complex in ref/assets before inventing a pair rule (likely same complex — rule
  unnecessary).
- ref/assets (flood-build 01) carries kind=station/complex rows with name, complex_id,
  daytime_routes — replaces the prototype's stations.json entirely.
- Live alert text uses current-era names (149 St-Hostos appears verbatim); FORMER_NAMES
  only matters for historic Socrata rows.
- Suggested shape: new `src/raincheck/flood_alerts.py` reading ref/assets; frozen
  constants (LIVE vocab, bridges, dedupe keys, flags); fixtures cut from captured
  parquet rows (no network, decode-census precedent); precision re-measure via a blind
  labeling pass over a stratified live sample, scored against the gate >= 0.90; the
  frozen-rule holdout re-run against the parquet serialization.

---


## 2026-08-23 — implemented (brave-davinci session)

**Landed:** `src/raincheck/flood_alerts.py`, `tests/test_flood_alerts.py`, four fixtures
under `tests/fixtures/flood_alerts_*`. The research prototype was committed as-is first
(`research/flood-02-station-prototype/`, commit 1bd4666) so the measured inputs survive.

### The correction this session had to make: alert_id is NOT a stable text key

The first pass folded captured rows on `alert_id` and measured precision 1.000. That
number was fiction. **The MTA edits `header`/`description` in place under the same
alert_id**: 14 of the 24 captured water alert_ids carry more than one distinct text, 50
distinct text revisions in all (up to 6 under one id). Folding on alert_id alone keeps
one arbitrary revision and silently drops every station named only in the others — and
the first blind labeling had also seen only one arbitrary variant per id, so truth and
prediction were wrong in the same direction.

Fixed by making the text part of the fold key (`revisions()`, keyed on
`(alert_id, header, description)`), and by **discarding the first truth set and
re-labeling blind from scratch at revision grain**. `test_alert_id_is_not_a_stable_text_key`
is the regression guard: it measures the labels the naive fold would lose.

Consequence worth carrying: the state flag flipped for most incidents once the later
revisions were read — the naive fold reported `264026`/`264031`/`264050` as still active
when their newest revision says the water was removed. Tickets 04 and 13 must key on
the revision, not the alert id.

### The second correction: routes must fold per alert_id, not per revision

Caught by the adversarial review after the first fix. Putting the text in the fold key was
right, but I also folded the ROUTE set into the same bucket — and since an in-place edit
splits an alert's informed-entity rows across revisions, each revision then saw only the
routes captured while its text was live. 12 of 50 revisions ended up with a strictly
narrower route set than their alert's union, which resolves fewer station names and
**manufactures ambiguity the alert never had**: `264026` alias "79 St" under the revision's
`{2,3}` stays ambiguous between complex 312 and 65, while the alert's real `{1,2,3}`
resolves cleanly to 312 — the truth label.

Worse, my own test blessed it: `test_every_recall_miss_is_the_ambiguity_drop` asserted each
miss was `cause and ambiguous`, which was *true* precisely because the fold had created the
ambiguity. Fixed by folding routes per `alert_id` and attaching that union to every
revision of the id. Revision-grain recall 0.870 -> 0.907, FP still 0.

### Measurements re-run on the full capture (1,929,727 subway_alerts rows)

| claim | measured 2026-08-23 |
|---|---|
| legacy 'flood' / 'water cond' phrasing | **0 rows** |
| rows whose text says WATER | 410 |
| distinct alert_ids | 24 |
| **distinct text revisions** | **50** |
| incidents (event component of alert_id) | 9 |
| `stop_id` NULL on those rows | **410/410** — informed-entity is no shortcut |
| every water revision is the remove-water family | 50/50 |

The capture grew from the claim note's 1,793,172 rows; every count above re-derived, none
inherited.

### Truth protocol (precision gate)

Two opus agents labeled all 50 revisions **blind and independently** — neither saw
extractor output, the prototype, or each other. They agreed on **50/50 revisions and all
71 (revision, station) pairs**, including the active/cleared flag. Truth station names
were resolved to complexes by hand (`complex_of` in
`tests/fixtures/flood_alerts_truth.json`): 79 St→312 (the 1 line), 149 St-Hostos→603,
World Trade Center→624, Chambers St→624, Utica Av→181. The truth file is keyed by
`(alert_id, sha1 of the text)`, so the oracle never depends on the module's own ordering
— a fold bug surfaces as a KeyError instead of as a quietly wrong score.

**Results — the gate is >= 0.90:**

| grain | TP | FP | FN | precision | recall |
|---|---|---|---|---|---|
| (alert_id, text revision, complex) | 49 | 0 | 5 | **1.000** | 0.907 |
| (event_id, complex) — the observation grain | 9 | 0 | 1 | **1.000** | 0.900 |
| frozen-rule holdout, re-run on the ported rules | 14 | 0 | 4 | **1.000** | 0.778 |

Active/cleared agreed with truth **50/50**. Holdout flags 40/40 on all three
(system_wide, footer_only, planned_work) — unchanged from the prototype's frozen-rule
numbers, so the port did not move the rules.

**All five recall misses are genuine data ambiguity, none is a rule failure** — asserted
per-miss by `test_every_recall_miss_is_the_ambiguity_drop`, which requires each lost label
to have been a cause-anchored match that failed to resolve. After the route fix the
remaining five are two real multi-complex names: "79 St" under `[4][5]` (`264044`) and
"Chambers St" under `[B][D]` (`264050`).

**Scope ceiling, stated plainly:** the live-era truth is 50 revisions and 71 pairs, but
only **5 distinct station names, 4 complexes, 9 events and ONE storm night**
(2026-08-20/21). The >= 0.90 gate is honest on that sample; it is not evidence about
vocabulary breadth, and the next captured flood should be re-measured rather than assumed
covered.

### Mutation check (the tests were verified to be able to fail)

Every guard was reverted one at a time and the suite re-run; the module was restored
byte-identical afterwards.

| mutation | result |
|---|---|
| fold on `alert_id` only (the first bug) | **5 tests red** |
| fold routes per revision instead of per alert_id (the second bug) | **4 tests red** |
| accept ambiguous matches in `observations()` | **2 tests red** |
| scan `header` only, drop `description` | **5 tests red** |
| disable the observation state precedence | **1 test red** |
| reverse it to oldest-wins | **1 test red** |
| count `n_revisions` per match instead of per sighting | **1 test red** |
| drop the `FORMER_NAMES` presence guard | **1 test red** |
| drop curly-apostrophe normalization | **1 test red** |
| drop the `TERMINAT\w* AT` blocklist | **1 test red** |
| disable `BRIDGE_BACK` | **1 test red** |
| remove the `\bAND\b` guard from `BRIDGE_FWD` | **no test moved** |
| remove the `\bAND\b` guard from `BRIDGE_AFTER_AT` | **no test moved** |

**Honest coverage gaps, left as debt rather than papered over:**

- **Neither AND guard is exercised**, and the prototype README is wrong about why. It
  claims (`research/flood-02-station-prototype/README.md`) that the three Tremont Av
  holdout misses are "blocked by the deliberate no-AND guard". They are not: `BRIDGE_FWD`'s
  connector alternation has no `AT` branch, so the gap `" AT 174 175 STS AND "` never
  fullmatches and the guard is never reached. **A future session adopting the B1
  " AND "-conjunct recall candidate must re-derive the blocker from scratch** — the
  premise it was scoped on does not hold, and no test holds the guard in place either.
  Cut the third fresh sample; do not trust the suite to catch that regression.
- `BRIDGE_BACK` fullmatches **zero times** across all 410 live rows and all 40 holdout
  rows. Only its `CLOSED` path fires, and only in one synthetic self-check string. It was
  ported verbatim and kept for the Socrata history the spine will replay, but it is
  carrying no measured weight today.
- `PLANNED` cannot fire on live data at all (it requires the literal `FLOOD`, which is 0
  rows in the live feed), and the holdout has 0 positives for both `planned_work` and
  `footer_only` — so 40/40 agreement on those two flags is what a constant-`False`
  predictor also scores. Only `system_wide` (21/40 positives) is a real flag measurement.
- The holdout's truth resolution pushes truth station names through the extractor's OWN
  alias table, so it measures cause-bridge precision, not station->complex resolution
  correctness. The live truth does not share this flaw (`complex_of` is hand-adjudicated).

### Decisions this ticket makes

1. **Ambiguity mints nothing.** A cause-anchored match that does not resolve to exactly
   ONE complex after route filtering produces no observation row. This is what buys the
   perfect precision: three stations are named "Chambers St" and two are named "79 St",
   and a `[B][D]` or `[4][5]` alert cannot say which. Cost measured exactly: 5 revision-
   grain labels, collapsing to ONE observation-grain label — `264044` "at 79 St" under
   routes {4,5}. The spine (04) recovers even that complex: event `264026` puts 79 St/312
   on the same night.
2. **Rows fold twice, on DIFFERENT keys, and both folds are load-bearing.** The text folds
   per `REVISION_KEY` because of the in-place revision above; the routes fold per
   `alert_id`, because an in-place edit splits one alert's informed-entity rows across
   revisions and a revision-local route set manufactures ambiguity. Getting either fold
   wrong is silent — both are mutation-checked.
3. **Frozen rules untouched.** `extract()` is the prototype's cause-anchor logic verbatim,
   so the holdout is a genuine re-run. The ambiguity drop lives one layer up, in
   `observations()` — new gate, old rules.
4. **The B1 " AND "-conjunct recall candidate was NOT adopted.** It still needs a third
   fresh sample and the live family gave no occasion to spend one.

### Frozen constants (ticket 11 folds these into the detector artifact)

- `LIVE_ANCHOR` — `REMOV(?:E|ES|ING|ED) WATER FROM THE TRACKS`. Three inflections
  measured; `ES` is carried defensively and has never been observed.
- `LEGACY_ANCHOR` — the Socrata-era `flood* / water condition(s) / water main break`;
  `ANCHOR` is the union, `LIVE` alone is what ticket 13's panel tier filters on.
- `BRIDGE_FWD`, `BRIDGE_BACK`, `BRIDGE_AFTER_AT`, `BETWEEN`, `SYSTEM_WIDE`, `PLANNED`,
  `FLOOD_KW`, `WORD_CANON`, `ORDINAL`, `FORMER_NAMES`.
- `CLEARED` + `state_of()` — cleared only on past tense with no ongoing removal in the
  same text; a revision naming one finished and one ongoing removal stays active
  (`264063` does exactly this). An observation takes the state of its **newest** revision.
- **Dedupe keys, which this ticket owns:** `ALERT_ID_RE` = `lmm:alert:<event>:<update>`,
  `INCIDENT_KEY = ("event_id",)` for ticket 13's one-chip-per-incident,
  `OBSERVATION_KEY = ("event_id", "complex_id")` for the spine's one row per pair, and
  `REVISION_KEY = ("alert_id", "header", "description")` — the text-identity key that
  the in-place revision above forces. `MIN_PRECISION = 0.90`.

### Observation table produced from the live capture

```
264026  312  79 St                 cleared   101 rows
264029  603  149 St-Hostos         cleared    19 rows
264031  624  World Trade Center    cleared    66 rows
264043  624  World Trade Center    cleared    61 rows
264048  181  Utica Av              active     40 rows
264050  624  World Trade Center    cleared    36 rows
264060  624  World Trade Center    cleared    20 rows
264063  181  Utica Av              cleared    15 rows
264063  624  Chambers St           cleared    15 rows
```

One physical flood mints several event ids (the WTC/Chambers night is 264031/264043/
264050/264060), so complex 624 appears under four events. Merging them is the spine's job
(04), not this ticket's — confirmed rather than assumed: `World Trade Center` and the A/C
`Chambers St` are both complex **624** in `ref/assets`, so the "near World Trade
Center/Chambers St" slash pair needs no pair rule. Note `264048` (the Utica Av incident)
ends **active** while `264063` reports Utica Av as cleared: each event carries the state
of its own newest revision, and reconciling across events is again 04's job.

### Checklist

- [x] anchor vocabulary extends to the remove-water family; header AND description scanned;
      legacy phrasing 0 rows; informed-entity no shortcut (410/410 NULL)
- [x] precision re-measured on the remove-water family and on the archiver's parquet
      serialization; 1.000 >= 0.90; frozen-rule holdout re-runs green against both
- [x] one observation row per (event, complex); dedupe keys frozen as named constants here
- [x] live vocabulary and match rules frozen as named constants
- [x] fixture tests on captured alert rows, no network

**Suite:** 244 passed / 0 failed (`make test`), of which 20 are this ticket's. The 216
baseline in the session brief was stale; this worktree branched at `c4bfdb2` with 224.

---

## 2026-08-23 — closing notes (brave-davinci session, post-landing)

Landed on master as f518f9e (prototype) + f29aa87 (module); both verified byte-identical
to the branch. Re-ran the suite on the main checkout after landing: **284 passed / 0
failed**, this ticket's 20 among them. (The orchestrator's check-in mentioned one failing
test at 282; it does not reproduce here and none of the 20 is it — if it resurfaces it is
not from this module.)

### Fixture provenance — how to recut, and what cannot be recut

The four fixtures were cut on 2026-08-23 from `<root>/archive/subway_alerts` (1,929,727
rows at the time) and `<root>/ref/assets`. Three are mechanical; the fourth is not.

- `flood_alerts_water.parquet` — every captured row whose header or description contains
  `WATER`, uppercased, written through the archiver's **own** schema construction
  (`pa.schema([(c, TYPES.get(c, pa.string())) for c in cols])` + `compression="zstd"`,
  copied from `archiver.flush`) so the gate is measured on the real serialization. Row
  order is `fetched_at, alert_id, coalesce(route_id,'')`. Columns are the archiver's 14
  (the hive `date`/`hour` keys are not included).
- `flood_alerts_stations.json` — `kind='station'` rows from `ref/assets`, ordered by
  `asset_id`: `asset_id, name, complex_id, coalesce(daytime_routes,'')`.
- `flood_alerts_holdout.json` — the prototype's `holdout_full.json` joined to
  `holdout_labels.json` by index, keeping only `affected`, `text`, `flood_stations` and
  the three flags. Source of both is `research/flood-02-station-prototype/`.
- `flood_alerts_truth.json` — **NOT mechanically reproducible.** It is a human-protocol
  artifact: two agents labeling 50 revisions blind and independently, forbidden from
  reading the module, the prototype, or each other, then checked for exact agreement on
  every revision and pair (they agreed on all 50 / all 71) and hand-adjudicated to
  complexes. Regenerating it means re-running that protocol, not running a script. Keyed
  by `(alert_id, sha1(header + "\x00" + description)[:12])`.

Recutting the first three is a few lines of DuckDB plus `pyarrow`; the working script was
scratch and deliberately not committed, because a committed builder that silently
regenerates three fixtures while the fourth needs a labeling protocol invites exactly the
mistake this ticket already made twice (measuring against a truth set that quietly no
longer matches the data).

### Debt beyond what is recorded above

1. **The stations fixture is a frozen snapshot with no drift check.** It is currently
   byte-for-byte the live registry (verified: 496 rows identical), but nothing asserts
   that. A `ref/assets` rebuild that renames or adds a station leaves the tests passing
   against the old registry — and `load_aliases()`, the production path, would then
   disagree with every measurement here. Ticket 01's key-stability contract is the natural
   place to hang a cross-check; there is none today.
2. **`measure()` and `load_aliases()` are untested.** Everything asserted here is the pure
   functions on fixtures; the DuckDB read of the archive and the read of `ref/assets` have
   no coverage. `load_aliases()` failing would be loud (the FORMER_NAMES guard raises), but
   `measure()`'s filter predicate is a hand-written SQL regex that no test exercises.
3. **`live_only=False` has no consumer.** It exists for the Socrata history the spine (04)
   will replay through the legacy anchors, and it is unexercised — deleting the whole
   filter is green. Whoever wires 04's replay is its first real caller and should test it
   there rather than trusting it.
4. **Two flaws in the holdout scorer, both latent.** It uses greedy first-fit matching, so
   one prediction can consume a truth set another needed and undercount TP (not triggered
   at FP 0). And holdout row 4 credits a TP to an **ambiguous** prediction `{152,438}` —
   the holdout is therefore scored under a looser rule than `observations()` actually
   ships, contradicting its own docstring. The frozen `(14,0,4)` is the prototype's
   comparable number, which is why it was left as-is; anyone re-deriving it should score
   under the shipped drop rule instead and expect a different, stricter figure.

None of these is load-bearing for the >= 0.90 gate, which stands on the live truth set.
They are the honest edges of it.
