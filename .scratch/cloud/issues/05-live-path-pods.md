# T5 — The live path as pods, and its latency knobs

Status: open
Type: task
Blocked by: 01, 03, 07
Owns: spec §5.

## Work

- **precip-live: a CronJob every 5 minutes** (cron's 1-minute granularity is what makes
  300 s expressible), **`concurrencyPolicy: Forbid`** so two ticks can never overlap,
  running `python -m raincheck.precip_live` **unmodified**.
  - **Acceptance is the catch-up contract**: every missing `:00` stamp within MRMS's
    ~25 h retention lands. A latest-only reimplementation silently re-blocks the flood
    replay gate [T11, F12] — which is exactly why the pod runs the module rather than a
    shell equivalent of it.
  - The **2-min and 15-min MRMS products are rejected detector inputs by contract** and
    may never enter `live/precip_cell`'s `:00` series. If ever used, they are a distinct
    feature and table [F11, ADR-0002].
- **live-export + the detector tick are one supervised Deployment**, beside the streaming
  driver, publishing to the static host on the existing 30 s cadence. The panel's two
  halves must never age apart. STALE semantics unchanged [T14].

## Latency knobs — adopted only with a measured win, recorded before/after

| knob | today | note |
|---|---|---|
| streaming trigger | 30 s | 10 s is a config change, not an improvement until measured |
| archiver poll | 30 s | misses ~10-15% of Snapshots [vault feeds ref]; tightening costs Bronze volume — a real trade, priced before taken |

## Tests

`tests/test_precip_live.py::test_live_catchup_lands_missing_hours_once` already pins the
~25 h contract and the CronJob calls the same module, so the contract needs **no new
test**. What is needed is the manifest assertion that the pod really does call the module:
extends `tests/test_cluster_manifests.py` with the CronJob's command **being**
`python -m raincheck.precip_live` and `concurrencyPolicy: Forbid`. That assertion is the
thing standing between this design and a shell one-liner that quietly drops catch-up.
