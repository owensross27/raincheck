# 14 — Truth tiers: coastal gauges and the winter-gate fetch

**What to build:** The coastal live tier — three tide gauges observed and forecast against the same frozen
threshold family as the static layer — and the Central Park observation fetch the winter gate
reads. Spec: Real-time detector (coastal live, winter gate); Testing seam 2.

**Blocked by:** 07

**Status:** resolved 2026-08-24

- [x] the three gauges' 6-min observations read in NAVD88 directly (labelled preliminary); margin computed against ticket 07's frozen threshold family (asserted equal — one constants family, two consumers); the Kings Point NWS/NOS inversion honored
- [x] forecast: harmonic next high tides over a FORWARD window — begin_date + range in the query (a bare range parameter returns the PAST N hours); the exact query strings are frozen constants — plus a 30–60 min mean anomaly persisted only onto highs within 12 h
- [x] chips: QUIET / APPROACHING (within 1.0 ft of minor) / EXCEEDING, next high tide with anomaly shown; gauge outage is its own chip state, never silence
- [x] the data side of asset recoloring: Units assigned to an APPROACHING-or-worse gauge carry their static surge margin for the panel to recolor by (rendering lands in ticket 15)
- [x] the winter-gate fetch: one Central Park (KNYC) observation per cycle from the frozen NWS endpoint, feeding ticket 11's pure winter-gate function; endpoints are frozen constants, not discovery (measured on wayfinder ticket 10: the /points endpoint 301-redirects on coordinate precision — follow redirects)
- [x] parsers tested on captured fixture responses — no network in tests; a fixture asserting the forward-vs-past range semantics

## Comments

**2026-08-24 (resolution).** `src/raincheck/flood_live.py` + `make flood-live`, tested in
`tests/test_flood_live.py` (39 tests, no network). Six fixtures are verbatim bodies
captured live at 2026-08-24T01:41Z: `flood_coops_obs.json`, `flood_coops_pred6.json`,
`flood_coops_hilo_forward.json`, `flood_coops_hilo_bare.json`, `flood_coops_error.json`,
`flood_nws_knyc.json`.

**Ticket 07's open question is answered by not needing an answer.** 07 left it to this
ticket to choose a rule for Kings Point, whose `action` stage is null where the Battery
and Sandy Hook publish one. The chip family never reads the action stage: APPROACHING is
`observed OR next forecast high >= minor - 1.0 ft` (the observed leg added in the review
round below), and all three gauges publish a minor stage. One rule, three gauges, no
invented value for the gauge that has none.

**One constants family, three consumers — chained, not copied.** `flood_live` imports
`GAUGES`/`STAGE`/`minor_navd88_ft` from `flood_coastal` rather than re-declaring them, so
"asserted equal" is structural. `check_shared_family()` then calls
`flood_coastal.check_shared_thresholds()`, which makes the whole line — the stage the
spine CUTS event-days on, the stage a Unit's margin is MEASURED against, the stage a live
chip is DRAWN against — one number or a failed build. A test bends the spine's copy and
watches this tier's check fail.

**Measured at build time, beyond what the ticket knew:**

1. **A CO-OPS failure is HTTP 200 with `{"error": {"message": ...}}`.** `raise_for_status`
   never fires. Every read goes through `_body()`, which raises on the error key, so an
   outage cannot arrive dressed as a healthy-but-empty gauge. The response is a fixture.
2. **The forward-vs-past semantics are now two real bodies, not an assertion about one.**
   `flood_coops_hilo_bare.json` (bare `range=36`) and `flood_coops_hilo_forward.json`
   (`begin_date=<now>&range=36`) were captured minutes apart; the test asserts every row
   of the first is in the past and every row of the second is in the future.
3. **6-min observation and 6-min prediction stamps align exactly**, so the anomaly is a
   stamp-join, never an interpolation. `range=1` (bare, i.e. BACKWARD) is the correct form
   for both — the direction trap runs the other way for the forecast only.
4. **A blank `v` is how CO-OPS emits a gap** — the stamp is present, the value is `""`.
   Read as 0.0 that would put the harbour 4.43 ft below its own minor stage.
5. **`api.weather.gov` 403s an empty User-Agent**, and `/points` 301-redirects past 4 dp
   of coordinate. Neither is exercised: nothing is discovered, the KNYC observation URL is
   a constant. The redirect is recorded so the next reader does not re-measure it.

**Two defects found by probing, fixed and pinned:**

