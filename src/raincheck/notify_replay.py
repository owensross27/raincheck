"""Notify ticket 11 (spec section 6; Testing Decisions: "replay is build-asset evidence,
not pytest"): WHAT A REAL STORM WOULD HAVE SENT.

Ticket 08's `notify_decide.decide` — the SAME pure function the live loop calls, not a
second copy of it — replayed hour by hour over flood-build 12's replayable subset, so the
volume a subscriber would have received is a measured number before the notifier is ever
armed. Two artifacts come out, `research/notify-11-replay.json` and its rendered `.md`,
and neither of them is a verdict: sizing the live fuse is notify 10's and the tier/rank
decision is Ross's.

THE SUBSET IS TAKEN OFF FLOOD 12'S ASSET AND NEVER RE-DERIVED. `research/flood-12-replay
.json` counted it — 195 AORC-era events, 133 with `gold/flood_matrix` rows and therefore
evaluable, 62 walk-only, 4,326 hourly cycles of which 76 are INSUFFICIENT_DATA and one
event (2011-08-01) has no OK cycle at all. This module reads those event ids out of that
file's `per_event` block and refuses to run if its own count disagrees. Re-deriving the
universe here would be a second implementation of a rule with one home.

ONE DETECTOR CHAIN, SEVERAL DECISION CHAINS, AND THE SAME `now` GOES TO ALL OF THEM.
`fd.cycle` is expensive (it scores ~14,000 Units per cycle) and `nd.decide` is not, so one
cycle feeds every (cohort, branch) decision chain in the same iteration. Each chain keeps
its own `previous`, exactly as a live loop keeps one.

FLOOD 12'S FOUR RULES ARE HONOURED HERE UNCHANGED, because every one of them is still a
way to publish a wrong count from this file: `wet_by_hour` is passed on every call (the
default counts the Cells you handed it and the citywide gate then never arms), the
`cell_hours` slice is a materialised LIST (`fd.cycle` iterates it twice), the NULL `mm_1h`
rows stay in (AORC's 168 dark Cells are UNFORCED, not holed), and the readout is the union
over an event's cycles rather than the set standing at `window_end`. The union is what a
subscriber received, and notify 08's `(unit, window_id)` dedupe is that same union by
another name — which is why the message counts here need no union pass of their own.

WHICH BRANCH THIS RUN EXERCISED IS READ, NEVER TYPED. `nd.branch(det)` reads
`cutpoints.provisional` out of flood 11's artifact at replay time. It says `watch` today.
A rank-only run and a tier run are not comparable volumes, so both are replayed and both
are labelled: the branch the artifact selects is THE run, and the other is a counterfactual
published beside it because the open [YOU] decision is exactly which one v1 ships.

THE SUBSCRIPTIONS ARE SYNTHETIC AND STORE-SHAPED. Exactly `notify_store.COLUMNS`, ACTIVE,
`asset_kind` in `notify_store.KINDS` — `decide()` RAISES on anything else, and that refusal
is the trust boundary working rather than a shape to route around. Three lists run, each
isolating one variable: `v1_list` is the realistic list at the ingress ceiling, `post_ingress`
is the same selection past it (SIZE), and `top_scored` is the same size picked by static
exposure rank instead (SELECTION). The third one exists because a rank cut is not a
threshold: a list of arbitrary stops can never ask the per-cycle fuse for more than it
allows, so the only way to test the fuse against a real event is a list whose members are
the Units the rank puts on top.

Run: make notify-replay                   (ONLY=<event_id> / LIMIT=<n> for a smoke run)
"""
import argparse
import json
from collections import Counter
from datetime import timedelta
from pathlib import Path

from raincheck import duck
from raincheck import flood_detect as fd
from raincheck import flood_exposure as fe
from raincheck import flood_replay as fr
from raincheck import notify_decide as nd
from raincheck import notify_store as ns
from raincheck.paths import REPO, data_root

OUT = REPO / "research" / "notify-11-replay.json"
DOC = REPO / "research" / "notify-11-replay.md"
F12 = fr.OUT      # research/flood-12-replay.json — the subset is COUNTED there, not here

# Synthetic handles under RFC 2606's reserved `.invalid`, which can never resolve to a real
# mailbox. They never reach the published asset: every number below comes from
# `Decision.summary()` (counts only, no handle) or from `Message.asset_kind`.
HANDLE = "sub{:02d}@replay.invalid"
CONSENT = "2010-01-01T00:00:00+00:00"     # before the first replayed event

# THE TWO WAYS A SUBSCRIBER PICKS AN ASSET, and they are not the same list.
MOST_FLOODED, TOP_SCORED = "most_flooded", "top_scored"

