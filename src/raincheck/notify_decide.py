"""Notify ticket 08 (spec section 6; SEAM N): the notify decision as ONE pure function.

Given the detector's current read, this function's own previous return, the active
subscriptions, the policy and an injected `now`, `decide()` returns the Messages that
should exist. It opens no socket, no database and no file, and it never reads a clock —
which is what lets ticket 11 replay it over history and ticket 12 rehearse every branch on
a fixture instead of waiting for a Tuesday at 3am.

TWO BRANCHES SHIP FROM THE SAME FUNCTION, AND WHICH ONE IS READ FROM THE ARTIFACT.

  * TIER — notify on tier ENTRY. flood 11's LATCH is the dedupe and nothing here
    reimplements it: a tier cannot fall inside a Window, so "the latched tier moved up
    since the previous evaluation" fires ONCE per Unit per Window by construction. A
    downward series revision is LOGGED by the detector and never clears a flag.
  * WATCH — the rank-only branch. The rank is re-normalised every cycle and has NO latch,
    so this branch carries its own dedupe keyed on (unit, window_id), and it has to
    RE-APPLY the two gates the tier branch gets for free: on a dry afternoon something is
    always the maximum of a vector, and the winter gate zeroes `tier` while leaving `rank`
    untouched.

`branch()` reads `cutpoints.provisional` out of flood 11's artifact. It is never re-typed
here, because the verdict is Ross's to record (flood 12 replayed 133 events / 4,326 cycles
and RECOMMENDED rank-only; the flag still says provisional). Absence is WATCH: the
conservative branch is the fail-safe one, and holding the notify path is an acceptable
outcome — this function never manufactures confidence the backtest refused.

WHAT IS SILENT, AND WHY EACH ONE IS CHECKED HERE RATHER THAN INHERITED:

  * version skew (`fd.skew` refuses on skew AND on an absent table stamp) — `cycle()`
    REPORTS the refusal and does not act on it, so a refused cycle sends nothing only
    because this function says so;
  * INSUFFICIENT_DATA / WINDOW_CAPPED — silence means "we do not know", never "it is fine";
  * the winter gate — it zeroes every `tier` but not one `rank`, so WATCH would notify
    straight through a snowstorm if this were left to the payload.

Staleness is deliberately NOT a refusal: the panel renders it [F15] and the tiers are
still what the rain that fell says.

Volumes this policy is sized against (flood 12's replay, measured): at ELEVATED+ a firing
event flags ~2,000 bus stops AT ONCE and 96 of 133 events flag none at all, so the fuse is
sized for the burst and not the average.

Nothing in here renders a string. Ticket 09 owns every word a subscriber reads.
"""
from dataclasses import dataclass, field, replace
from datetime import datetime
from types import MappingProxyType
from typing import Mapping, Sequence
from zoneinfo import ZoneInfo

from raincheck import flood_detect as fd
from raincheck import notify_store as ns

TIER, WATCH = "tier", "watch"
BRANCHES = (TIER, WATCH)

# Why a whole cycle sent nothing. Derived from the detector's own vocabulary, never
# re-spelled: the window states are `fd.OK`/`fd.INSUFFICIENT_DATA`/`fd.WINDOW_CAPPED`.
SKEW, WINTER = "version_skew", "winter_gate"
REASONS = (SKEW, WINTER, fd.INSUFFICIENT_DATA.lower(), fd.WINDOW_CAPPED.lower())

# Why ONE message that was owed did not get sent. Every drop lands in `Decision.drops`.
QUIET, HANDLE_CAP, CYCLE_FUSE = "quiet_hours", "handle_cap", "cycle_fuse"
DROPS = (QUIET, HANDLE_CAP, CYCLE_FUSE)


