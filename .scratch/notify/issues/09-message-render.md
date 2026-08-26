# 09 — Message render and the fixed strings

**What to build:** A decided Message becomes an email a person can read, act on and leave —
one that states the hour-grain evidence behind it and claims nothing the panel does not
claim. Spec: section 7 (message content, claim strings); SEAM N.

**Blocked by:** 01, 08 — externally on flood-build 15 (the fixed-string list and constants
artifact).

**Status:** DONE 2026-08-26 (branch `notify09-message-render`, `d9e2e0a`)

- [x] rendering a Message produces: the Unit's ID and kind, the tier entered (or, on the branch that ships, the WATCH worded from `top_n`/`rank`), the Window, the hour-grain evidence sentence, the estimand sentence, a link to the panel, and the unsubscribe instruction. **DEVIATION, MEASURED: the Unit's NAME is not renderable and is not a gap.** `nd.Message` is frozen and carries no name; a name would need a `ref/assets` lookup, which would end the purity this ticket's last box demands. The `asset_id` is the identity anyway — names are NOT unique at either grain (`86 St` names SIX complexes; `bus:200163` and `bus:200173` are both `FATHER CAPODANNO BLVD/DOTY AV`, metres apart), so a name alone could not say which Unit this is [TRAPS]. If a name is ever wanted it belongs on the Message, put there by the decision, not fetched by the renderer.
- [x] F15's fixed strings are reused verbatim — read through `flood_panel.strings(det, art)`, the panel's OWN selector, so a message and the panel cannot disagree by construction. **ONE ITEM OF THIS LIST HAS NO VERBATIM TO REUSE, and it is a finding, not a skipped box: the reporting-propensity sentence does not exist as a string anywhere.** Measured 2026-08-26: `grep -rn 'propensity|report more|rank higher for that reason' src/ research/*.json web/` returns NOTHING. It lives only in the two flood specs' claims bullets, and there it is written with an ellipsis ("ranks where a flood REPORT is likely… places whose residents report more rank higher for that reason") — not a literal at all. F15 shipped `display.*` + the gate's panel strings and did not add it. So the message renders what EXISTS and does not invent it: writing the sentence here would be the message-only vocabulary this same box bars, and would make a message the only surface in the project that makes the claim. Filed forward. ORIGINAL TEXT: F15's fixed strings are reused verbatim — the reporting-propensity sentence, the estimand name `flooded_reported`, the Window in the tier label, the degraded-state strings, and the B2-branch alternates selected by the shipped model id; the message gets no vocabulary of its own
- [x] ticket 01's replacement string is used where the retired one would have gone, and the retired string appears NOWHERE in the rendered corpus. The frozen string is compared against **notify 01's own ticket file** (`release_check.frozen_string()`), never against the module that renders it — `x in render(x)` is a mirror-pin. The absence test **builds its needle at RUNTIME from fragments** and proves the needle is the right sentence against `release_check.RETIRED`, the regex the gate itself greps with; `test_the_needle_is_built_at_runtime_so_this_file_is_not_a_grep_hit` is the row that keeps this file out of the zero-hits row. `make release-check` on this tree: **15/15 rows PASS, rc 0**, row 5 still `0 hit(s)`.
- [x] the message states its evidence window in hours and never implies second-scale urgency. The Window is `(m.anchor, m.now]` labelled with `display.window_interval` read from the artifact, and a barred-word row fails on `1-2 min`, `minute`, `second`, `live now`, `as it happens`, `immediately` — with a row beside it proving the barred list can fail.
- [x] the message never claims water was observed — it says so in as many words (`no water has been observed`) and the frozen string carries the rest. The barred list here is written AROUND the frozen string, which itself contains `an observation of water`: a naive absence grep on that phrase would fail on notify 01's own sentence [TRAPS: a docstring that names what it forbids poisons a source-text grep].
- [x] every message carries the token in a `List-Unsubscribe` mailto header AND in the body. **`List-Unsubscribe-Post` is deliberately NOT set** — that header is RFC 8058 ONE-CLICK, and v1's removal is an operator running a function, so setting it would be exactly the implication the spec bars. The body names `notify_store.unsubscribe(con, token)` and the test's independent side is `inspect.signature(ns.unsubscribe)`. The message says the token is per HANDLE, removes every subscription at once, and stays valid if more are added.
- [x] render is a pure function of the Message: same Message, same bytes. No `From`, `Date` or `Message-ID` (the sender's, ticket 10's) — which is also what makes it deterministic. A parametrized row proves EVERY Message field reaches the bytes: a field the renderer ignored would make two different Messages the same email, which is how a subscriber gets somebody else's stop.