# Three lists, each isolating ONE variable, and every size DERIVED from the two constants
# notify 08 sized the fuse against rather than picked.
#   * v1_list      — the realistic list at the ceiling the deferred ingress is allowed to
#                    hold (`ns.INGRESS_TRIGGER_ENTRIES`); the 26th entry reopens ticket 07.
#   * post_ingress — the SAME selection, every handle at the store's per-handle cap. It is
#                    past the ingress trigger by construction, so it isolates SIZE.
#   * top_scored   — the same size, picked by the static exposure rank instead. It isolates
#                    SELECTION, and it is the adversarial case: the live rank is a rank, so
#                    the only list that can ask a per-cycle fuse for more than it allows is
#                    one whose members ARE the Units the rank puts on top.
COHORTS = (("v1_list", ns.INGRESS_TRIGGER_ENTRIES, 5, MOST_FLOODED),
           ("post_ingress", 6 * ns.MAX_PER_HANDLE, 6, MOST_FLOODED),
           ("top_scored", 6 * ns.MAX_PER_HANDLE, 6, TOP_SCORED))

# Two named per-event expectations. A run that breaks either gets a row in `over_expectation`
# and a line in the printed report — never silently absorbed into a pooled total.
#
# OVER_FUSE is named for what it MEASURES and not for what it looks like. A cycle's OWED
# messages are `sent + dropped`, and a message dropped for quiet hours is dropped BEFORE the
# fuse is consulted (`decide` tests quiet -> handle cap -> fuse, in that order), so a cycle
# can owe more than the fuse allows while the fuse never fires at all — which is the normal
# overnight case on the watch branch. The row therefore carries `fuse_dropped` beside
# `wanted`: nonzero is the fuse actually clipping, zero is a volume the policy shed earlier.
OVER_FUSE = "cycle_owed_more_than_the_fuse_allows"
PER_SUB = "more_than_one_message_per_subscription"


# ---- the subset, read off flood 12's asset ---------------------------------------------

def subset(path: Path = F12) -> dict:
    """flood 12's replayable subset: the event ids it evaluated, plus its own counts.

    Every number here is READ. The ticket file's "248 event-days" is the whole 206-event
    union universe and is not this; the AORC-era one is what that asset's `universe` and
    `excluded` blocks say, and if this module ever replays a different number of events the
    build refuses rather than publishing a subset nobody counted.
    """
    p = Path(path)
    d = json.loads(p.read_text())
    return {"source": str(p.relative_to(REPO)) if p.is_relative_to(REPO) else str(p),
            "event_ids": [r["event_id"] for r in d["per_event"]],
            "aorc_era_events": d["universe"]["aorc_era_events"],
            "replayed_with_evaluation": d["universe"]["replayed_with_evaluation"],
            "walk_only": d["universe"]["walk_only"],
            "cycles_total": d["excluded"]["cycles_total"],
            "cycles_by_walk_state": d["excluded"]["cycles_by_walk_state"],
            "events_with_no_ok_cycle": d["excluded"]["events_with_no_ok_cycle"],
            "detector_version": d["detector_version"],
            "score_version": d["score_version"],
            "flag_volume": {k: {"rows": v["rows"], "events": v["events"],
                                fd.ELEVATED: v[fd.ELEVATED]["flagged"],
                                fd.HIGH: v[fd.HIGH]["flagged"]}
                            for k, v in d["flag_volume"].items()},
            "note": ("the universe is COUNTED in flood 12's asset and read here; this "
                     "module re-derives none of it")}


# ---- the synthetic list ----------------------------------------------------------------

def hot(con, root: Path | str, kind: str, n: int) -> list[str]:
    """The `n` most-flooded Units of a kind in `gold/flood_matrix`, ties broken on asset_id.

    What a person subscribes to: the stop that floods. Deterministic, and NOT the average
    stop — flood 12's pooled flag rate is that number and it is published beside these.
    """
    rows = con.execute(
        f"""SELECT asset_id, count(*) FILTER (WHERE flooded) AS n_flooded
            FROM read_parquet('{root}/gold/flood_matrix/**/*.parquet')
            WHERE kind = ? GROUP BY 1 ORDER BY n_flooded DESC, asset_id LIMIT {int(n)}""",
        [kind]).fetchall()
    return [r[0] for r in rows]


def scored(con, root: Path | str, kind: str, n: int) -> list[str]:
    """The `n` highest STATIC exposure ranks of a kind, from `gold/flood_exposure`'s own
    `score_index` — flood 10's published within-kind rank, read and never recomputed.

    This is the adversarial list and it is deliberately NOT derived from this replay's own
    output, which would be circular. The live rank is the same model with the storm's precip
    added, so a Unit that ranks high statically is the one most likely to sit in the live
    top N once its Cell is wet — which is the only way a list can ask the per-cycle fuse for
    more messages than it allows.
    """
    rows = con.execute(
        f"""SELECT asset_id FROM read_parquet('{root}/gold/flood_exposure/**/*.parquet')
            WHERE kind = ? ORDER BY score_index DESC, asset_id LIMIT {int(n)}""",
        [kind]).fetchall()
    return [r[0] for r in rows]