@dataclass(frozen=True)
class Policy:
    """The policy constants in ONE frozen place — never scattered literals.

    `branch` and `own_cell_window_mm` are deliberately NOT given values here: they are
    READ from flood 11's artifact by `policy(det)`, and a Policy that still carries None
    is refused by `decide()` so that no caller can silently ship the wrong branch.
    """

    branch: str | None = None
    own_cell_window_mm: float | None = None

    # flood 11's own sentence, read from `display` and never re-worded here. It rides on
    # every message whose number is an aggregate of doorway scores rather than a
    # measurement, so ticket 09 can neither forget it nor paraphrase it.
    no_complex_skill_claim: str | None = None

    # HIGH always notifies; every tier below it needs the per-subscription opt-in.
    notifying_tiers: tuple[str, ...] = (fd.ELEVATED, fd.HIGH)

    # WATCH's cut is a COUNT and not a percentage, which is the whole difference: a rank
    # spends the same ~10% of the city on a storm that floods nothing as on one that
    # floods everywhere (flood 12), while a count cannot. Each N is far under the alert
    # rate flood 12 measured for that kind's HIGH cut — bus_stop 2.89% of 13,370 stops is
    # 386 and complex 2.22% of 445 is 10 — so the watch branch is the TIGHTEST cut on the
    # table, not a loosened one. A kind absent from here can never notify: `cell` is not
    # subscribable and an entrance publishes no live number at all.
    watch_top_n: Mapping[str, int] = MappingProxyType({"bus_stop": 25, "complex": 5})

    # Local hours [start, end), and the zone they are local TO — `fd.NY`, the detector's
    # own, never a second spelling of "America/New_York". Quiet hours DROP rather than
    # defer (spec section 6's DEFAULT): an hour-grain alert delivered hours late is worse
    # than no alert. HIGH is never suppressed by them.
    quiet_hours: tuple[int, int] = (22, 7)
    quiet_hours_tz: ZoneInfo = fd.NY

    # Per handle, per Window ("per event"). The store already refuses a handle past
    # MAX_PER_HANDLE subscriptions, so this cap is that same ceiling read from the store —
    # one message per subscription per event, and an escalation ELEVATED -> HIGH is what
    # can push a handle past it.
    per_handle_event_cap: int = ns.MAX_PER_HANDLE

    # The blast-radius fuse, per cycle, across every handle. A Unit fires at most once per
    # cycle, so a cycle can legitimately send at most one message per SUBSCRIPTION — and
    # the managed list's own stated ceiling is `INGRESS_TRIGGER_ENTRIES` entries, past
    # which ticket 07's deferred ingress reopens. So the fuse is exactly that ceiling: a
    # cycle that wants to send more than the list is allowed to hold is a defect or a list
    # that outgrew v1, and either way the right answer is to stop and log it. The worst
    # case this is checked against is published on every Decision (`worst_case` =
    # handles x MAX_PER_HANDLE).
    per_cycle_fuse: int = ns.INGRESS_TRIGGER_ENTRIES


POLICY = Policy()


@dataclass(frozen=True)
class Message:
    """One message that should exist. Ticket 09 renders it; this carries no prose.

    `no_skill_claim` is flood 11's own sentence, verbatim from the artifact, and it is
    present on exactly the kinds whose number is an aggregate rather than a measurement —
    a complex score is the max over its child doorway scores and the independent
    complex-grain set caught 1 of 118. A renderer that ignores it words a claim the
    artifact refuses to make.
    """

    handle: str
    asset_id: str
    asset_kind: str
    branch: str
    tier: str | None          # a member of fd.TIERS on the tier branch; None in watch mode
    rank: float
    top_n: int | None         # the N in force in watch mode; None on the tier branch
    window_id: str
    anchor: str
    now: datetime
    unsubscribe_token: str
    score_version: str
    detector_version: str
    no_skill_claim: str | None = None


@dataclass(frozen=True)
class Decision:
    """What this cycle decided, and the state the next cycle needs.

    It is its own `previous`: a caller chains it exactly as `live_loop` chains
    `fd.cycle`'s return, and the three ledgers below are what a rank cannot hold.
    """

    messages: tuple[Message, ...] = ()
    drops: tuple[dict, ...] = ()
    branch: str = WATCH
    reason: str | None = None            # why the whole cycle was silent, or None
    window_id: str | None = None
    worst_case: int = 0                  # handles x MAX_PER_HANDLE, the fuse's ceiling
    latched: Mapping[str, str] = field(default_factory=dict)   # the evaluation it saw
    watched: tuple[str, ...] = ()        # Units already entered top-N this Window
    sent: Mapping[str, int] = field(default_factory=dict)      # messages per handle

    def summary(self) -> dict:
        """The line ticket 10 logs: counts only, no handle and no payload."""
        return {"branch": self.branch, "reason": self.reason, "window_id": self.window_id,
                "messages": len(self.messages), "drops": len(self.drops),
                "dropped": {r: sum(1 for d in self.drops if d["reason"] == r)
                            for r in DROPS if any(d["reason"] == r for d in self.drops)},
                "worst_case": self.worst_case}


