# 12 — End-to-end rehearsal

**What to build:** One command drives a flood from detector state to a rendered message to
an empty subscriber store, twice — once on a synthetic event built to trip every branch,
once on the real 2023-09-29 event — so the first real storm is not the rehearsal. Spec:
section 10.

**Blocked by:** 10, 11.

**Status:** ready-for-agent

- [ ] one make target drives: fixture detector state -> tier entry -> notify decision -> message render -> dry-run send -> unsubscribe token -> empty store. Repeatable, no network, no real subscriber
- [ ] the synthetic event trips entry, hold, INSUFFICIENT_DATA, the winter gate, quiet hours and the per-subscriber cap
- [ ] the 2023-09-29 event replays through the detector's own walk, not a hand-built state
- [ ] the rehearsal asserts message counts and rendered strings; mail transport is NOT asserted — transport is exercised once by hand when the notifier is armed, and that is a HITL step
- [ ] re-running it after any change costs one command

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
