"""Notify ticket 12 (spec section 10): the END-TO-END REHEARSAL, so the first real storm
is not the rehearsal. ONE command drives a flood from detector state to rendered messages
to an empty subscriber store, TWICE — once on a synthetic event built to trip every
branch, once on the real 2023-09-29 event through the detector's own walk — and every
expectation is a printed PASS/FAIL row, `release_check`'s own shape.

WHAT THE TWO HALVES EACH PROVE, and the split is MEASURED, not invented (notify 11
replayed both branches over 133 events / 4,326 cycles and counted which states history
reaches):

  * SYNTHETIC (no data root): real `fd.cycle` output over flood 11's committed Ida
    fixture, re-tiered or state-edited only where the fixture cannot reach a case on its
    own. Trips: entry and hold on both branches, ELEVATED with and without the opt-in,
    HIGH either way, quiet hours (dropped, never deferred, HIGH exempt, and at an instant
    where the UTC and New York clocks DISAGREE), version skew including an absent table
    stamp, INSUFFICIENT_DATA, the winter gate, WINDOW_CAPPED — the one state history
    never produced (0 of 4,326 cycles), so it is the one hand-edited payload here — and
    the per-handle cap, which is structurally unreachable on the watch branch and is
    built the only way it can be: an ELEVATED -> HIGH escalation on the TIER branch.
  * REAL (data root): the named 2023-09-29 event plus a Window-ROLL event picked off the
    committed replay's own over-expectation rows (a real mid-storm roll, never a
    `score_version` swap), through `notify_replay.inputs` and `notify_replay.replay` —
    the detector's own walk, no hand-built state. Every chain's counts must equal the
    committed `research/notify-11-replay.json` row for that event, which is what makes
    this a rehearsal against recorded history rather than a second measurement. The
    per-cycle fuse clip rides here, on the `top_scored` cohort — the only list that can
    reach it.

EVERY ASSERTED STRING IS READ, NEVER TYPED: claims come through
`notify_render.strings()` (the panel's own selector) and the two committed artifacts;
the frozen operating-truth string's independent side is `release_check.frozen_string()`;
the retired claim's needle is BUILT AT RUNTIME from fragments and proved against
`release_check.RETIRED`, so this file is not the grep hit that fails release-check row 5.
The barred observed-water list is written AROUND the frozen string, which itself contains
the words "an observation of water".

NOTHING IS SENT AND NO REAL SUBSCRIBER EXISTS: handles are RFC 2606 `.invalid`, rendering
uses explicit keyword arguments (`notify_render.PANEL_URL` / `UNSUBSCRIBE_TO` stay None —
the [YOU]-gated tripwire facts, asserted still unset here), the store is a throwaway
SQLite file drained to ZERO rows through `notify_store.unsubscribe` with the tokens the
messages themselves carry. Mail transport is exercised once BY HAND when the notifier is
armed; that HITL step does not exist yet and is deliberately not rehearsed.

Module names are spelled in full throughout: `raincheck.notify_render` and
`raincheck.notify_replay` both read as `nr`, so neither is ever aliased here.

Run: make notify-rehearse            (SYNTH=1 skips the real half; no data root needed)
"""
import argparse
import email
import email.policy
import json
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from raincheck import duck
from raincheck import flood_detect as fd
from raincheck import flood_exposure as fe
from raincheck import flood_replay as fr
from raincheck import notify_decide as nd
from raincheck import notify_render
from raincheck import notify_replay
from raincheck import notify_store as ns
from raincheck import release_check
from raincheck.paths import REPO, data_root

FIX = REPO / "tests" / "fixtures" / "flood_detect_ida.json"
NAMED_EVENT = "2023-09-29"

# The two deployment facts, supplied as .invalid values that can never resolve — the
# tree's own constants stay None and a row below asserts they do.
PANEL = "https://panel.invalid/"
OPS = "unsubscribe@ops.invalid"

UTC = timezone.utc
NOON = datetime(2021, 9, 1, 16, tzinfo=UTC)   # 12:00 New York — outside quiet hours
NIGHT = datetime(2021, 9, 2, 6, tzinfo=UTC)   # 02:00 New York — inside them
DUSK = datetime(2021, 9, 2, 1, tzinfo=UTC)    # 21:00 New York / 01:00 UTC — they disagree