def branch(det: Mapping) -> str:
    """TIER or WATCH, READ from flood 11's artifact and never re-typed here.

    `cutpoints.provisional` is the switch. `display.cutpoints_confirmed_by` names WHO
    confirms and is populated long before any verdict exists, so it is an audit trail and
    never the test. A missing flag is WATCH: the conservative branch is the fail-safe one.
    """
    return TIER if det.get("cutpoints", {}).get("provisional", True) is False else WATCH


def policy(det: Mapping, **overrides) -> Policy:
    """THE policy for a cycle: the frozen constants, plus the two values read from the
    artifact — which branch v1 ships, and the own-Cell rain gate the watch branch has to
    re-apply itself. Going through here is what makes shipping the wrong branch impossible
    to do quietly."""
    p = replace(POLICY, branch=branch(det),
                own_cell_window_mm=float(det["gates"]["own_cell_window_mm"]),
                no_complex_skill_claim=det["display"]["no_complex_skill_claim"], **overrides)
    if p.branch not in BRANCHES:
        raise ValueError(f"{p.branch} is not one of {BRANCHES}")
    if not set(p.notifying_tiers) <= set(fd.TIERS) or fd.NONE in p.notifying_tiers:
        raise ValueError(f"{p.notifying_tiers} is not a subset of {fd.TIERS[1:]}")
    return p


def window_id(current: Mapping) -> str | None:
    """The Window's identity: exactly the three fields `fd.rolled` compares, so this key
    rolls when and only when the detector's Window rolls — a new anchor, a coefficient
    swap or a changed detector rule. None when there is no Window to identify."""
    anchor = current.get("anchor")
    if not anchor:
        return None
    return f"{anchor}|{current['score_version']}|{current['detector_version']}"


def silent(current: Mapping) -> str | None:
    """The reason this cycle must send nothing, or None. Checked in this order because a
    refused model is a refusal about everything downstream of it."""
    if current.get("skew", {}).get("model_tier") != "ok":
        return SKEW
    state = current.get("window", {}).get("state")
    if state != fd.OK:
        return str(state).lower()
    if (current.get("winter") or {}).get("suppressed"):
        return WINTER
    return None


def in_quiet_hours(now: datetime, hours: tuple[int, int], tz: ZoneInfo = fd.NY) -> bool:
    """Local-hour test in the policy's zone, which is the detector's own. A naive `now` is
    refused rather than assumed to be local — the clock is an argument here precisely so
    that nothing has to guess which one it is."""
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware: the clock is an injected argument")
    start, end = hours
    h = now.astimezone(tz).hour
    return (h >= start or h < end) if start > end else (start <= h < end)


def gated(unit: Mapping, own_cell_mm: float) -> bool:
    """flood 11's two live gates, read off the row the detector published: the Unit's own
    Cell took at least the artifact's own-Cell total this Window, and the city is actively
    raining. The tier branch has these ANDed into `tier` already; the watch branch reads a
    RANK, which has neither."""
    return bool(unit["gate_citywide_active"]) and float(unit["gate_own_cell_mm"]) >= own_cell_mm


def top_n(units: Sequence[Mapping], p: Policy) -> dict[str, str]:
    """The N highest-ranked GATED Units of each kind in the current vector, {asset_id:
    kind}. Gating first is what keeps a dry afternoon from having a top N at all."""
    out: dict[str, str] = {}
    for kind, n in p.watch_top_n.items():
        grp = sorted((u for u in units if u["kind"] == kind and gated(u, p.own_cell_window_mm)),
                     key=lambda u: (-float(u["rank"]), u["asset_id"]))
        out |= {u["asset_id"]: kind for u in grp[:n]}
    return out


def entries(current: Mapping, previous: Decision, p: Policy) -> dict[str, Mapping]:
    """The Units that CROSSED into notifying territory this cycle, {asset_id: unit row}.

    Tier branch: the latched tier moved up since the previous evaluation. Because a tier
    cannot fall inside a Window, this is flood 11's latch used as the dedupe rather than a
    second copy of it. Watch branch: first entry into the top N this Window, keyed on
    (unit, window_id) because the rank is not stateful.
    """
    units = current.get("units") or []
    if p.branch == TIER:
        was = dict(previous.latched)
        return {u["asset_id"]: u for u in units
                if u["tier"] in p.notifying_tiers
                and fd.TIERS.index(u["tier"]) > fd.TIERS.index(was.get(u["asset_id"], fd.NONE))}
    seen, top = set(previous.watched), top_n(units, p)
    return {u["asset_id"]: u for u in units
            if u["asset_id"] in top and u["asset_id"] not in seen}


