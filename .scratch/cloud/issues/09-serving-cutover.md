# T9 — Serving cutover

Status: done (branch cloud09-serving-cutover; +18 tests in tests/test_publish.py)
Type: task
Blocked by: 07
Owns: spec §9.

**live.geojson is BUILT BUT NOT PUBLISHED** — the MTA-terms precondition is unmet.
Ross was asked directly on 2026-08-24 and had not verified them, so
`raincheck.publish.LIVE_TERMS_VERIFIED` is `None` and the live family refuses with
rc 3. The other four families ship. See "Opening the gate" below.

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
| insight exports — `cells.geojson`, `headline.json`, `zones.geojson` | `make export` behind the daily build | per build |
| Great Expectations Data Docs | Airflow task | per run |
| per-asset flood history | flood spine rebuild | per rebuild |
| the page (`index.html`, `app.js`, `app.css`), vendored MapLibre | deploy-time | rare |

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


## Close-out (2026-08-24)

### The public bucket

**`raincheck-public`** — the name cloud 07 had already annotated on the `raincheck-serve`
ServiceAccount, kept rather than renamed, so `deploy/k8s/serviceaccounts.yaml` needed no
edit and `RAINCHECK_R2_SERVE_BUCKET` keeps its frozen value. `tests/test_publish.py` now
asserts `raincheck.publish.PUBLIC_BUCKET` equals that annotation, so renaming either one
alone turns the suite red instead of surfacing as a 403 on the first publish.

The bucket IS the `web/` tree, so the page's relative paths work unchanged:

    index.html · app.js · app.css · vendor/*   deploy-time        family `site`
    files/cells.geojson · headline · zones     per build          family `insight`
    files/live.geojson · files/meta.json       30 s               family `live`  GATED
    files/history/**                           per spine rebuild  family `history`
    docs/**                                    per Airflow run    family `docs`

### Interface

- `python -m raincheck.publish --family <name> [--src DIR] [--bucket B] [--dry-run]`,
  and `make publish FAMILY=<name> [DRY=1]`.
- In-process: `raincheck.publish.publish(name, src=None, dest=None, put=_put)` returns the
  `Item(local, key, cache, content_type)` list it uploaded; `plan(name, src=None)` is the
  same list with no network, no credentials and no s3fs import.
- Exit codes: **0** published · **3** the MTA gate is closed (designed, not a failure) ·
  **1** anything else refused. MEASURED: `make` flattens all of these to its own rc 2, so
  a caller that must tell "gated" from "broken" runs the module, never the make target.
- Transport is **s3fs** (already a dependency — no aws CLI has to exist in the image),
  `endpoint_url` from `AWS_ENDPOINT_URL`, credentials from the `r2-serve` Secret's env.

### [YOU] — create the bucket (Cloudflare dashboard, ~2 minutes)

Nothing publishes until this exists, and it is deliberately not scripted: an R2 bucket and
its public hostname are dashboard steps, like the tokens in ticket 07.

1. R2 → **Create bucket** → name **`raincheck-public`**, location automatic. It must be a
   different bucket from `raincheck-bronze`; `scripts/r2-secrets.sh serve` and
   `raincheck.publish.bucket()` both refuse the archive name outright.
2. Settings → **Public access**: enable the r2.dev subdomain (or attach a custom domain).
   Note the hostname — that is the page's URL.
3. Settings → leave **object versioning OFF** and add **no lifecycle rule**. Rule 1 of the
   live payload is *current snapshot only, no served history*; versioning would quietly
   retain every 30 s snapshot and make the host a history endpoint by configuration.
4. Mint the **serve** token (ticket 07's procedure) scoped to this one bucket, then
   `RAINCHECK_R2_SERVE_BUCKET=raincheck-public scripts/r2-secrets.sh serve --check`.
5. `make publish FAMILY=site` then `make publish FAMILY=insight`. Open the hostname.

### Opening the MTA gate

The three constraints below hold whether or not the gate opens; the gate only decides
whether the payload goes public at all. To open it, replace `None` in
`src/raincheck/publish.py` with the receipt — the date and what was actually read, e.g.
`LIVE_TERMS_VERIFIED = "2026-09-01: <terms document>, §N — derived current-snapshot views
permitted with attribution"` — and run `tests/test_publish.py`, whose first test asserts
the constant is not opened without one.

### How the three constraints are enforced

1. **Current snapshot only** — the live family's two remote keys are literals, so no tick
   can write a dated second copy; the bucket is created without versioning or a lifecycle
   (step 3 above). Pinned by a test that re-plans after the payload changes.
2. **No bulk or protobuf endpoint** — `PUBLISHABLE` is an allowlist of web payload
   suffixes, so a `.pb`, a `.parquet` or a tarball is refused by construction, including
   one that appears inside a directory-tree family later.
3. **MTA attribution on the page** — in the always-visible provenance panel of
   `web/index.html`, not only in MapLibre's compact control, which ships collapsed.

**Families are explicit file lists, never directory syncs**, and that is load-bearing: the
live pair and the insight trio share `web/files/`, so an `aws s3 sync web/files/` would
publish live.geojson on every build, straight past the gate.

**Publish order inside the live family is load-bearing too**: live.geojson first,
meta.json LAST. A publisher that dies mid-pair then leaves a fresh fleet under an older
meta (the page reads STALE — safe), never a fresh meta over an old fleet.

### STALE: a hole found and closed

Moving to a static host exposed a live defect in the page, so this ticket fixed it rather
than porting it. `isStale()` read `vp_age_s`, **a number the exporter computes and freezes
into meta.json**. If the exporter dies — or the publisher does, or a CDN keeps serving a
cached copy — the page re-fetches the same small `vp_age_s` forever and paints a stopped
city as a live one. `metaAge()` now dates the file itself against the browser clock and
adds it, with `Math.max(0, ...)` so clock skew errs stale and an unparseable stamp reading
`Infinity`. Measured in a real browser against a meta written 21 min ago with
`vp_age_s: 20, error: null, stale: false`:

| case | after | before |
|---|---|---|
| exporter frozen 21 min | STALE | **LIVE** |
| bronze frozen 30 min | STALE | **LIVE** |
| unparseable `as_of_utc` | STALE | **LIVE** |
| healthy tick · worst healthy (40 s feed + 33 s meta) | live | live |
| feed dead, exporter alive | STALE | STALE |

`no-cache` on both live keys is the other half: a CDN must not outlive the exporter.

### What this ticket did NOT build, and who owns it

- **The live-export Deployment is cloud 05's** (its ticket: "live-export + the detector
  tick are one supervised Deployment ... publishing to the static host"). It calls
  `publish("live")` in-process on its existing 30 s tick. Today that raises `GateClosed`
  (rc 3) — a no-op to log, not a crash to restart.
- **No manifest, and no cluster rule.** The host is outside the cluster: the `static-host`
  entry in `deploy/cloud/inbound-allowlist.yaml` stays `not-cluster-ingress` and undrawn.
- **`docs` and `history` have no writer yet.** Their sources are declared —
  `<data_root>/gx/data_docs` (orch 08) and `web/files/history/` (notify 05) — and publish
  refuses by naming the owed writer. `--src` overrides either if they land elsewhere.