SELECTORS = {MOST_FLOODED: hot, TOP_SCORED: scored}
SELECTION_NOTE = {
    MOST_FLOODED: ("the most-flooded Units in gold/flood_matrix (ties on asset_id) — what a "
                   "person subscribes to, and orthogonal to what the live rank ranks"),
    TOP_SCORED: ("the highest static score_index in gold/flood_exposure (ties on asset_id) — "
                 "the adversarial list, the Units the live rank is most likely to put on top"),
}


def picks(assets: dict, total: int, p: nd.Policy) -> list[tuple[str, str]]:
    """(asset_id, kind) rows in the SAME ratio as the watch cut itself — `watch_top_n` is
    25 bus stops to 5 complexes — so neither subscribable kind is a token row. The ratio is
    read off the policy; typing one here would be a second copy of it."""
    share = p.watch_top_n["complex"] / sum(p.watch_top_n.values())
    n_cx = min(round(total * share), len(assets["complex"]))
    cx = [(a, "complex") for a in assets["complex"][:n_cx]]
    bus = [(a, "bus_stop") for a in assets["bus_stop"][:total - n_cx]]
    return cx + bus


def subscribers(rows: list[tuple[str, str]], handles: int) -> list[dict]:
    """Store-shaped ACTIVE subscriptions, dealt round-robin across `handles` handles so no
    handle is a single-kind list and none passes the store's own cap. Exactly `ns.COLUMNS`,
    in order — `decide()` raises on anything the store could not have produced, and that
    refusal is the trust boundary, not an obstacle.

    Every row opts in to ELEVATED. On the watch branch the flag is not read at all; on the
    tier branch it is the difference between HIGH-only and everything, so opting all of them
    in is the LOUDEST list, which is the one a fuse has to survive.
    """
    out = [{"handle": HANDLE.format(i % handles), "asset_id": a, "asset_kind": k,
            "elevated_optin": 1, "consent_ts": CONSENT,
            "unsubscribe_token": f"replay-token-{i % handles:02d}", "state": ns.STATES[0]}
           for i, (a, k) in enumerate(rows)]
    per = Counter(r["handle"] for r in out)
    if per and max(per.values()) > ns.MAX_PER_HANDLE:
        raise ValueError(f"{max(per.values())} rows on one handle: the store refuses past "
                         f"{ns.MAX_PER_HANDLE}, so this list could not exist")
    if any(tuple(r) != ns.COLUMNS for r in out):
        raise ValueError(f"a synthetic row is not the store's shape {ns.COLUMNS}")
    return out


def lists(con, root: Path | str, p: nd.Policy) -> dict:
    """{cohort: (subscriptions, definition)} — built ONCE, before any cycle runs."""
    widest = max(t for _, t, _, _ in COHORTS)
    assets = {sel: {k: SELECTORS[sel](con, root, k, widest) for k in ns.KINDS}
              for sel in {s for *_, s in COHORTS}}
    out = {}
    for name, total, handles, sel in COHORTS:
        rows = picks(assets[sel], total, p)
        subs = subscribers(rows, handles)
        out[name] = (subs, {
            "subscriptions": len(subs), "handles": handles, "selection": sel,
            "per_handle": max(Counter(s["handle"] for s in subs).values()),
            "by_kind": dict(Counter(s["asset_kind"] for s in subs)),
            "assets": {k: [a for a, kk in rows if kk == k] for k in ns.KINDS},
            "worst_case": handles * ns.MAX_PER_HANDLE,
            # what this list can ACTUALLY produce in one cycle. A Unit fires once per
            # cycle, so a cycle can never owe more than one message per subscription —
            # while `Decision.worst_case` is handles x MAX_PER_HANDLE, the ceiling on
            # the STORE. The two differ whenever a handle is not full.
            "reachable_max_per_cycle": len(subs),
            "past_ingress_trigger": len(subs) > ns.INGRESS_TRIGGER_ENTRIES,
            "selection_note": SELECTION_NOTE[sel]})
    return out


# ---- the replay -------------------------------------------------------------------------

def tally() -> dict:
    return {"cycles": 0, "silent": Counter(), "messages": 0, "by_kind": Counter(),
            "by_tier": Counter(), "drops": 0, "dropped": Counter(), "windows": set(),
            "cycles_with_messages": 0, "peak_cycle_messages": 0, "peak_cycle_wanted": 0,
            "worst_case": 0}


def add(t: dict, d: nd.Decision) -> None:
    """Fold one cycle's Decision into the running tally.

    The per-cycle numbers come from `Decision.summary()`, which is counts only and carries
    no handle; the per-kind split is `decision.messages` grouped by `asset_kind`, which is
    the only place a kind is knowable. The fuse's victims and the cap's victims stay
    SEPARATE rows: "this would have sent 400" and "this would have DROPPED 400" are
    different answers and pooling them would hide the one that matters.
    """
    s = d.summary()
    t["cycles"] += 1
    t["worst_case"] = max(t["worst_case"], s["worst_case"])
    if s["window_id"] is not None:
        t["windows"].add(s["window_id"])
    if s["reason"] is not None:
        t["silent"][s["reason"]] += 1
    t["messages"] += s["messages"]
    t["drops"] += s["drops"]
    t["dropped"].update(s["dropped"])
    t["peak_cycle_messages"] = max(t["peak_cycle_messages"], s["messages"])
    t["peak_cycle_wanted"] = max(t["peak_cycle_wanted"], s["messages"] + s["drops"])
    t["cycles_with_messages"] += 1 if s["messages"] else 0
    for m in d.messages:
        t["by_kind"][m.asset_kind] += 1
        t["by_tier"][str(m.tier)] += 1