## FROM notify 08 (2026-08-25, branch `notify08-decision`) — THE DECISION FUNCTION EXISTS

You render `nd.Message`, and it is FROZEN. The decision produces no prose at all — the
only string it hands you is flood 11's own disclaimer — so every word is yours.

```python
from raincheck import flood_detect as fd
from raincheck import notify_decide as nd
from raincheck import notify_store as ns

det = fd.constants()                   # the CALLER reads the artifact; decide() opens nothing
p   = nd.policy(det)                   # -> Policy; READS `cutpoints.provisional` -> branch
subs = ns.subscriptions(con)           # ACTIVE rows, (handle, asset_id) order
cyc  = fd.cycle(state, now, cell_hours, units, art, det, ...)
d    = nd.decide(cyc, d_prev, subs, p, now)      # -> Decision; d is the next call's d_prev
for m in d.messages:                   # -> Message (frozen)
    ...
```

`Message`: `handle · asset_id · asset_kind · branch · tier · rank · top_n · window_id ·
anchor · now · unsubscribe_token · score_version · detector_version · no_skill_claim`.

**MUSTs this puts on you.**

- **`tier` IS `None` ON THE WATCH BRANCH, which is the branch shipping today** (flood 12
  recommended rank-only and `cutpoints.provisional` is still true). A renderer that reads
  `m.tier` for its headline renders `None` for every real message v1 sends. On watch,
  `m.top_n` is the N in force for that kind and `m.rank` is the within-kind rank — word it
  as a WATCH ("among the N most exposed right now"), never as a tier, and never as a
  measured depth. Where `m.tier` IS set it is a member of `fd.TIERS` and its label is
  `fd.constants()["display"]["tier_labels"][m.tier]` — read it, never re-spell it.
- **`m.no_skill_claim` is flood 11's `display.no_complex_skill_claim`, verbatim, and it is
  present on exactly the messages that owe it** (complex grain: the number is a max over
  child doorway scores and the independent complex set caught 1 of 118). Render it or you
  word a claim the artifact refuses to make. It is `None` on a bus_stop and nothing is owed.
- **The Window for the hour-grain evidence sentence is `(m.anchor, m.now]`** — the
  detector's own half-open convention. `m.anchor` is an ISO string, `m.now` the injected
  clock the decision ran at.
- `m.unsubscribe_token` is the handle's token straight off the store row — PER HANDLE and
  shared by every row that handle owns, exactly as your own summary line says.
- `m.score_version` / `m.detector_version` are the stamps the message was produced under;
  a message always says which model and which rules made it.

The frozen operating-truth string, the retired claim and the fixed-strings list are
UNCHANGED by this ticket — notify 08 renders nothing, so it retired nothing and added no
vocabulary of its own.

## FROM FLOOD 15 (2026-08-25, `flood15-panel-exports`, `5925813`) — SAME STRINGS, SAME LOOP