# Wordings a message may never acquire. The water list is written AROUND the frozen
# operating-truth string (it contains "an observation of water"); a row below proves the
# two do not collide, so this list cannot silently ban the honesty string.
URGENCY_BARRED = ("1-2 min", "1–2 min", "minute", "second", "live now", "as it happens",
                  "immediately")
WATER_BARRED = ("water was observed", "we observed", "is flooded", "is flooding",
                "water is", "observed flooding")


def _needle() -> str:
    """The retired claim, ASSEMBLED rather than quoted (`tests/test_notify_render.py`'s
    shape): release-check row 5 greps this tree, and a file that spelled the string would
    BE the hit."""
    return " ".join(["a page you", "open during", "a storm, not a", "service that watches"])


# ---- the synthetic event: real detector cycles over the committed Ida fixture ----------

def _fixture() -> dict:
    f = json.loads(FIX.read_text())
    f["peak"] = datetime.fromisoformat(f["peak_hour_utc"])
    f["wet"] = {datetime.fromisoformat(k): v for k, v in f["wet_counts"].items()}
    f["hours"] = [{"cell": c["cell"], "hour_end_utc": datetime.fromisoformat(h), "mm_1h": mm}
                  for c in f["cells"] for h, mm in c["hourly"].items()]
    f["mx"] = {c["cell"]: c["matrix"] for c in f["cells"]}
    return f


def _units(f: dict) -> list[dict]:
    """flood 11's own `_units` shape: the fixture's points, its Cells and one complex."""
    us = [dict(p) for p in f["points"]]
    cell = next(iter(f["mx"]))
    for c, m in f["mx"].items():
        us.append({"asset_id": f"cell:{c:x}", "kind": "cell", "cell": c} | {
            k: m[k] for k in ("share_deep", "share_nuisance", "share_not_analyzed",
                              "density_311_3y")})
    us.append({"asset_id": f["complex_asset_id"], "kind": "complex",
               "complex_id": f["complex_id"], "cell": cell})
    return us


def _cycles(f: dict, us: list[dict], art: dict, det: dict) -> dict:
    """Real `fd.cycle` output, one payload per case. WINDOW_CAPPED is the ONE hand-edited
    state — history never produced it (0 of 4,326 replayed cycles, notify 11), so no
    input can make the real detector emit it here."""
    def run(**kw):
        kw.setdefault("temp_c", 22.0)
        kw.setdefault("table_score_version", art["score_version"])
        state, now = kw.pop("state", None), kw.pop("now", f["peak"])
        hours, wet = kw.pop("hours", f["hours"]), kw.pop("wet", f["wet"])
        return fd.cycle(state, now, hours, us, art, det, wet_by_hour=wet, **kw)

    one = run()
    return {"one": one, "two": run(state=one), "winter": run(temp_c=0.0),
            "skew_none": run(table_score_version=None),
            "skew_other": run(table_score_version="another-model"),
            "insufficient": run(hours=[], wet={}),
            "capped": dict(one, window=dict(one["window"], state=fd.WINDOW_CAPPED))}


def _retier(out: dict, want: dict) -> dict:
    """A REAL cycle payload with named Units re-tiered, latched map kept consistent —
    the four-stop vector cannot produce an ELEVATED on its own (notify 08)."""
    us = [dict(u, tier=want.get(u["asset_id"], u["tier"])) for u in out["units"]]
    return dict(out, units=us,
                latched={u["asset_id"]: u["tier"] for u in us if u["tier"] != fd.NONE})


# ---- rendered-string rows: the nine present, the conditionals, the absences ------------

def _open(m: nd.Message) -> tuple[str, str, object]:
    """(whole corpus, decoded body, parsed message) — rendered with EXPLICIT keyword
    arguments; the tree's PANEL_URL/UNSUBSCRIBE_TO stay None and stay asserted so."""
    raw = notify_render.render(m, panel_url=PANEL, unsubscribe_to=OPS)
    parsed = email.message_from_bytes(raw, policy=email.policy.SMTP)
    return raw.decode("utf-8"), parsed.get_content(), parsed


