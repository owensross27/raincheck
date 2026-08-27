"""Notify ticket 10 (spec section 8): the notify decision joins the 30 s live loop, as a
DRY-RUN. Decisions are made, messages are rendered where the renderer will render them,
and NOTHING IS SENT — the loop's own state says what would have gone out.

This module is the seam `live_loop.cycle()` calls: ONE call, ONE `state` field
(`notify`), the same shape flood 15 used to join the flood tick. It stands up no daemon,
opens no socket, and has NO send path and NO credential path at all — arming the notifier
is a later ticket's decision, and a capability that does not exist cannot half-send.

What one call does, on a cycle whose flood tick produced a FRESH detector read:

  * read the ACTIVE subscriptions from ticket 07's store (`notify_store.subscriptions`;
    the SQLite connection is opened once and carried on the state, the loop's own
    warm-connection idiom);
  * build the policy from the artifact the flood tick itself used — `nd.policy(det)`,
    once per cycle, so the branch is READ and never typed;
  * call `nd.decide(read, previous, subs, p, now)` with the loop's OWN clock — the same
    `now` the flood tick was given — and chain the returned Decision as the next cycle's
    `previous`, exactly as the loop chains `fd.cycle`'s state;
  * render `d.messages` and nothing else (a DROP is a ledger row, never a queue) and
    count what rendered. Today `nr.render()` REFUSES every real message because
    `nr.PANEL_URL` and `nr.UNSUBSCRIBE_TO` are unset deployment facts — that refusal is
    the CORRECT dry-run outcome, recorded on the state, not a gap to paper over.

On a cycle whose flood tick skipped, errored or carries no read, the Decision ledgers
are CARRIED untouched and the store is not read at all.

Sized against notify 11's replay (15.33 years, measured): the realistic volume is 0.158
messages per bus-stop subscription per year, quiet hours (22:00-07:00 New York) suppress
every watch-branch message — so a dry-run at night that drops everything is CORRECT —
and the reachable per-cycle maximum is the active subscription count, never
`Decision.worst_case` (the store's ceiling, which overstates). Nothing here needs its
own cap: the fuse and the handle cap live in `nd.decide`.

A failure in any of it is a field on the state, never a raise — the panel beside this
must not stall because a decision refused (`nd.decide` raising on an inconsistent store
row is loud BY DESIGN, and this is the catch its docstring says it belongs inside).
The log line prints on CHANGE only, `Decision.summary()`'s counts — no handle, no token,
no payload — because 2,880 identical quiet lines a day would bury the cycle that moved.
"""
from datetime import datetime
from pathlib import Path

from raincheck import flood_detect as fd
from raincheck import notify_decide as nd
from raincheck import notify_render as nr
from raincheck import notify_store as ns


def dryrun(root: Path, prev: dict | None, flood: dict | None, now: datetime) -> dict:
    """One dry-run pass over this cycle's flood state. Returns the new `notify` state
    (the next cycle's `prev`); never raises."""
    prev = prev or {}
    flood = flood or {}
    state = {"at": now, "decided": False, "why": None,
             "d": prev.get("d"), "summary": prev.get("summary"), "con": prev.get("con"),
             "rendered": 0, "unrendered": 0, "unrendered_reason": None, "error": None}
    if flood.get("error") or flood.get("skipped") or flood.get("read") is None:
        state["why"] = ("flood_error" if flood.get("error")
                        else "flood_skipped" if flood.get("skipped") else "no_read")
        return state
    try:
        con = state["con"] or ns.connect(ns.db_path(root))
        state["con"] = con
        subs = ns.subscriptions(con)
        p = nd.policy(flood.get("det") or fd.constants())
        d = nd.decide(flood["read"], prev.get("d"), subs, p, now)
        for m in d.messages:                     # d.messages ONLY: a drop is never rendered
            try:
                nr.render(m)                     # bytes made and discarded: NOTHING IS SENT
                state["rendered"] += 1
            except Exception as exc:  # noqa: BLE001 - an unrenderable message is a count,
                state["unrendered"] += 1         # not a stalled panel [notify 09's MUST]
                if state["unrendered_reason"] is None:
                    state["unrendered_reason"] = f"{type(exc).__name__}: {str(exc)[:120]}"
        state |= {"decided": True, "d": d, "summary": d.summary()}
    except Exception as exc:  # noqa: BLE001 - a refused decision is a field, never a stop
        state["error"] = f"{type(exc).__name__}: {str(exc)[:200]}"
        if state["error"] != prev.get("error"):
            print(f"notify-dryrun: {state['error']}", flush=True)
        return state
    if state["summary"] != prev.get("summary"):
        print(f"notify-dryrun: {state['summary']} rendered={state['rendered']} "
              f"unrendered={state['unrendered']} NOT SENT (dry-run)", flush=True)
    return state
