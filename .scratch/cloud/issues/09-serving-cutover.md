# T9 — Serving cutover

Status: open
Type: task
Blocked by: 07
Owns: spec §9.

## Work

- **A new public bucket** (R2 public bucket or a Pages-class static host) — **never
  `raincheck-bronze`** [T18]. "Public" and "the archive" must never be able to be the
  same mistake. This supersedes the bus map's "public hosting" out-of-scope, for the map
  page only.
- The static host is outside the cluster entirely, which is what keeps ticket 07's "no
  inbound" true while the map is still served.

## Payloads, writers and cadences

| payload | writer | cadence |
|---|---|---|
| `live.geojson` + `meta.json` | live-export Deployment | 30 s |
| insight exports | `make export` behind the daily build | per build |
| Great Expectations Data Docs | Airflow task | per run |
| per-asset flood history | flood spine rebuild | per rebuild |
| `cells.geojson`, vendored MapLibre | deploy-time | rare |

## The `live.geojson` judgement call

It falls on the **derived** side of the MTA line and is published, with three constraints
that keep it a view rather than a feed: **current snapshot only with no served history,
no bulk or protobuf endpoint, and MTA attribution on the page.** It carries per-vehicle
fields and is feed-shaped [T14], so this is a genuine judgement call, not a technicality —
the spec flags it as the decision most worth vetoing.

**Verify MTA's actual redistribution terms before go-live.** The spec does not assert what
they say, and neither does this ticket. That verification is a precondition of shipping,
not a follow-up.

STALE semantics unchanged [T14] — a dead exporter must still look dead, never like a quiet
city.

## Inherited from the wave-1 landing (2026-08-24, recorded by the gate)

- **The network baseline you inherit is verified green**: `make inboundaudit` rc 0
  at the gate (three cluster SGs, every rule allowlisted, zero CIDR sources). The
  static host stays a NAMED NON-INGRESS exception in
  deploy/cloud/inbound-allowlist.yaml `reserved:` — it needs no cluster rule and
  you draw none; the manifest test asserts the reservation stays undrawn.
- **The serve token still does not exist** ([YOU] item): build everything; the
  first publish fails loudly until Ross mints `r2-serve` via cloud 07's procedure.
  `scripts/r2-secrets.sh serve` refuses raincheck-bronze outright; if you rename
  the public bucket, change the `raincheck.io/r2-bucket` annotation in
  deploy/k8s/serviceaccounts.yaml in the same commit.
- **COST RULE (gate sweep)**: the 30 s live.geojson cadence is a standing write
  rate — R2 class-A operations every 30 s is the agreed price, but keep it to the
  ONE small object per tick (no versioning, no history lifecycle, no per-tick
  multipart); insight/history/Docs families publish on their own slower cadences,
  never the 30 s tick.