def string_rows(msgs: list[tuple[str, nd.Message]], det: dict, s: dict,
                frozen: str | None) -> list[tuple[bool, str, str]]:
    """One row per rule, over every rendered message. Every asserted string is READ —
    from `notify_render.strings()`, the artifact, or notify 01's own ticket file."""
    opened = [(label, m, *_open(m)) for label, m in msgs]
    frozen = frozen or ""   # a missing frozen string FAILS the first row, loudly, not with a crash
    out = [(bool(frozen) and frozen == s["operating_truth"],
            "the frozen string's independent side is notify 01's own ticket file",
            f"release_check.frozen_string() == strings()['operating_truth'], "
            f"{len(frozen or '')} chars")]

    def rule(row: str, pred, evidence: str = "") -> None:
        bad = [label for label, m, whole, body, parsed in opened
               if not pred(m, whole, body, parsed)]
        out.append((not bad, row,
                    (evidence + "; " if evidence else "")
                    + (f"FAILED on {bad}" if bad else f"all {len(opened)} messages")))

    present = [("the frozen operating-truth string rides verbatim and unfolded",
                lambda m, w, b, p: frozen in b and frozen in w),
               ("the estimand and its note are the artifact's",
                lambda m, w, b, p: s["estimand"] in b and s["estimand_note"] in b),
               ("within_cell and cutpoint_basis are rendered",
                lambda m, w, b, p: s["within_cell"] in b and s["cutpoint_basis"] in b),
               ("the Window block is the detector's half-open convention",
                lambda m, w, b, p: f"Window {s['window_interval']}" in b
                and m.anchor in b and m.now.isoformat() in b),
               ("all three gate panel strings are rendered, never chosen",
                lambda m, w, b, p: all(s["panel"][k] in b
                                       for k in ("headline", "release", "caveat"))),
               ("the four stamps and the asset id are in the body",
                lambda m, w, b, p: all(x in b for x in (m.score_version,
                                       m.detector_version, m.window_id,
                                       m.unsubscribe_token, m.asset_id))),
               ("the unsubscribe names the real handler, not instant, not one-click",
                lambda m, w, b, p: notify_render.HANDLER in b and "not instant" in b
                and "not one-click" in b)]
    for row, pred in present:
        rule(row, pred)

    rule("the no-skill claim rides on exactly the messages that carry it",
         lambda m, w, b, p: (det["display"]["no_complex_skill_claim"] in b)
         == (m.no_skill_claim is not None),
         "on the MESSAGE, never looked up by kind")
    rule("the provisional-cutpoints note appears only where a tier is claimed",
         lambda m, w, b, p: (det["cutpoints_note"] in b) == (m.tier is not None))

    needle = _needle()
    out.append((bool(re.search(release_check.RETIRED, needle)),
                "the runtime-built needle really is the retired claim",
                "proved against release_check.RETIRED, the gate's own regex"))
    rule("the retired claim appears nowhere in the rendered corpus",
         lambda m, w, b, p: needle not in w
         and not re.search(release_check.RETIRED, w))
    rule("the word None appears in no rendered message",
         lambda m, w, b, p: "None" not in w)
    rule("the audit field cutpoints_confirmed_by never reaches a subscriber",
         lambda m, w, b, p: det["display"]["cutpoints_confirmed_by"] not in w)
    rule("no second-scale urgency wording",
         lambda m, w, b, p: not any(x in b.lower() for x in URGENCY_BARRED))
    out.append((not any(x in frozen.lower() for x in WATER_BARRED)
                and "an observation of water" in frozen,
                "the barred water list is written around the frozen string",
                "the honesty string itself says 'an observation of water'"))
    rule("no observed water is ever claimed, and the denial is present",
         lambda m, w, b, p: "no water has been observed" in b.lower()
         and not any(x in b.lower() for x in WATER_BARRED))
    rule("no List-Unsubscribe-Post header (one-click is barred)",
         lambda m, w, b, p: p["List-Unsubscribe-Post"] is None
         and p["List-Unsubscribe"] is not None)
    return out


# ---- the store: fixture rows in, decided, drained to zero through the handler ----------