**THE STRINGS.** The panel now renders the frozen operating-truth string verbatim, and it
reads it from nowhere but `flood_panel.OPERATING_TRUTH`, which is notify 01's text
unedited. **Render the same object, not a paraphrase**: a message and the panel that
disagree is the failure notify 01's freeze exists to prevent. Everything else the panel
says is under `strings` in `files/flood.json` and comes from `display.*` in
`research/flood-11-detector.json` (`fd.constants()`) — `tier_labels`, `tiers`,
`window_states`, `precip_states`, `winter_label`, `winter_unknown_label`,
`no_complex_skill_claim`, `within_cell`, `cutpoint_basis` — plus `estimand`,
`estimand_note`, `tiers_provisional`, `gate_branch` and `panel` (flood 10's pre-selected
`headline` / `release` / `caveat`, branch MODEL). **`display.*` is deliberately OUTSIDE
`detector_version`**, so re-wording a label cannot roll a live Window — which only holds
while you READ them. `make release-check` fails if the honesty string stops riding on the
payloads, and it compares against notify 01's OWN ticket file rather than against the
exporter's copy (a `x in render(x)` check is a mirror-pin and passes whatever the string
becomes).

**`provisional` IS A TOP-LEVEL BOOLEAN, READ AT RENDER TIME.** flood 12 recommended
RANK-ONLY and the verdict is Ross's; while `cutpoints.provisional` is true the panel says
so, and recording the verdict bumps `detector_version` and rolls every open Window with
no code change. Branch on the flag, never on a remembered answer, and **never render a
tier as confirmed.**

**THE LOOP.** The flood tick is already inside cloud 05's 30 s loop as ONE call in
`live_loop.cycle()` and ONE field on `state` (`flood`). Join it the same way — no new
daemon, no second `python -m`:

    flood = flood_panel.tick(con, root, out_dir, state.get("flood"), now, detected)

It never raises (an outage is a field on its state), it SKIPS unless the forcing advanced
or the artifact's `throttles.floodnet_s` (120 s) expired, and it is handed the loop's own
`flood_live.live()` read so nothing re-fetches CO-OPS or KNYC at the render rate. Copy
that failure policy rather than inventing one. **The pod is limited to 768 MiB and the
loop now peaks at ~500 MiB** — if your notifier reads a table, put its projection and its
predicate INSIDE the read's own statement (`duck.table()` binds the path as a parameter
and blocks pushdown; that shape cost 5 GiB for six rows here — TRAPS).

**WHAT THE PANEL ALREADY PUBLISHES, so a message and a page cannot disagree:** the tier
per Unit and per Cell, `skew.model_tier` (a refusal is rendered, never a last-good
number), `window.state`, `staleness` per source with its budget in `budgets_s`
(seconds: precip 5400/10800, floodnet 600, coops 1800, nws_alerts 900, nws_knyc_obs
7200), `dim.dimmed` + `dry_hours`, and `winter`. Files: `files/flood.json` +
`files/flood-meta.json` (open) and `files/flood-mta.json` + `files/flood-mta-meta.json`
(GATED with `live.geojson`). The human-facing value is the RANK — never an eta, never a
probability, and `make release-check` fails if one appears.

## DONE 2026-08-26 — branch `notify09-message-render`, `d9e2e0a`, +51 tests, 14/14 mutants killed

`src/raincheck/notify_render.py` (156 lines) and `tests/test_notify_render.py`. NOTHING
else in `src/` was touched — `notify_decide.py` is byte-identical to master, so the frozen
`Message` shape is unmoved and `tests/test_notify_decide.py` needed no edit.

**THE SURFACE, which is the whole ticket:**

    from raincheck import notify_render as nr
    nr.render(m, *, panel_url: str | None = None, unsubscribe_to: str | None = None) -> bytes

One plain-text RFC 5322 message per `nd.Message`. `nr.strings()` is the claim vocabulary
(`flood_panel.strings(fd.constants(), fe.coefficients())`) if a caller wants to assert on
it; `nr.PANEL_URL` / `nr.UNSUBSCRIBE_TO` / `nr.HANDLER` are the only other names.

**EVERY CLAIM IS READ, NEVER WRITTEN.** The rendered text pulls
`estimand`, `estimand_note`, `within_cell`, `cutpoint_basis`, `window_interval`,
`tier_labels`, `tiers_provisional`, `operating_truth` and the gate's pre-selected
`panel.{headline,release,caveat}` out of `flood_panel.strings(det, art)` — the panel's own
selector — so the two surfaces cannot contradict each other and neither can be re-worded
here. The literal `"L2 logistic"` appears nowhere in the code; nor does any tier spelling.
The connective words (labels, the Window block, the unsubscribe instruction) are this
module's, and they are all this module has.