- `anomaly()` trusted the caller's ordering. A descending series produced a **negative**
  span, which slid under the minimum-span check and would have published a mean over an
  arbitrary 11 samples. It sorts now.
- A gauge stamping **ahead** of wall clock passed the staleness check (negative age < 30
  min) and rendered as a fresh reading. FloodNet's year-2080 sensor is the precedent: a
  source's clock is not evidence of its own correctness. Outside `[-5, +30]` minutes is
  now OUTAGE with its own reason string.

**A null is never a number.** Two places where a coerced zero would be the most alarming
value the field can take, both asserted: the winter observation's `temp_c` (0.0 is below
the gate's 0.5 C cutoff, so a broken thermometer would suppress every tier on a warm day),
and `recolor()`'s pass-through of the 404 Units with no `surge_margin_ft` (07's own
warning — 0.0 places a Unit exactly at minor flood stage). Both ride through as `None`.

**`recolor()` takes the margin table, it does not read it.** `flood_coastal.unit_margins`
is passed in rather than fetched per cycle: the caller already holds it, and it changes
with the DEM epoch, not with the tide. Verified against the real table — forcing the
Battery hot selects 9,006 Units, 8 below minor, 138 with no margin, which is 07's
published Battery row exactly.

**Left for ticket 11.** The winter gate itself. This ticket supplies `temp_c` and its `qc`
flag; 11 owns the pure function and the 0.5 C cutpoint, per its own checklist.

## Review round (2026-08-24, four-lens adversarial verify)

Four lenses (criteria / correctness / contract-drift / house-style) raised 34 findings;
each faced an independent refuter that reproduced or killed it. **Six survived**, all
fixed. What survived:

1. **A forecast failure erased a live EXCEEDING observation.** All three CO-OPS reads
   shared one try block, so a timed-out hilo call greyed the gauge and took a real
   over-the-stage reading with it. Each read now fails alone: a lost forecast costs the
   next-high line, a lost observation is the OUTAGE, and the two are reported separately.
2. **The suite was green with the forward window mutated to backward.** The direction test
   exercised `fetch()` directly, never `gauge()`. A spy test now watches what `gauge()`
   itself sends — the hilo read must carry `now`, or it returns the PAST 36 h.
3. **The thin-window guard measured span, not samples.** Two readings 49 min apart cleared
   the 30-min check and published a mean-of-two as a surge residual. Both span AND count
   must now clear.
4. **A JSON null `v` raised instead of being dropped** — `str(None).strip()` is the truthy
   `"None"` that reached `float()`, greying a whole gauge over one bad sample.
5. **A naive or non-UTC `now` shifted the forward window** by the UTC offset, silently,
   from outside `gauge()`'s error handling. Every entry point normalizes to UTC now.
6. **`_iso` ran outside `winter_obs`'s try and caught only `ValueError`.** An NWS body
   whose `timestamp` is not a string raised `AttributeError` past every handler and took
   the tier down from the one line the error handling missed.

Plus two shape/consistency fixes that came in with them: the fetch-failure chip is now
built through `chip()` like every other (a consumer iterating chips no longer KeyErrors on
the failure path), and a stale Central Park reading no longer arrives labelled `ok`.

Notable refutations, accepted: an OUTAGE gauge publishing an anomaly-adjusted forecast is
arithmetically unreachable through the frozen `range=1` window; `n_below_minor`'s
`or 0` coercion is value-identical over the column's real domain; and `unitCode` is
already pinned at the fixture level.

Two further changes were made against REFUTED findings, deliberately, and are recorded as
deviations rather than fixes:

- **APPROACHING now also fires from the observation**, not the forecast alone. The
  wayfinder draft defines it as forecast-only, and the refuter was right that the code
  matched the draft — but a gauge sitting 0.02 ft under its own flood stage read QUIET
  whenever the next harmonic high happened to be low. Water already here outranks water
  coming. The ticket's own wording ("within 1.0 ft of minor") does not say forecast-only.
- **A stale Central Park reading is labelled `stale`, not `ok`.** This surfaces a real
  constants conflict for ticket 11: the spec freezes an NWS staleness budget of **15 min**,
  but KNYC reports **hourly** at :51 (measured, 24 consecutive observations). A 15-minute
  budget marks nearly every observation stale and the winter gate never fires. This module
  uses two report intervals (120 min) and says so at the constant. **Ticket 11 owns the
  detector constants artifact and must reconcile the two** — the 15 min almost certainly
  belongs to the per-cycle NWS *alerts* call, not to an hourly observation.

Also closed: ticket 07's "Open for ticket 14" is now answered on ticket 07 itself.