def drain_rows(subs: list[dict], messages: list[nd.Message]) -> list[tuple[bool, str, str]]:
    """A throwaway SQLite store holds the fixture rows, the messages' own tokens drain it
    through `notify_store.unsubscribe`, and the end state is ZERO rows read back."""
    out = []
    with tempfile.TemporaryDirectory() as td:
        con = ns.connect(Path(td) / ns.DB_NAME)
        con.executemany("INSERT INTO subscriptions VALUES (?, ?, ?, ?, ?, ?, ?)",
                        [tuple(r[c] for c in ns.COLUMNS) for r in subs])
        con.commit()
        back = ns.subscriptions(con)
        out.append((sorted(map(tuple, (r.items() for r in back)))
                    == sorted(map(tuple, (r.items() for r in subs))),
                    "the store accepts the fixture rows and reads them back unchanged",
                    f"{len(back)} rows, exactly ns.COLUMNS — the fixture IS the store's shape"))
        token_of = {r["handle"]: r["unsubscribe_token"] for r in back}
        out.append((bool(messages) and all(m.unsubscribe_token == token_of[m.handle]
                                           for m in messages),
                    "every message carries its handle's own store token",
                    f"{len(messages)} messages checked"))
        gone = sum(ns.unsubscribe(con, t)
                   for t in dict.fromkeys(m.unsubscribe_token for m in messages))
        for t in {r["unsubscribe_token"] for r in ns.subscriptions(con)}:
            gone += ns.unsubscribe(con, t)   # handles no message reached: the operator's
        left = con.execute("SELECT count(*) FROM subscriptions").fetchone()[0]
        out.append((ns.subscriptions(con) == [] and left == 0 and gone == len(subs),
                    "the tokens drain the store to zero rows",
                    f"{gone} rows removed via notify_store.unsubscribe, {left} left"))
        con.close()
    return out


# ---- part one: the synthetic event ------------------------------------------------------