def replay(ev: dict, wet: dict, temp: dict, by_hour: dict, us: list[dict],
           art: dict, det: dict, score_version: str | None, chains: dict) -> dict:
    """One event, hour by hour: ONE `fd.cycle` chain, one `nd.decide` chain per key in
    `chains` ({key: (subscriptions, policy)}), and the SAME `now` handed to every call.

    Both states are chained — each call's return is the next call's `previous` — which is
    what makes the latch (tier branch) and the (unit, window_id) dedupe (watch branch) work
    without a daemon, and it is why the message counts here are already per (unit, Window).
    """
    ws, we = ev["window_start_utc"], ev["window_end_utc"]
    nows = fr.hours(ws + timedelta(hours=1), we)
    state: dict | None = None
    prev: dict[str, nd.Decision | None] = {k: None for k in chains}
    out = {k: tally() for k in chains}
    for now in nows:
        w = fd.walk(now, wet)
        # a materialised LIST: `fd.cycle` iterates cell_hours TWICE and a generator comes
        # back as an empty Window with coverage 1.0 and nothing flagged [flood 12].
        rows = fr.slice_rows(by_hour, w["anchor"], now)
        state = fd.cycle(state, now, rows, us, art, det, temp_c=temp.get(now),
                         wet_by_hour=wet, table_score_version=score_version)
        for k, (subs, p) in chains.items():
            d = nd.decide(state, prev[k], subs, p, now)
            prev[k] = d
            add(out[k], d)
    return out


def over(t: dict, n_subs: int, fuse: int) -> list[dict]:
    """The two per-event expectations, read off a FINISHED row.

    Kept out of `finish()` on purpose: a row carries the counts, and the expectations are a
    pure function of them — so a wording or threshold fix re-renders from the committed
    per-event rows instead of costing another 4,326-cycle replay.

    * the FUSE — a cycle may want at most `per_cycle_fuse` messages. A Unit fires once per
      cycle, so wanting more means more subscriptions landed on entering Units than the
      deferred ingress list is allowed to hold.
    * ONE PER SUBSCRIPTION — an event owes at most one message per subscription. More has
      TWO causes and the row's own `windows` count tells them apart: `windows > 1` is a
      Window that ROLLED mid-event (the city dried and the storm came back), and
      `windows == 1` on the tier branch is an ESCALATION — a Unit that entered at ELEVATED
      and came back at HIGH is a second message for the same (unit, Window), by design.
      Neither is a duplicate. On the watch branch only the first can happen: the rank has
      no tiers to escalate through.
    """
    rows = []
    if t["peak_cycle_wanted"] > fuse:
        rows.append({"rule": OVER_FUSE, "wanted": t["peak_cycle_wanted"],
                     "allowed": fuse,
                     "fuse_dropped": t["dropped"].get(nd.CYCLE_FUSE, 0)})
    owed = t["messages"] + t["drops"]
    if owed > n_subs:
        rows.append({"rule": PER_SUB, "owed": owed, "subscriptions": n_subs,
                     "windows": t["windows"]})
    return rows


def finish(t: dict) -> dict:
    """A tally as it publishes: sets become counts, Counters become plain dicts."""
    return {"cycles": t["cycles"], "silent_cycles": dict(t["silent"]),
            "windows": len(t["windows"]), "messages": t["messages"],
            "by_kind": dict(t["by_kind"]), "by_tier": dict(t["by_tier"]),
            "drops": t["drops"], "dropped": dict(t["dropped"]),
            "cycles_with_messages": t["cycles_with_messages"],
            "peak_cycle_messages": t["peak_cycle_messages"],
            "peak_cycle_wanted": t["peak_cycle_wanted"], "worst_case": t["worst_case"]}


# ---- pooling ----------------------------------------------------------------------------

