"""Cloud ticket 05 / spec section 5: the live path's ONE supervised process.

The panel has two halves - the vehicle fleet (`live_export`) and the flood detector's
coastal/winter read (`flood_live`) - and spec story 28 says they must never age apart.
That is what this module is: one process, one clock, one warm DuckDB connection, ticking

    export  ->  detect  ->  publish

in that order. The Deployment that runs it is the supervision; this is the tick.

Why a loop module rather than three containers or three `python -m` calls in a shell:

  * `publish("live")` is called IN-PROCESS, which is what cloud 09's `publish()` docstring
    asks of this ticket - "an interpreter start every 30 s buys nothing". At 2,880 ticks a
    day an interpreter start, an import graph and a cold DuckDB connection per tick are the
    per-run setup the cost rule bars, paid forever for something the image already holds.
  * Ordering is then free and correct: the tick publishes the pair it just wrote, so
    live.geojson and meta.json go up as the snapshot they came from. Two independent
    loops would eventually publish one half of one tick beside the other half of another.

Nothing here re-implements a tick. `live_export.once()` (its own SQL, its own STALE
rules), `flood_live.live()` and `publish.publish()` are called as they ship; this module
owns only the cadence, the failure policy, and the log line.

FAILURE POLICY - the panel must degrade, never crash:
  * `live_export.once()` never raises by contract; a bad read becomes a stale meta.json.
  * the detector and the publisher are each wrapped: an outage or a closed gate is logged
    and the loop carries on. A dead detector must not stop the fleet from publishing.
  * `GateClosed` (cloud 09 rc 3) is a DESIGNED state, not an error - the MTA terms are
    unverified, so the live pair is written locally and not published. It is logged on
    change only: 2,880 identical lines a day would bury the tick that actually failed.

Run: python -m raincheck.live_loop            (the Deployment's command)
     python -m raincheck.live_loop --once     (one cycle, for a smoke check)
"""
import argparse
import os
import time
from datetime import datetime, timezone
from pathlib import Path

from raincheck import (duck, flood_coastal, flood_live, flood_panel, live_export,
                       notify_dryrun, publish)
from raincheck.live_export import INTERVAL_S
from raincheck.paths import data_root

# The detector's own cadence, and the one number here that is NOT 30 s. CO-OPS publishes
# observations every 6 minutes and KNYC hourly (both measured by flood 14 and recorded in
# flood_live's docstring), so a 30 s poll re-asks two public APIs 12x and 120x per
# publication for an answer that cannot have moved: 2,880 calls a day per gauge instead of
# 240, with a rate-limited 429 rendering as a false OUTAGE chip on the panel. The tick is
# still SUPERVISED at 30 s - a failed detector is seen within one tick - it is only
# re-FETCHED at the source's own rate. Lower it if the detector ever reads something that
# moves faster; there is no reason to raise it.
DETECT_S = 360


def detect(root: Path) -> dict:
    """One detector read, or the reason there wasn't one. Never raises.

    `margins` is the static surge table, which hangs off ref/assets - absent on the
    cluster until ref/ is archived off the Mac ([YOU], cloud 08). flood_live's own
    `--no-margins` path is the supported answer: the recolor set renders empty and the
    gauge chips are unaffected, so a missing margin table costs a layer, not the tier."""
    try:
        margins = flood_coastal.unit_margins(root)
    except Exception as exc:  # noqa: BLE001 - no ref/assets is a thinner panel, not a stop
        margins = None
        print(f"live-loop: no margin table ({type(exc).__name__}) - recolor set empty",
              flush=True)
    try:
        return flood_live.live(margins=margins)
    except Exception as exc:  # noqa: BLE001 - an API outage is a chip, never a crash
        return {"error": f"{type(exc).__name__}: {str(exc)[:200]}"}