def synthetic() -> list[tuple[bool, str, str]]:
    det, art = fd.constants(), fe.coefficients()
    s, frozen = notify_render.strings(), release_check.frozen_string()
    f = _fixture()
    us = _units(f)
    cyc = _cycles(f, us, art, det)
    # Both branches, selected the ONLY way one may be: the artifact's own flag, flipped
    # on a COPY. Never a hand-constructed Policy — decide() refuses one.
    watch_p = nd.policy(dict(det, cutpoints=dict(det["cutpoints"], provisional=True)))
    tier_p = nd.policy(dict(det, cutpoints=dict(det["cutpoints"], provisional=False)))
    subs = notify_replay.subscribers(
        [("bus:400070", "bus_stop"), (f["complex_asset_id"], "complex"),
         ("bus:400071", "bus_stop"), ("bus:400166", "bus_stop")], 2)
    one_sub = notify_replay.subscribers([("bus:400070", "bus_stop")], 1)
    optout = [dict(one_sub[0], elevated_optin=0)]
    elevated = _retier(cyc["one"], {"bus:400070": fd.ELEVATED})

    one = cyc["one"]
    out = [(one["window"]["state"] == fd.OK and one["skew"]["model_tier"] == "ok"
            and fd.HIGH in one["latched"].values()
            and {u["kind"] for u in one["units"]} >= {"bus_stop", "complex"},
            "the fixture is real detector output and not degenerate",
            f"window {one['window']['state']}, {len(one['latched'])} latched, HIGH present"),
           (nd.branch(det) == nd.WATCH,
            "the live branch is read from the artifact",
            f"nd.branch(det) = {nd.branch(det)!r} (flood 12's verdict is still [YOU])")]

    w1 = nd.decide(one, None, subs, watch_p, NOON)
    w2 = nd.decide(cyc["two"], w1, subs, watch_p, NOON)
    out.append((len(w1.messages) == len(subs)
                and {m.asset_kind for m in w1.messages} == {"bus_stop", "complex"}
                and all(m.tier is None and m.top_n for m in w1.messages),
                "watch ENTRY: first top-N entry notifies, tier None, top_n carried",
                f"{len(w1.messages)} messages, kinds {sorted({m.asset_kind for m in w1.messages})}"))
    out.append((w2.messages == () and w2.watched == w1.watched,
                "watch HOLD: the same Window fires nothing twice",
                "(unit, window_id) dedupe held on the second cycle"))

    t1 = nd.decide(one, None, subs, tier_p, NOON)
    t2 = nd.decide(cyc["two"], t1, subs, tier_p, NOON)
    out.append((bool(t1.messages) and all(m.tier == fd.HIGH for m in t1.messages),
                "tier ENTRY: a latched HIGH notifies on the tier branch",
                f"{len(t1.messages)} HIGH messages"))
    out.append((t2.messages == (), "tier HOLD: the latch is the dedupe",
                "held tier, second cycle, zero messages"))

    e_in = nd.decide(elevated, None, one_sub, tier_p, NOON)
    e_out = nd.decide(elevated, None, optout, tier_p, NOON)
    out.append(([m.tier for m in e_in.messages] == [fd.ELEVATED] and e_out.messages == (),
                "ELEVATED sends with the opt-in and is silent without it",
                "same payload, elevated_optin 1 vs 0"))
    out.append((bool(nd.decide(one, None, optout, tier_p, NOON).messages),
                "HIGH notifies without any opt-in", "elevated_optin 0, HIGH message sent"))

    nq = nd.decide(elevated, None, one_sub, tier_p, NIGHT)
    late = nd.decide(_retier(cyc["two"], {"bus:400070": fd.ELEVATED}), nq, one_sub,
                     tier_p, NOON)
    wq = nd.decide(one, None, subs, watch_p, NIGHT)
    out.append((nq.messages == () and [d["reason"] for d in nq.drops] == [nd.QUIET],
                "quiet hours DROP an ELEVATED and log it", f"drops {nq.summary()['dropped']}"))
    out.append((late.messages == (),
                "a quiet-hours drop is a drop, never a deferral",
                "the next morning cycle delivered nothing late"))
    out.append((bool(nd.decide(one, None, one_sub, tier_p, NIGHT).messages),
                "HIGH is never suppressed by quiet hours", "02:00 New York, HIGH sent"))
    out.append((wq.messages == ()
                and set(d["reason"] for d in wq.drops) == {nd.QUIET},
                "on watch, quiet hours suppress EVERYTHING (tier is None, nothing urgent)",
                f"{len(wq.drops)} drops, all quiet_hours — notify 11's MUST 4"))
    out.append((bool(nd.decide(elevated, None, one_sub, tier_p, DUSK).messages),
                "the quiet clock is New York's: DUSK sends where a UTC clock would drop",
                "01:00 UTC = 21:00 New York"))

    for key, label in (("skew_none", "an ABSENT table stamp"), ("skew_other", "a skewed stamp")):
        d = nd.decide(cyc[key], None, subs, watch_p, NOON)
        out.append((d.messages == () and d.reason == nd.SKEW,
                    f"version skew is silent: {label} refuses the cycle",
                    f"reason {d.reason!r}"))
    for key, want in (("insufficient", fd.INSUFFICIENT_DATA.lower()),
                      ("capped", fd.WINDOW_CAPPED.lower()), ("winter", nd.WINTER)):
        d = nd.decide(cyc[key], None, subs, watch_p, NOON)
        extra = {"insufficient": "no elapsed Window hour",
                 "capped": "the ONE synthetic-only state: 0 of 4,326 real cycles reach it",
                 "winter": "suppressed with every rank surviving"}[key]
        out.append((d.messages == () and d.reason == want,
                    f"{want} is silent on every branch", extra))
    out.append((any(u["rank"] >= 1.0 for u in cyc["winter"]["units"])
                and all(u["tier"] == fd.NONE for u in cyc["winter"]["units"]),
                "the winter gate zeroes tiers and leaves ranks — the branch re-checks it",
                "measured on the winter cycle's own units"))

    # The per-handle cap: STRUCTURALLY UNREACHABLE on watch (a (unit, Window) fires once,
    # the store refuses an 11th row), so it is built the only way it can be — an
    # ELEVATED -> HIGH escalation on the TIER branch, cap overridden down to 1 because
    # this fixture cannot hold ten entering Units on one handle.
    cap1 = nd.policy(dict(det, cutpoints=dict(det["cutpoints"], provisional=False)),
                     per_handle_event_cap=1)
    c1 = nd.decide(elevated, None, one_sub, cap1, NOON)
    c2 = nd.decide(one, c1, one_sub, cap1, NOON)
    out.append(([m.tier for m in c1.messages] == [fd.ELEVATED] and c2.messages == ()
                and [d["reason"] for d in c2.drops] == [nd.HANDLE_CAP]
                and c2.drops[0]["tier"] == fd.HIGH,
                "the per-handle cap clips a TIER-branch escalation and logs it",
                "ELEVATED sent, the HIGH escalation is the over-cap message"))

    rendered = [("watch bus", next(m for m in w1.messages if m.asset_kind == "bus_stop")),
                ("watch complex", next(m for m in w1.messages if m.asset_kind == "complex")),
                ("tier HIGH", t1.messages[0]), ("tier ELEVATED", e_in.messages[0])]
    out += string_rows(rendered, det, s, frozen)
    out += drain_rows(subs, list(w1.messages))
    out.append((notify_render.PANEL_URL is None and notify_render.UNSUBSCRIBE_TO is None,
                "the two deployment facts are still unset in the tree",
                "rendered with explicit keyword arguments; the [YOU] tripwire holds"))
    return out


