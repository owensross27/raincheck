# 12 — End-to-end rehearsal

**What to build:** One command drives a flood from detector state to a rendered message to
an empty subscriber store, twice — once on a synthetic event built to trip every branch,
once on the real 2023-09-29 event — so the first real storm is not the rehearsal. Spec:
section 10.

**Blocked by:** 10, 11.

**Status:** done

- [x] one make target drives: fixture detector state -> tier entry -> notify decision -> message render -> dry-run send -> unsubscribe token -> empty store. Repeatable, no network, no real subscriber — `make notify-rehearse` (`python -m raincheck.notify_rehearse`; `SYNTH=1` runs the rootless half alone)
- [x] the synthetic event trips entry, hold, INSUFFICIENT_DATA, the winter gate, quiet hours and the per-subscriber cap — plus WINDOW_CAPPED (the one synthetic-only state) and version skew; see DONE
- [x] the 2023-09-29 event replays through the detector's own walk, not a hand-built state — `notify_replay.inputs` + `notify_replay.replay`, all six chains equal the committed notify-11 row
- [x] the rehearsal asserts message counts and rendered strings; mail transport is NOT asserted — transport is exercised once by hand when the notifier is armed, and that is a HITL step
- [x] re-running it after any change costs one command

## FROM notify 08 (2026-08-25, branch `notify08-decision`) — THE DECISION FUNCTION EXISTS

The synthetic fixture has to trip EVERY branch, and this is the list of branches that
exist, with the shape each one needs:

- tier ENTRY fires; the same tier held fires nothing; a Window roll re-arms (roll it by
  swapping `score_version` — `nd.window_id` is `anchor|score_version|detector_version`);
- ELEVATED with `elevated_optin` 1 sends and with 0 is silent; HIGH sends either way;
- watch mode fires once per (unit, window) and not per cycle;
- silent: version skew (including an ABSENT `table_score_version`), INSUFFICIENT_DATA,
  WINDOW_CAPPED, the winter gate;
- quiet hours: HIGH sends, everything else DROPS and is logged — and the drop is not
  delivered late on the next cycle;
- the per-handle cap and the per-cycle fuse both clip and both log.

Two fixture traps this ticket already paid for, so you do not have to:

- **A four-stop vector cannot produce an ELEVATED** — the top 10% and the top 2% of four
  Units are the same Unit — so an ELEVATED case is built by re-tiering a REAL cycle
  payload (`tests/test_notify_decide.py::_retier`), never by inventing one.
- **Pin a clock where UTC and New York DISAGREE.** 16:00Z/12:00 NY and 06:00Z/02:00 NY
  give the same quiet-hours verdict in both zones, so a suite pinned only on those cannot
  see a timezone bug; 01:00Z = 21:00 NY can.

The rehearsal's own end state is unchanged: `ns.unsubscribe(con, token)` then a SQL
read-back of `subscriptions` (0 rows) against a throwaway db — the token in every message
is `Message.unsubscribe_token`, the handle's own.

## FROM notify 09 (2026-08-26, branch `notify09-message-render`, `d9e2e0a`) — THE STRINGS YOU ASSERT

The rehearsal asserts the message COUNT and the rendered STRINGS. Here is the frozen list,
and the rule that governs all of it: **every CLAIM in a rendered message is READ from the
two committed artifacts through `flood_panel.strings(det, art)`, so assert against THAT
call (or against the artifact JSON), never against a string you type into the rehearsal.**
`nr.strings()` returns exactly that dict.

**How to get the text at all:**

    body = nr.render(m, panel_url=..., unsubscribe_to=...)          # -> bytes
    text = email.message_from_bytes(body, policy=email.policy.SMTP).get_content()

**THE LIST, every entry present in every rendered message unless marked:**