def pooled(rows: list[dict], key: str, cohort: dict, years: float) -> dict:
    """Sum the per-event counts and recompute the rates. Averaging per-event rates would
    weight a quiet night the same as Ida."""
    got = [r["chains"][key] for r in rows if key in r["chains"]]
    out = {"events": len(got), "events_that_sent": sum(1 for g in got if g["messages"]),
           "cycles": sum(g["cycles"] for g in got),
           "windows": sum(g["windows"] for g in got),
           "messages": sum(g["messages"] for g in got),
           "drops": sum(g["drops"] for g in got),
           "peak_event_messages": max((g["messages"] for g in got), default=0),
           "peak_cycle_messages": max((g["peak_cycle_messages"] for g in got), default=0),
           "peak_cycle_wanted": max((g["peak_cycle_wanted"] for g in got), default=0),
           "worst_case": max((g["worst_case"] for g in got), default=0)}
    for name in ("by_kind", "by_tier", "dropped", "silent_cycles"):
        c: Counter = Counter()
        for g in got:
            c.update(g[name])
        out[name] = dict(c)
    out["messages_per_subscription_per_year"] = {
        k: (out["by_kind"].get(k, 0) / n / years if n and years else None)
        for k, n in cohort["by_kind"].items()}
    out["events_over_the_fuse"] = sum(
        1 for g in got if any(o["rule"] == OVER_FUSE for o in g["over_expectation"]))
    out["events_the_fuse_clipped"] = sum(1 for g in got if g["dropped"].get(nd.CYCLE_FUSE))
    out["multi_window_events"] = sum(
        1 for g in got if any(o["rule"] == PER_SUB for o in g["over_expectation"]))
    return out


def distinct_units(con, root: Path | str) -> dict[str, int]:
    """The DISTINCT Units of each kind in `gold/flood_matrix` — the denominator every rate
    below is divided by, MEASURED rather than re-typed."""
    return dict(con.execute(
        f"""SELECT kind, count(DISTINCT asset_id)
            FROM read_parquet('{root}/gold/flood_matrix/**/*.parquet') GROUP BY 1""").fetchall())


def f12_flag_rate(sub: dict, units: dict[str, int], years: float) -> dict:
    """flood 12's own pooled flag volume, expressed on the same per-Unit-per-year scale as
    the message rates above so the two are readable side by side.

    A FLAG is not a message: the watch branch notifies the top N of a kind per Window and
    ELEVATED+ is ~15% of the Units present, so this is the number the watch cut is measured
    AGAINST and never the number it produces. The denominator is named beside every rate,
    because a rate quoted without one is partly a statement about the budget [flood 09].
    """
    return {k: {"flags_elevated_plus": v[fd.ELEVATED], "flags_high": v[fd.HIGH],
                "units": units.get(k),
                "per_unit_per_year": (v[fd.ELEVATED] / units[k] / years
                                      if units.get(k) and years else None)}
            for k, v in sub["flag_volume"].items()}


# ---- the build ---------------------------------------------------------------------------

def inputs(con, root: Path | str, ev: dict) -> tuple[dict, dict, dict, list[dict]]:
    """flood 12's four reads for one event, in flood 12's own order and with its own spans.
    The citywide series is the WHOLE grid and the Cell-hour rows keep their NULLs."""
    ws, we = ev["window_start_utc"], ev["window_end_utc"]
    wet = fr.citywide(con, root, ws - timedelta(days=fd.CAP_DAYS + 2), we)
    us = fr.units(con, root, ev["event_id"])
    anchors = [w for w in (fd.walk(n, wet) for n in
                           fr.hours(ws + timedelta(hours=1), we)) if w["anchor"]]
    lo = (min(w["anchor"] for w in anchors) if anchors else ws) - timedelta(hours=fd.ANTECEDENT_H)
    return wet, fr.temps(con, root, lo, we), fr.cell_rows(con, root, lo, we), us