# ---- part two: the real events, against the committed replay rows -----------------------

def _walk(ev: dict, wet: dict, temp: dict, by_hour: dict, us: list[dict], art: dict,
          det: dict, sv: str | None, chains: dict) -> dict[str, list[nd.Decision]]:
    """`notify_replay.replay`'s own loop, kept Decision by Decision so the messages can
    be rendered. Its tallies are asserted equal to `replay()`'s below, so this copy
    cannot drift from the walk it mirrors without a row going red."""
    from datetime import timedelta
    nows = fr.hours(ev["window_start_utc"] + timedelta(hours=1), ev["window_end_utc"])
    state = None
    prev: dict[str, nd.Decision | None] = {k: None for k in chains}
    out: dict[str, list[nd.Decision]] = {k: [] for k in chains}
    for now in nows:
        w = fd.walk(now, wet)
        rows = fr.slice_rows(by_hour, w["anchor"], now)   # a LIST: cycle reads it twice
        state = fd.cycle(state, now, rows, us, art, det, temp_c=temp.get(now),
                         wet_by_hour=wet, table_score_version=sv)
        for k, (subs, p) in chains.items():
            d = nd.decide(state, prev[k], subs, p, now)
            prev[k] = d
            out[k].append(d)
    return out


def _fold(decisions: list[nd.Decision]) -> dict:
    t = notify_replay.tally()
    for d in decisions:
        notify_replay.add(t, d)
    return notify_replay.finish(t)