def decide(current: Mapping, previous: Decision | None, subscriptions: Sequence[Mapping],
           p: Policy, now: datetime) -> Decision:
    """SEAM N. The current detector read, this function's previous return, the ACTIVE
    subscriptions (`notify_store.subscriptions(con)`, read by the caller — this opens no
    database), the policy and an injected clock, in; the Messages that should exist, out.

    The ledgers record the ENTRY and not the send, so a message the quiet hours or a cap
    dropped is DROPPED — it is logged in `drops` and never quietly retried on the next
    cycle, which would be the deferral this policy specifically rejects.
    """
    if p.branch is None or p.own_cell_window_mm is None:
        raise ValueError("build the policy with policy(det): the branch and the own-Cell "
                         "gate are READ from flood 11's artifact, never typed at a call site")
    for s in subscriptions:
        # The trust boundary: these rows decide who gets mail. `notify_store.subscriptions`
        # already hands back ACTIVE Unit-grain rows only, so a row outside that is an
        # inconsistent store and not a subscriber to skip quietly. The refusal names the
        # ASSET and never the handle — a raised message reaches a log.
        if s["state"] != ns.STATES[0] or s["asset_kind"] not in ns.KINDS:
            raise ValueError(f"subscription for {s['asset_id']} is {s['state']} at "
                             f"{s['asset_kind']} grain: active {ns.KINDS} rows only")
    prev = previous if previous is not None else Decision()
    wid = window_id(current)
    # ONE roll signal, and it is the same triple `fd.rolled` compares. A cycle with no
    # Window (INSUFFICIENT_DATA) has no identity, so its ledgers are CARRIED rather than
    # cleared: an outage is not an event boundary.
    same = wid is None or wid == prev.window_id
    carried = Decision(branch=p.branch, window_id=wid if wid is not None else prev.window_id,
                       latched=dict(prev.latched) if same else {},
                       watched=prev.watched if same else (),
                       sent=dict(prev.sent) if same else {},
                       worst_case=len({s["handle"] for s in subscriptions}) * ns.MAX_PER_HANDLE)

    reason = silent(current)
    if reason is not None:
        if reason not in REASONS:                      # a new detector state, unhandled
            raise ValueError(f"{reason} is not one of {REASONS}")
        return replace(carried, reason=reason)

    entered = entries(current, carried, p)
    by_asset: dict[str, list[dict]] = {}
    for s in subscriptions:
        by_asset.setdefault(s["asset_id"], []).append(s)

    messages: list[Message] = []
    drops: list[dict] = []
    sent = dict(carried.sent)
    for asset_id, unit in ((a, entered[a]) for a in sorted(entered)):
        for s in sorted(by_asset.get(asset_id, ()), key=lambda r: r["handle"]):
            tier = unit["tier"] if p.branch == TIER else None
            urgent = tier == fd.HIGH
            if not urgent and p.branch == TIER and not s["elevated_optin"]:
                continue                               # not subscribed to this loudness
            drop = None
            if not urgent and in_quiet_hours(now, p.quiet_hours, p.quiet_hours_tz):
                drop = QUIET
            elif sent.get(s["handle"], 0) >= p.per_handle_event_cap:
                drop = HANDLE_CAP
            elif len(messages) >= p.per_cycle_fuse:
                drop = CYCLE_FUSE
            if drop is not None:
                drops.append({"handle": s["handle"], "asset_id": asset_id,
                              "asset_kind": s["asset_kind"], "branch": p.branch,
                              "tier": tier, "reason": drop})
                continue
            messages.append(Message(
                handle=s["handle"], asset_id=asset_id, asset_kind=s["asset_kind"],
                branch=p.branch, tier=tier, rank=float(unit["rank"]),
                top_n=None if p.branch == TIER else p.watch_top_n.get(unit["kind"]),
                window_id=wid, anchor=current["anchor"], now=now,
                unsubscribe_token=s["unsubscribe_token"],
                score_version=current["score_version"],
                detector_version=current["detector_version"],
                no_skill_claim=p.no_complex_skill_claim if unit["kind"] == "complex" else None))
            sent[s["handle"]] = sent.get(s["handle"], 0) + 1

    return replace(carried, messages=tuple(messages), drops=tuple(drops), sent=sent,
                   latched=dict(current.get("latched") or {}),
                   watched=tuple(sorted(set(carried.watched) | set(entered))))