def build(root: Path | str | None = None, only: str | None = None, limit: int | None = None,
          out: Path = OUT, doc: Path = DOC, f12: Path = F12) -> dict:
    rt: Path | str = root if root is not None else str(data_root())
    con = duck.connect()
    art, det = fe.coefficients(), fd.constants()
    sub = subset(f12)

    # THE STAMP THAT WAS READ, never a constant — `fd.skew`'s rule. It is asserted equal to
    # the artifact's rather than replaced by it: a skewed pair makes `nd.silent()` return
    # `version_skew` on EVERY cycle and the whole replay publishes zeros that look like a
    # quiet decade.
    score_version = fr.table_score_version(con, rt)
    if score_version != art["score_version"]:
        raise ValueError(f"gold/flood_exposure is stamped {score_version} and the "
                         f"coefficients are {art['score_version']}: every cycle would "
                         f"refuse on version skew and this replay would publish zeros")

    live = nd.branch(det)
    other = nd.TIER if live == nd.WATCH else nd.WATCH
    # Both policies come from `nd.policy(det)`; the counterfactual selects its branch the
    # ONLY way one may be selected — by the artifact's own flag, on a copy.
    flipped = dict(det, cutpoints=dict(det["cutpoints"], provisional=(other == nd.WATCH)))
    policies = {live: nd.policy(det), other: nd.policy(flipped)}
    if policies[other].branch != other:
        raise ValueError(f"the counterfactual policy is {policies[other].branch}, not {other}")

    cohorts = lists(con, rt, policies[live])
    chains = {f"{c}/{b}": (cohorts[c][0], policies[b]) for c in cohorts for b in policies}

    evs = [e for e in fr.events(con, rt) if e["event_id"] in set(sub["event_ids"])]
    if only:
        evs = [e for e in evs if e["event_id"] == only]
    if limit:
        evs = evs[:limit]
    whole = only is None and limit is None
    if whole and len(evs) != sub["replayed_with_evaluation"]:
        raise ValueError(f"{len(evs)} events resolve from flood 12's subset of "
                         f"{sub['replayed_with_evaluation']}: the universe moved under the "
                         f"asset and the counts would not be comparable")

    per_event = []
    for i, ev in enumerate(evs, 1):
        wet, temp, by_hour, us = inputs(con, rt, ev)
        got = replay(ev, wet, temp, by_hour, us, art, det, score_version, chains)
        row = {"event_id": ev["event_id"], "day_start": ev["day_start"],
               "event_class": ev["event_class"], "n_days": ev["n_days"],
               "chains": {k: finish(v) for k, v in got.items()}}
        for k, c in row["chains"].items():
            c["over_expectation"] = over(c, len(chains[k][0]),
                                         chains[k][1].per_cycle_fuse)
        per_event.append(row)
        h = row["chains"][f"v1_list/{live}"]
        print(f"[{i}/{len(evs)}] {ev['event_id']} cycles={h['cycles']} "
              f"v1_list/{live} msgs={h['messages']} drops={h['drops']} "
              f"peak_cycle={h['peak_cycle_messages']}", flush=True)

    years = span_years(per_event) if per_event else 0.0
    doc_out = {
        "branch": {
            "live": live, "read_from": "notify_decide.branch(flood_detect.constants())",
            "selected_by": ("research/flood-11-detector.json cutpoints.provisional is "
                            f"{det['cutpoints'].get('provisional')}"),
            "counterfactual": other,
            "why_both": ("a rank-only run and a tier run are not comparable volumes, and "
                         "which one v1 ships is the open [YOU] decision flood 12 measured "
                         "and recommended on — so the branch the artifact selects is THE "
                         "run and the other is published beside it, labelled"),
            "watch_has_no_urgent_message": True,
            "watch_note": ("on the watch branch `Message.tier` is None, so no message is "
                           "HIGH and the quiet-hours rule applies to EVERY one of them; "
                           "`elevated_optin` is read on the tier branch only"),
        },
        "detector_version": det["detector_version"], "score_version": art["score_version"],
        "table_score_version": score_version, "skew": fd.skew(art, score_version),
        "policy": policy_block(policies[live]),
        "subset": sub, "span_years": years, "events_replayed": len(per_event),
        "partial_run": not whole,
        "cohorts": {c: d for c, (_, d) in cohorts.items()},
        "expectations": expectations(policies[live].per_cycle_fuse),
        "volume": {k: pooled(per_event, k, cohorts[k.split("/")[0]][1], years)
                   for k in chains},
        "over_expectation": [dict(o, event_id=r["event_id"], chain=k)
                             for r in per_event for k, v in r["chains"].items()
                             for o in v["over_expectation"]],
        "flood_12_flag_volume": f12_flag_rate(sub, distinct_units(con, rt), years),
        "verdict": {
            "question": "does notify 08's fuse sizing survive a real event",
            "answered_by": "notify 10 sizes the live fuse; this harness measures",
            "this_build_wrote_no_artifact_but_its_own": True,
        },
        "per_event": per_event,
    }
    out.write_text(json.dumps(doc_out, indent=1, sort_keys=True, default=str) + "\n")
    doc.write_text(render(doc_out))
    return doc_out


def span_years(per_event: list[dict]) -> float:
    """The replayed span in years, from the events' own day_starts. Named because a rate
    without its denominator is a statement about the budget."""
    days = sorted(r["day_start"] for r in per_event)
    return ((days[-1] - days[0]).days + 1) / 365.25


def policy_block(p: nd.Policy) -> dict:
    """The constants actually in force, read off the Policy the run used."""
    return {"branch": p.branch, "watch_top_n": dict(p.watch_top_n),
            "notifying_tiers": list(p.notifying_tiers),
            "quiet_hours": list(p.quiet_hours), "quiet_hours_tz": str(p.quiet_hours_tz),
            "per_cycle_fuse": p.per_cycle_fuse, "per_handle_event_cap": p.per_handle_event_cap,
            "own_cell_window_mm": p.own_cell_window_mm,
            "ingress_trigger_entries": ns.INGRESS_TRIGGER_ENTRIES,
            "max_per_handle": ns.MAX_PER_HANDLE,
            "fuse_equals_ingress_trigger": p.per_cycle_fuse == ns.INGRESS_TRIGGER_ENTRIES}