def ship(out_dir: Path, state: dict) -> str:
    """Publish the live pair THIS loop just wrote. Returns the word for the log; never
    raises.

    `src=out_dir` rather than the family's default: the loop must publish the pair it
    wrote, or `--out` silently ships whatever is in the repo's web/files instead.

    `state` carries the last outcome so a closed gate is logged once rather than 2,880
    times a day - the gate is a standing condition, and a line per tick would hide the
    tick that genuinely broke."""
    try:
        items = publish.publish("live", src=out_dir)
        return f"published {len(items)}"
    except publish.GateClosed as exc:
        if state.get("publish") != "gated":
            print(f"live-loop: publish gated (rc 3, designed) - {exc}", flush=True)
        return "gated"
    except Exception as exc:  # noqa: BLE001 - a failed upload is a stale page, not a stop
        return f"failed {type(exc).__name__}: {str(exc)[:120]}"


def cycle(con, root: Path, out_dir: Path, source: str, state: dict,
          now: datetime | None = None) -> dict:
    """One export -> detect -> publish cycle. Returns the new state (also the log line's
    source), which carries `prev` for live_export's stale-carrying meta."""
    now = now or datetime.now(timezone.utc)
    meta = live_export.once(con, root, out_dir, source, state.get("meta"), now)
    due = state.get("detected_at") is None or (now - state["detected_at"]).total_seconds() >= DETECT_S
    detected = detect(root) if due else state.get("detector")
    # flood 15's tick JOINS this loop rather than standing a second daemon up beside it:
    # one process, one clock, one warm connection, so the panel's halves cannot age apart.
    # It skips itself unless the forcing advanced or its own truth throttle expired, and it
    # never raises - an outage comes back as a field on its state, exactly like the two
    # above. It is handed the detector read this cycle already has, so the winter gate's
    # KNYC temperature and the coastal chips cost no second fetch of the same endpoints.
    flood = flood_panel.tick(con, root, out_dir, state.get("flood"), now, detected)
    # notify 10: the decision rides THIS cycle's flood read as a DRY-RUN - one call, one
    # state field, the same clock. Decisions are made and rendered where the renderer
    # will; NOTHING IS SENT, and the seam owns its own failure policy (never raises).
    notify = notify_dryrun.dryrun(root, state.get("notify"), flood, now)
    return {"meta": meta, "detector": detected,
            "detected_at": now if due else state.get("detected_at"),
            "flood": flood, "notify": notify,
            "publish": ship(out_dir, state), "at": now}


def line(state: dict) -> str:
    meta, det = state["meta"], state.get("detector") or {}
    coastal = det.get("coastal") or {}
    return (f"{meta.get('as_of_utc')} n={meta.get('n_vehicles')} "
            f"vp_age_s={meta.get('vp_age_s')} error={meta.get('error')} "
            f"coastal={coastal.get('stage') or det.get('error')} "
            f"winter={(det.get('winter') or {}).get('status')} "
            f"publish={state['publish']} {flood_panel.line(state.get('flood') or {})}")


def loop(root: Path, out_dir: Path, source: str, interval: float = INTERVAL_S,
         once_only: bool = False) -> dict:
    """The foreground loop. One DuckDB connection for the life of the pod, as
    live_export.loop() does - the read is the same read, so the warm connection is too."""
    con = duck.connect()
    state: dict = {}
    while True:
        state = cycle(con, root, out_dir, source, state)
        print(line(state), flush=True)
        if once_only:
            return state
        time.sleep(interval)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--source", choices=sorted(live_export.SOURCES),
                    default=os.environ.get("SOURCE") or "live")
    ap.add_argument("--once", action="store_true", default=bool(os.environ.get("ONCE")),
                    help="one cycle, then exit")
    ap.add_argument("--out", type=Path, default=live_export.OUT)
    args = ap.parse_args()
    root = data_root()
    print(f"live-loop: root={root} source={args.source} export={INTERVAL_S}s "
          f"detect={DETECT_S}s -> {args.out} (Ctrl-C stops)", flush=True)
    try:
        loop(root, args.out, args.source, once_only=args.once)
    except KeyboardInterrupt:
        print("live-loop: stopped", flush=True)


if __name__ == "__main__":
    main()