**WATCH IS THE BRANCH THAT SHIPS, AND `None` NEVER REACHES AN INBOX.**
`cutpoints.provisional` is still `true` on master, so `nd.branch(det)` is WATCH and
`m.tier` is `None` on every real message. The claim is worded from `m.top_n` and `m.rank`
("is among the 25 bus_stop units ranked most exposed right now"), explicitly `not a tier`
and `not a depth`, and a row asserts the string `None` is in NO rendered message at all.
The tier branch is rendered from `display.tier_labels[m.tier]` and is exercised by REAL
tier-branch Messages (`nd.policy` on a `provisional=False` artifact), not by a stub.
`display.cutpoints_confirmed_by` is asserted ABSENT from the corpus — it names who
confirms, it is populated already, and printing it would read as a confirmation that has
not happened.

**TWO DEPLOYMENT FACTS THIS REPO DOES NOT HOLD, so `render()` REFUSES.** There is no
public URL anywhere in the tree (the bucket + custom domain are [YOU]) and no unsubscribe
mailbox (v1 has no endpoint, spec section 9). `PANEL_URL` and `UNSUBSCRIBE_TO` are both
`None`, and a render without them raises rather than shipping a dead link and a bouncing
header — the same shape as `nd.policy()` refusing a Policy that did not come from the
artifact. A test asserts they are still unset, so nobody can quietly fill in a plausible
placeholder.

**8bit, NOT quoted-printable.** QP soft-wraps at 76 columns, which would break the frozen
operating-truth string mid-sentence IN THE BYTES — so `fp.OPERATING_TRUTH.encode() in
render(m)` is true, and a grep over the wire format finds the sentence whole. The
independent side for that string is `release_check.frozen_string()`, i.e. notify 01's own
ticket file, which is what `make release-check` compares against.

**MUTATIONS: 14 written, 14 KILLED, zero survivors**, pristine control green before and
after, every mutant proved landed by `git diff`, `PYTHONDONTWRITEBYTECODE=1`, restore by
`git checkout -- <paths> && git clean -fdq <paths>` with a clean-tree assert after each.
The fourteen: the watch branch worded as a tier · `top_n` spelled as a literal · the
no-skill claim dropped · the no-skill claim attached by KIND instead of by message (the
other direction) · the frozen string paraphrased · quoted-printable · no
`List-Unsubscribe` · `List-Unsubscribe-Post` added · the window interval spelled instead
of read · a naive clock accepted · the unconfigured refusal removed · the rank's precision
· the tier label as the raw token · the honest-processing sentence made dishonest.

**ONE TEST-HARNESS DEFECT FOUND AND FIXED BEFORE THE ROUND, worth knowing:** notify 08's
`_code()` helper strips `tokenize.STRING` to keep a docstring's prose out of a purity
grep. **Under python 3.12 an f-string is no longer a STRING token** — its literal halves
arrive as `FSTRING_MIDDLE` — so on a module whose prose is f-strings that filter keeps
every rendered sentence in the "code", and `assert "send" not in CODE` failed on the word
inside `To stop these, send this token`. Fixed here by dropping `FSTRING_*` too, with
`test_the_purity_grep_reads_code_and_not_prose` as its own oracle. Anyone copying that
helper onto an f-string-heavy module inherits the bug.

**TEST DELTA +51**, recounted by `def test_` against this branch's OWN merge base
`5dc7666`: master **1305 -> 1356**. 60 collected (one row is parametrized over ten
fields). Own-module run `test_notify_render test_notify_decide test_notify_store
test_flood_panel` = **196 passed / 5 skipped in 1.54 s**; the five skips are
`test_flood_panel`'s off-root canaries and **`tests/test_notify_render.py` alone is 60
passed / 0 skipped — it reads no data root, opens no socket and no database, so it adds
ZERO skips to the gate's decoder.** `make release-check` on this tree: 15/15, rc 0.