1. `flood_panel.OPERATING_TRUTH` — VERBATIM, and the independent side is
   `release_check.frozen_string()` (notify 01's own ticket file), which is what
   `make release-check` compares against. `x in render(x)` is a mirror-pin; do not write one.
2. `det["estimand"]` (`flooded_reported`) and `det["estimand_note"]`.
3. `det["display"]["within_cell"]` and `det["display"]["cutpoint_basis"]`.
4. `det["display"]["window_interval"]` (`(anchor, now]`), with `m.anchor` and
   `m.now.isoformat()` under it.
5. `art["gate"]["panel_strings"]` — all three of `headline`, `release`, `caveat`,
   PRE-SELECTED by flood 10's gate. Never choose between the alternates.
6. `m.no_skill_claim` — **on exactly the complex-grain messages and NOWHERE else.** It is
   on the MESSAGE, not looked up by kind, so a rehearsal that asserts it by kind is
   asserting a different rule than the one that ships.
7. `det["cutpoints_note"]` — **only where a tier is claimed** (the tier branch). Absent
   from a watch message, and asserted absent.
8. `m.score_version`, `m.detector_version`, `m.window_id`, `m.unsubscribe_token`,
   `m.asset_id`.
9. `nr.HANDLER` = `notify_store.unsubscribe(con, token)`, plus `not instant` and
   `not one-click`.

**THE ABSENCES, which are half the rehearsal:**

- **The retired claim, and the test for it is a TRAP.** The string exists NOWHERE in the
  repo, so a rehearsal that QUOTES it becomes the grep hit that fails `make release-check`
  row 5. **Build the needle at runtime from fragments** and prove it is the right sentence
  against `release_check.RETIRED` (a regex, for this same reason).
  `tests/test_notify_render.py::_needle` is the working shape — copy it.
- **The word `None` appears in no rendered message.** `m.tier` is `None` on the branch that
  ships; this row is what catches a headline that read it.
- **`display.cutpoints_confirmed_by`** ("flood-build ticket 12") is AUDIT and must not
  reach a subscriber — printing it reads as a confirmation that has not happened.
- **No second-scale urgency**: `1-2 min`, `minute`, `second`, `live now`, `as it happens`,
  `immediately`.
- **No observed water**: `water was observed`, `we observed`, `is flooded`, `is flooding`,
  `observed flooding`. **Write the barred list AROUND the frozen string** — notify 01's
  sentence contains `an observation of water`, so a naive grep for that phrase fails on the
  honesty string itself.
- **No `List-Unsubscribe-Post` header** (RFC 8058 one-click; v1's removal is an operator
  running a function).

**ONE STRING ON F15's LIST HAS NO VERBATIM TO REUSE — do not assert it.** The
reporting-propensity sentence exists in NO module and NO artifact (measured 2026-08-26:
`grep -rn 'propensity|report more|rank higher for that reason' src/ research/*.json web/`
returns nothing). It lives only in the two flood specs' claims bullets, written with an
ellipsis. notify 09 deliberately did not invent it — a message must not be the only
surface in the project making a claim the panel does not make.

## FROM notify 11 (2026-08-26, branch `notify11-f12-subset-replay`) — THE FIXTURE SHAPES AND THE BRANCH LIST

**THE BRANCH LIST, MEASURED RATHER THAN LISTED.** notify 11 replayed BOTH branches over
flood 12's 133-event subset by building two policies from the artifact —
`nd.policy(det)` and `nd.policy(dict(det, cutpoints=dict(det["cutpoints"],
provisional=False)))` — and running one `nd.decide` chain per branch off ONE `fd.cycle`
chain. **That is how your rehearsal reaches the branch that is not shipping: flip
`cutpoints.provisional` on a COPY of `fd.constants()` and ask `nd.policy` again. Never
construct a `Policy(branch=...)`; `decide()` refuses a Policy that did not come from
`nd.policy(det)`.** The live branch is still `watch`.

**FOUR OF YOUR SIX SYNTHETIC BRANCHES ARE REACHABLE FROM A REAL HISTORICAL EVENT and two
are not — measured, so you do not have to discover it:**

- **entry / hold / Window roll** — reachable. A real event's cycles produce entries and
  holds on their own, and a multi-day event ROLLS its Window mid-storm (the city dries and
  the storm returns), which re-arms the dedupe with no artifact swap. `notify-11-replay
  .json`'s `over_expectation` rows under `more_than_one_message_per_subscription` are
  exactly the events where that happened; take your roll fixture from one of them rather
  than from a `score_version` swap, which tests the key and not the walk.
- **INSUFFICIENT_DATA** — reachable: 76 of flood 12's 4,326 cycles are that state, and
  `nd.silent()` renders them as `insufficient_data` on every chain.
- **quiet hours** — reachable, and on the WATCH branch it is not an edge case at all:
  `Message.tier` is None there, so `urgent` is False for EVERY message and quiet hours
  suppress ALL of them. A watch-branch storm that peaks between 22:00 and 07:00 New York
  sends nothing.
- **the per-cycle fuse** — reachable ONLY with a list whose members are the Units the rank
  puts on top (`notify_replay`'s `top_scored` cohort, picked off `gold/flood_exposure`'s
  `score_index`). An arbitrary list cannot reach it; see the MUST on notify 10.
- **the winter gate** — reachable, and not rare: **267 of the 4,326 cycles were
  winter-suppressed** and `nd.silent()` renders every one as `winter_gate`. (The replay
  substitutes the citywide AORC median temperature for flood 14's KNYC reading, which has
  no history on this root — the gate stays observation-derived, but a rehearsal that wants
  the LIVE observation still has to inject one.)
- **WINDOW_CAPPED** — **NOT reachable from history: flood 12 measured ZERO capped cycles in
  4,326, and this replay's silent-cycle table confirms zero on every chain.** It is the one
  detector state that has to be synthetic.
- **the per-handle cap** — **structurally unreachable on the watch branch**, and this is
  arithmetic, not a gap in the fixture. See the MUST on notify 10; your rehearsal has to
  build it with an escalation on the TIER branch or with a `per_handle_event_cap` override.

**THE SUBSCRIPTION FIXTURE SHAPE, and it is the store's or `decide()` raises.** Exactly
`ns.COLUMNS` in order, `state` = `ns.STATES[0]`, `asset_kind` in `ns.KINDS`,
`elevated_optin` in (0, 1). `notify_replay.subscribers(rows, handles)` builds them from
`[(asset_id, kind), ...]` round-robin and REFUSES a list that puts more than
`ns.MAX_PER_HANDLE` rows on one handle — reuse it rather than hand-shaping dicts. Its
handles are `sub<NN>@replay.invalid` (RFC 2606 `.invalid`, which can never resolve to a
real mailbox); do the same, and keep handles out of any published artifact — every number
notify 11 publishes comes from `Decision.summary()` or `Message.asset_kind`.

**THE 2023-09-29 EVENT YOUR LINE NAMES IS IN THE SUBSET** and it replays through the
detector's own walk with no hand-built state: `notify_replay.inputs(con, root, ev)`
returns `(wet, temp, by_hour, units)` for one event exactly as flood 12 reads them, and
`notify_replay.replay(ev, wet, temp, by_hour, us, art, det, score_version, chains)`
walks it. Both are two lines from a rehearsal.

**NAMES, so this file does not end up with two `nr`s:** notify 09 ships
`raincheck.notify_render` and this ticket ships `raincheck.notify_replay`. Both read
naturally as `nr`. Spell them out here — every module name in this block is written in
full for that reason.

## FROM notify 10 (2026-08-26, branch `notify10-dry-run`) — THE DRY-RUN IS IN THE LOOP; ITS STATE IS WHAT YOU REHEARSE AGAINST

Module names spelled in full throughout (this file already holds two `nr`s).

**THE SEAM.** `live_loop.cycle()` now calls, after the flood tick and with the same
clock:

    notify = raincheck.notify_dryrun.dryrun(root, state.get("notify"), flood, now)

ONE call, ONE `state` field (`notify`), flood 15's join shape — and the function is
named `dryrun`, not `tick`, because flood 17's AST test allows `cycle()` at most one
`.tick(` call. flood-build 20 is the other wave-8 editor of that file; the gate re-runs
`tests/test_live_loop.py` on the union.

**THE STATE SHAPE (`state["notify"]`), the loop's own record of what would have gone
out — nothing is published, so no page and no payload carries this; the loop state and
the on-change log line are the ONLY surfaces:**

    at                 datetime — the cycle's clock
    decided            bool — a fresh flood read was decided this cycle
    why                None | "flood_error" | "flood_skipped" | "no_read" (carry cycles)
    d                  the chained `raincheck.notify_decide.Decision` (next cycle's prev;
                       carried UNTOUCHED through carry cycles and through errors)
    summary            d.summary() — counts only: {branch, reason, window_id, messages,
                       drops, dropped{reason: n}, worst_case}
    rendered           int — messages `raincheck.notify_render.render(m)` rendered
    unrendered         int — messages it REFUSED (today: ALL of them, PANEL_URL/
                       UNSUBSCRIBE_TO unset — the tripwire facts; that is the correct
                       tree outcome, not a defect)
    unrendered_reason  first refusal, "ValueError: ..." truncated
    error              a decide()/store failure as text, or None — never a raise
    con                the store's sqlite3 connection, opened once, carried (internal)

**WHAT A REHEARSAL CAN LEAN ON, pinned by `tests/test_notify_dryrun.py` and a 10/10
mutation round:** the decision runs ONLY on a fresh read (skipped/errored/readless flood
cycles carry `d` and never touch the store — `live/subscriptions.db` is not even
created); the same `now` reaches `raincheck.notify_decide.decide` as reached the flood
tick (`Message.now` equals the loop clock); a DROP is never rendered; a decide refusal
(inconsistent store row) lands in `error` with the previous `d` carried; the log line
prints on summary CHANGE only, counts only, and ends `NOT SENT (dry-run)`. There is no
send path and no credential path — an AST test pins the imports and the attribute calls,
so "arming" the notifier is a new capability, not a flag flip. A night rehearsal that
drops everything on quiet_hours is CORRECT (notify 11's MUST 4).

**FROM flood-build 20 (2026-08-26, branch `floodbuild20-design-storm`) — the flood tick's
state gained one field a rehearsal will see.** `flood_panel.tick`'s returned state now
carries `design_storm: {cells: <n raining scored-grid Cells>, max_mm_1h?: <2dp>}` and the
one log line per tick ends `... ds=<n>[@<max>]` (module `raincheck.design_storm`; the
payload side is `flood.json`'s top-level `design_storm` block + per-Cell `{mm_1h,
bracket?}`, shape frozen on frontend 08's file and summary line). Nothing notify-side
reads it — `nd.decide`/the renderer never see a design-storm number — so a rehearsal
asserts at most that the field exists and the line renders; `live_loop.py` is untouched
and the wave-8 `cycle()` union is notify 10's alone.

## DONE 2026-08-27 — branch `notify12-rehearsal` (the WAVE 9 GATE's P1 row reads this section)

**What shipped:** `make notify-rehearse` -> `python -m raincheck.notify_rehearse`
(`src/raincheck/notify_rehearse.py`; `SYNTH=1` runs the rootless half alone) +
`tests/test_notify_rehearse.py` (+17 tests, nothing parametrized) + the Makefile target.
The rehearsal EDITS none of the chain it drives — `notify_store` / `notify_decide` /
`raincheck.notify_render` / `raincheck.notify_replay` / `flood_detect` are called, never
touched (module names spelled in full; neither `nr` module is ever aliased, and a test
enforces that for both rehearsal files). Every expectation is a printed PASS/FAIL row,
`release_check`'s shape; rc 1 if any row fails.

**WHAT THE REHEARSAL PROVES (measured 2026-08-27, `make notify-rehearse` = 72/72 rows,
31.7 s; 42 synthetic + 30 real):**

- **Synthetic half (no data root, real `fd.cycle` payloads over the committed Ida
  fixture; the only hand-edits are `_retier` and the WINDOW_CAPPED state):** entry + hold
  on BOTH branches (both policies from the artifact via the provisional flip on a copy —
  no hand-built Policy, pinned by test) · ELEVATED sends with `elevated_optin` 1 and is
  silent at 0 · HIGH sends either way · quiet hours DROP an ELEVATED and every watch
  message (tier None -> nothing urgent), never deliver late, never suppress HIGH, and are
  pinned at DUSK (01:00 UTC = 21:00 NY) where the two clocks disagree · version skew is
  silent on a skewed AND an absent table stamp · INSUFFICIENT_DATA silent ·
  winter gate silent with every rank surviving (the payload-side trap re-checked) ·
  **WINDOW_CAPPED silent — the ONE synthetic-only state (0 of 4,326 real cycles, flood 12
  and notify 11 both measured zero), so it is the one hand-edited payload** · **the
  per-handle cap clips a TIER-branch ELEVATED -> HIGH escalation** (cap overridden to 1
  via `nd.policy(..., per_handle_event_cap=1)`; structurally unreachable on watch, and
  the fixture cannot hold ten entering Units on one handle — notify 11's arithmetic).
- **Real half (the detector's own walk, no hand-built state):** `notify_replay.inputs` +
  `notify_replay.replay` over **2023-09-29** AND the Window-ROLL event **2025-12-19**,
  picked at runtime from the committed replay's own over-expectation rows (`windows` > 1
  — a real mid-storm roll, the city dried and the storm returned; NEVER a `score_version`
  swap). **All SIX chains (three cohorts x both branches) on BOTH events reproduce the
  committed `research/notify-11-replay.json` rows EXACTLY** — today's tree makes the same
  decisions notify 11 recorded, which is the "first real storm is not the rehearsal"
  claim in measured form. A message-keeping copy of the replay loop folds to tallies
  identical to `notify_replay.replay`'s on every chain (so the rendered messages come
  from the same walk). **The per-cycle fuse CLIPS on `top_scored/tier`: 21 `cycle_fuse`
  drops on 2023-09-29, equal to the committed row** — the top_scored cohort is the only
  list that can ask it (notify 11's MUST, honoured). Quiet-hours drops appear on the live
  chain; the roll event shows 2 Windows on every chain; every live-branch message carries
  `tier: None`.
- **Strings (11 messages rendered: synthetic watch bus/complex + tier ELEVATED/HIGH;
  real watch x4 + tier ELEVATED/HIGH/complex; explicit `panel_url=`/`unsubscribe_to=`
  kwargs, `.invalid` values):** the nine PRESENT items read from
  `notify_render.strings()` / the artifacts (frozen operating-truth string == 
  `release_check.frozen_string()`, 254 chars, unfolded in the bytes) · the CONDITIONALS
  on the MESSAGE, not the kind (`no_skill_claim` rides exactly the carrying messages;
  `cutpoints_note` only where a tier is claimed) · the ABSENCES: the retired claim via a
  runtime-assembled needle proved against `release_check.RETIRED` (release-check re-run
  on the committed tree: **15/15 rows**, row 5 clean with both rehearsal files tracked) ·
  the word `None` · `display.cutpoints_confirmed_by` · second-scale urgency · observed
  water, with the barred list written AROUND the frozen string and a row proving the two
  do not collide · no `List-Unsubscribe-Post` header. **The reporting-propensity sentence
  is asserted NOWHERE, on purpose** — it exists in no module and no artifact.
- **The store:** fixture rows from `notify_replay.subscribers` (`.invalid` handles,
  exactly `ns.COLUMNS`) inserted into a throwaway SQLite store, read back unchanged,
  decided against, and **drained to ZERO rows through `notify_store.unsubscribe`** with
  the tokens the messages themselves carry (message tokens first, the operator's sweep
  for unmessaged handles after): 4 rows synthetic, 25 rows real, `SELECT count(*)` == 0
  both times.
- **Tripwires held:** `notify_render.PANEL_URL` / `UNSUBSCRIBE_TO` are still None and
  asserted so AFTER rendering; nothing sends (AST-pinned: no smtplib/socket/subprocess
  bound in the module).
- **Harness falsifiability:** a canary test injects a violating corpus through `_open`'s
  seam and requires >= 4 rows to flip red; a 4-mutant probe (chain break in the walk ·
  drain sweep deleted · every string rule neutered · wrong needle fragment) was **4/4
  killed with pristine 17/17 green before and after** — first attempt disclosed: two
  probe harnesses accidentally ran CONCURRENTLY over one worktree and confounded each
  other's attribution (a pytest run imports the module once at collection, so a restore
  mid-run does not undo a loaded mutant); every mutant was re-run SOLO and the solo
  numbers are the ones above.

**WHAT IT DELIBERATELY DOES NOT PROVE:**

- **Transport.** Nothing opens a socket and nothing sends; mail is exercised once BY
  HAND when the notifier is armed, and that HITL arming step does not exist yet (no
  ticket, no send path, no credential path — notify 10's AST pin unchanged).
- **Arming.** The dry-run refusal on the unset deployment facts is still the tree's
  outcome (notify 10); this rehearsal renders only via explicit kwargs and sets nothing.
- **The loop seam.** `live_loop.cycle()` / `notify_dryrun.dryrun` are notify 10's,
  pinned by its own tests; the rehearsal drives the same `nd.decide` / 
  `raincheck.notify_render.render` those call. fb20's `design_storm` field lives in
  `flood_panel.tick` state, which the rehearsal never touches — nothing notify-side
  reads it, and nothing here asserts it.

**Numbers for the gate:** branch `notify12-rehearsal`, commits `cce91fb` (feat) + docs;
test delta **+17** (`def test_` 0 -> 17 in the new file; no other test file touched;
`test_notify_decide` + `test_notify_render` re-run green, 130 passed). **Skips: the two
real-half tests skip off-root (join the existing worktree off-root family); on the main
checkout they RUN** (the skip is keyed on part files under the resolved root, never on
the env var — flood-build 21a's rule). `make -n notify-rehearse` renders; re-run cost is
one command.