def real(root: Path | str | None = None) -> list[tuple[bool, str, str]]:
    rt: Path | str = root if root is not None else str(data_root())
    con = duck.connect()
    det, art = fd.constants(), fe.coefficients()
    s, frozen = notify_render.strings(), release_check.frozen_string()
    oracle = json.loads(notify_replay.OUT.read_text())

    sv = fr.table_score_version(con, rt)
    if sv != art["score_version"]:
        raise ValueError(f"gold/flood_exposure is stamped {sv} and the coefficients are "
                         f"{art['score_version']}: every cycle would refuse on version "
                         f"skew and the rehearsal would prove nothing")

    live = nd.branch(det)
    other = nd.TIER if live == nd.WATCH else nd.WATCH
    flipped = dict(det, cutpoints=dict(det["cutpoints"], provisional=(other == nd.WATCH)))
    policies = {live: nd.policy(det), other: nd.policy(flipped)}
    cohorts = notify_replay.lists(con, rt, policies[live])
    chains = {f"{c}/{b}": (cohorts[c][0], policies[b]) for c in cohorts for b in policies}

    # The roll fixture is a REAL over-expectation event (windows > 1: the city dried and
    # the storm returned), read off the committed asset — never a score_version swap.
    roll_id = max(o["event_id"] for o in oracle["over_expectation"]
                  if o["rule"] == notify_replay.PER_SUB and o["windows"] > 1)
    out = [(roll_id != NAMED_EVENT,
            "the Window-roll fixture is a real over-expectation event",
            f"{roll_id}, picked from the committed replay's own rows")]

    by_id = {e["event_id"]: e for e in fr.events(con, rt)}
    orc = {r["event_id"]: r for r in oracle["per_event"]}
    messages: list[tuple[str, nd.Message]] = []
    live_key = f"v1_list/{live}"
    for ev_id in (NAMED_EVENT, roll_id):
        ev = by_id[ev_id]
        wet, temp, by_hour, us = notify_replay.inputs(con, rt, ev)
        got = notify_replay.replay(ev, wet, temp, by_hour, us, art, det, sv, chains)
        decs = _walk(ev, wet, temp, by_hour, us, art, det, sv, chains)
        same = all(_fold(decs[k]) == notify_replay.finish(got[k]) for k in chains)
        out.append((same, f"{ev_id}: the message-keeping walk IS the replay's walk",
                    f"{len(chains)} chains fold to identical tallies"))
        match = [k for k in chains
                 if notify_replay.finish(got[k])
                 == {kk: v for kk, v in orc[ev_id]["chains"][k].items()
                     if kk != "over_expectation"}]
        out.append((len(match) == len(chains),
                    f"{ev_id}: every chain reproduces the committed notify-11 row",
                    f"{len(match)}/{len(chains)} chains equal research/notify-11-replay.json"))
        if ev_id == NAMED_EVENT:
            fold = _fold(decs["top_scored/tier"])
            out.append((fold["dropped"].get(nd.CYCLE_FUSE, 0) > 0,
                        "the per-cycle fuse CLIPS on the top_scored cohort",
                        f"{fold['dropped'].get(nd.CYCLE_FUSE, 0)} cycle_fuse drops — the "
                        "only list that can ask the fuse for more than it allows"))
            lv = _fold(decs[live_key])
            out.append((lv["dropped"].get(nd.QUIET, 0) > 0,
                        "quiet hours drop real messages on the live chain",
                        f"{lv['dropped']} on {live_key}"))
            for d in decs[live_key]:
                messages += [(f"real {live}", m) for m in d.messages]
            tiers = [m for d in decs[f"v1_list/{nd.TIER if live == nd.WATCH else nd.WATCH}"]
                     for m in d.messages]
            for tier in (fd.ELEVATED, fd.HIGH):
                pick = next((m for m in tiers if m.tier == tier), None)
                if pick is not None:
                    messages.append((f"real tier {tier}", pick))
            cx = next((m for d in decs["top_scored/tier"] for m in d.messages
                       if m.asset_kind == "complex"), None)
            if cx is not None:
                messages.append(("real tier complex", cx))
        else:
            fold = _fold(decs[live_key])
            out.append((fold["windows"] > 1,
                        f"{ev_id}: the Window ROLLED mid-event and re-armed the dedupe",
                        f"{fold['windows']} Windows on {live_key}, no artifact swap"))

    watch_msgs = [m for label, m in messages if label == f"real {live}"]
    out.append((bool(watch_msgs) and all(m.tier is None for m in watch_msgs)
                if live == nd.WATCH else True,
                "every live-branch message carries tier None",
                f"{len(watch_msgs)} messages on {live_key}"))
    out += string_rows(messages, det, s, frozen)
    out += drain_rows(cohorts["v1_list"][0], watch_msgs)
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--synthetic-only", action="store_true",
                    help="skip the real events (no data root needed)")
    a = ap.parse_args()
    checks = synthetic()
    if not a.synthetic_only:
        checks += real()
    for ok, row, evidence in checks:
        print(f"[{'PASS' if ok else 'FAIL'}] {row}\n         {evidence}")
    bad = [r for ok, r, _ in checks if not ok]
    print(f"notify-rehearse: {len(checks) - len(bad)}/{len(checks)} rows pass"
          + (" (synthetic only)" if a.synthetic_only else ""))
    print("NOT ASSERTED, on purpose: mail transport — exercised once BY HAND when the "
          "notifier is armed, a HITL step that does not exist yet. Nothing here sends.")
    if bad:
        print("REHEARSAL FAILED:\n  " + "\n  ".join(bad))
        raise SystemExit(1)


if __name__ == "__main__":
    main()