def expectations(fuse: int) -> dict:
    return {
        OVER_FUSE: {
            "rule": f"a cycle OWES at most per_cycle_fuse = {fuse} messages",
            "means": ("more subscriptions landed on entering Units in one cycle than the "
                      "deferred-ingress list is allowed to hold. Read `fuse_dropped` on the "
                      "row: nonzero is the fuse clipping, zero is a cycle whose volume the "
                      "quiet-hours or per-handle rule shed before the fuse was consulted")},
        PER_SUB: {"rule": "an event owes at most one message per subscription",
                  "means": ("read the row's `windows`: >1 is a Window that ROLLED mid-event "
                            "(the city dried and the storm came back) and ==1 on the tier "
                            "branch is an ESCALATION, a Unit that entered at ELEVATED and "
                            "came back at HIGH. Neither is a duplicate, and only the first "
                            "can happen on the watch branch — a rank has no tiers to "
                            "escalate through")},
    }


# ---- the render ---------------------------------------------------------------------------

def derived(d: dict) -> dict:
    """The blocks that are a pure function of the committed per-event rows and the policy.

    `--render-only` goes through here, which is why `over()` lives outside `finish()`: a
    wording or threshold fix costs a re-render, not another 4,326-cycle replay.
    """
    fuse = d["policy"]["per_cycle_fuse"]
    rows = []
    for r in d["per_event"]:
        for k, c in r["chains"].items():
            c["over_expectation"] = over(c, d["cohorts"][k.split("/")[0]]["subscriptions"],
                                         fuse)
            rows += [dict(o, event_id=r["event_id"], chain=k) for o in c["over_expectation"]]
    return dict(d, expectations=expectations(fuse), over_expectation=rows)


def plural(n: int, word: str) -> str:
    return f"{n:,} {word}" + ("" if n == 1 else "s")


def sd(x: dict) -> dict:
    """Key-sorted, so the document does not depend on which dict order it was handed. A
    build renders from live dicts and `--render-only` renders from a `sort_keys=True` JSON;
    without this the two produce different bytes for the same numbers."""
    return dict(sorted(x.items()))


def num(x, nd_=3) -> str:
    return "-" if x is None else (f"{x:,}" if isinstance(x, int) else f"{x:.{nd_}f}")


def render(d: dict) -> str:
    b, p, s = d["branch"], d["policy"], d["subset"]
    live = b["live"]
    L = ["# notify 11 — what a real storm would have sent", "",
         f"The SAME `notify_decide.decide` the live loop calls, replayed over flood 12's "
         f"replayable subset. Evidence for a human; the volume numbers are not assertions.", "",
         f"**BRANCH EXERCISED: `{live}`** — read at replay time from `{b['read_from']}`, "
         f"never typed. Selected by {b['selected_by']}. The `{b['counterfactual']}` branch "
         f"is replayed beside it as a labelled counterfactual: {b['why_both']}.", "",
         f"- detector `{d['detector_version'][:12]}` · score `{d['score_version'][:12]}` · "
         f"table stamp `{d['table_score_version'][:12]}` · skew "
         f"`{d['skew']['model_tier']}`",
         f"- subset READ from `{s['source']}`: **{s['replayed_with_evaluation']} events** of "
         f"{s['aorc_era_events']} AORC-era ({s['walk_only']} walk-only), "
         f"**{s['cycles_total']:,} hourly cycles** "
         f"({', '.join(f'{v:,} {k}' for k, v in sorted(s['cycles_by_walk_state'].items()))}), "
         f"{s['events_with_no_ok_cycle']} event with no OK cycle. "
         f"**{plural(d['events_replayed'], 'event')} replayed here over "
         f"{d['span_years']:.2f} years**" + (" — PARTIAL RUN, the per-year "
         "rates below are over that span and not over the subset"
         if d['partial_run'] else "") + ".",
         f"- policy in force: watch cut `{p['watch_top_n']}` · per-cycle fuse "
         f"**{p['per_cycle_fuse']}** · per-handle cap **{p['per_handle_event_cap']}** · "
         f"quiet hours {p['quiet_hours']} {p['quiet_hours_tz']} · own-Cell gate "
         f"{p['own_cell_window_mm']} mm.",
         f"- **the fuse and the ingress trigger are the same number "
         f"({p['per_cycle_fuse']}): `{p['fuse_equals_ingress_trigger']}`.**", "",
         "## The lists", ""]
    for name, c in sorted(d["cohorts"].items()):
        L.append(f"- **`{name}`** — {c['subscriptions']} subscriptions over {c['handles']} "
                 f"handles ({c['per_handle']} each, cap {p['max_per_handle']}), "
                 f"{sd(c['by_kind'])}; past the ingress trigger: "
                 f"**{c['past_ingress_trigger']}**. Published `worst_case` **{c['worst_case']}** "
                 f"against a reachable max of **{c['reachable_max_per_cycle']}** per cycle. "
                 f"Assets: {c['selection_note']}.")
    L += ["", "## Volume", "",
          "| chain | events that sent | messages | by kind | by tier | drops | dropped |",
          "| --- | ---: | ---: | --- | --- | ---: | --- |"]
    for k in sorted(d["volume"]):
        v = d["volume"][k]
        mark = " **(live)**" if k.endswith("/" + live) else ""
        L.append(f"| `{k}`{mark} | {v['events_that_sent']}/{v['events']} | "
                 f"{v['messages']:,} | {sd(v['by_kind']) or '-'} | "
                 f"{sd(v['by_tier']) or '-'} | "
                 f"{v['drops']:,} | {sd(v['dropped']) or '-'} |")
    head = ("chain", "peak event", "peak cycle sent", "peak cycle wanted", "worst_case",
            "events over the fuse", "events the fuse clipped", "multi-Window events",
            "per subscription per year")
    L += ["", "| " + " | ".join(head) + " |",
          "| --- |" + " ---: |" * (len(head) - 2) + " --- |"]
    for k in sorted(d["volume"]):
        v = d["volume"][k]
        rate = sd({kk: (None if r is None else round(r, 3))
                   for kk, r in v["messages_per_subscription_per_year"].items()})
        L.append(f"| `{k}` | {v['peak_event_messages']:,} | {v['peak_cycle_messages']} | "
                 f"{v['peak_cycle_wanted']} | {v['worst_case']} | "
                 f"{v['events_over_the_fuse']} | {v['events_the_fuse_clipped']} | "
                 f"{v['multi_window_events']} | {rate} |")
    L += ["", b["watch_note"] + ".", "", "## Silent cycles, and why", "",
          "| chain | " + " | ".join(nd.REASONS) + " |",
          "| --- | " + " | ".join("---:" for _ in nd.REASONS) + " |"]
    for k in sorted(d["volume"]):
        sc = d["volume"][k]["silent_cycles"]
        L.append(f"| `{k}` | " + " | ".join(f"{sc.get(r, 0):,}" for r in nd.REASONS) + " |")
    L += ["", "## Over expectation — never silently absorbed", ""]
    for name, e in sorted(d["expectations"].items()):
        L.append(f"- **{name}** — {e['rule']}. Breaking it means: {e['means']}.")
    rows = d["over_expectation"]
    L += ["", f"**{plural(len(rows), 'row')}.**" if rows else "**No event broke either expectation.**", ""]
    if rows:
        L += ["| event | chain | rule | detail |", "| --- | --- | --- | --- |"]
        for r in sorted(rows, key=lambda r: (r["chain"], r["event_id"])):
            detail = sd({k: v for k, v in r.items()
                          if k not in ("event_id", "chain", "rule")})
            L.append(f"| {r['event_id']} | `{r['chain']}` | {r['rule']} | {detail} |")
    L += ["", "## What this is measured against — flood 12's flag volume", "",
          "A FLAG is not a message. The watch branch notifies the top N of a kind per "
          "Window; ELEVATED+ is ~15% of the Units present. These are the numbers the cut "
          "is measured against, on the same per-Unit-per-year scale.", "",
          "| kind | ELEVATED+ flags | HIGH flags | units | per unit per year |",
          "| --- | ---: | ---: | ---: | ---: |"]
    for k, v in sorted(d["flood_12_flag_volume"].items()):
        L.append(f"| {k} | {v['flags_elevated_plus']:,} | {v['flags_high']:,} | "
                 f"{num(v['units'])} | {num(v['per_unit_per_year'])} |")
    L += ["", "## The verdict this harness does NOT record", "",
          f"**{d['verdict']['question']}** — {d['verdict']['answered_by']}.", ""]
    return "\n".join(L)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--only", help="replay one event_id")
    ap.add_argument("--limit", type=int, help="replay the first N events (smoke run)")
    ap.add_argument("--render-only", action="store_true",
                    help="re-render the .md from the committed .json, without replaying")
    a = ap.parse_args()
    if a.render_only:
        d = derived(json.loads(OUT.read_text()))
        OUT.write_text(json.dumps(d, indent=1, sort_keys=True, default=str) + "\n")
        DOC.write_text(render(d))
    else:
        d = build(only=a.only, limit=a.limit)
    live = d["branch"]["live"]
    for k in sorted(d["volume"]):
        v = d["volume"][k]
        print(f"{k}{' (LIVE BRANCH)' if k.endswith('/' + live) else ''}: "
              f"{v['messages']:,} messages, {v['drops']:,} dropped {v['dropped']}, "
              f"{v['events_that_sent']}/{v['events']} events sent, "
              f"peak cycle {v['peak_cycle_messages']} sent / {v['peak_cycle_wanted']} wanted",
              flush=True)
    rows = d["over_expectation"]
    print(f"OVER EXPECTATION: {plural(len(rows), 'row')}"
          + ("" if not rows else " — " + ", ".join(
              f"{r['event_id']} {r['chain']} {r['rule']}" for r in rows[:10])
             + (f" (+{len(rows) - 10} more)" if len(rows) > 10 else "")), flush=True)
    print(f"{OUT.relative_to(REPO)}: branch {live}, "
          f"{d['subset']['replayed_with_evaluation']} events / "
          f"{d['subset']['cycles_total']:,} cycles", flush=True)


if __name__ == "__main__":
    main()
