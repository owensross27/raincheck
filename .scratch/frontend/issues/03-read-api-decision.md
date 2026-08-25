# 03 — The unified read API: does anything beyond the static contract earn its place?

Type: grilling
Status: resolved
Blocked by: 04

## The question

Ross wants "an api we could leverage that integrates all of this info into one
that could feed some alerting and other apps we want to create in the future".
The cheap observation: once notify 05 lands, the public bucket IS a read API —
versioned-by-build JSON at stable keys (per-asset history, insight, live pair),
all public-mode by construction, licence boundary already enforced upstream by
SEAM Q. The question is what, if anything, sits on top:

- Is the DOCUMENTED STATIC CONTRACT (stable keys + payload schemas + stamps)
  the v1 API — zero new components, consumable by any future app today?
- Does a THIN EDGE WORKER over `raincheck-public` earn a place (ticket 04's
  research supplies the facts: free-tier limits, caching, CORS, custom domain)
  — e.g. for key aggregation ("give me stop X's history + current tier in one
  call"), CORS headers the bucket cannot set, or rate limiting?
- HARD CONSTRAINTS already frozen: never cluster ingress (no inbound is a
  tested invariant); public mode only (a hosted surface may never set local
  mode — notify 06's rule); no SQL passthrough (permanent); no bulk/protobuf
  endpoint for live (spec §9); Cell ids as H3 hex strings.
- In-repo ALERTING does not wait on this: notify 08/10 run in-process on the
  30 s loop. This API serves EXTERNAL/future consumers only — say so in the
  answer so nobody routes the notifier through HTTP.

## Resolution shape

A decision: static-contract-only vs static + named Worker duties, with the
consumer list it serves, recorded here and gisted on the map. If a Worker is
in, the answer names what it does and explicitly what it refuses; the build
belongs downstream of the map.

---

## Answer

**STATIC-ONLY. No Worker, now or on the currently-known consumer list.** The v1 read
API is the DOCUMENTED STATIC CONTRACT on `raincheck-public` — the five families that
already exist in code at `src/raincheck/publish.py:120-149`, plus one new discovery
file. Zero new components, zero new deploy surface, zero new bill. Ross accepted all
six recommendations in one round on 2026-08-24.

### The contract IS `FAMILIES` — it was never hypothetical

| family | keys | cadence | Cache-Control |
|---|---|---|---|
| `site` | `index.html`, `app.js`, `app.css`, `vendor/*` | deploy-time | `public, max-age=86400` |
| `insight` | `files/cells.geojson`, `files/headline.json`, `files/zones.geojson` | per build | `public, max-age=300` |
| `live` | `files/live.geojson`, `files/meta.json` | 30 s | `no-cache` — **MTA-GATED, dark** |
| `history` | `files/history/**` (notify 05: 7,955 files, ~10.9 MB) | per spine rebuild | `public, max-age=300` |
| `docs` | `docs/**` | per Airflow run | `public, max-age=300` |

Stable keys, explicit file lists (never a directory sync — `publish.py:20-25`), stamps
resolved before any payload exists (SEAM Q's envelope, `query.py`), licence boundary
enforced upstream. That is an API. The only thing it lacked was a way to discover
itself, which is D3 below.

### D1 — Three of the four candidate Worker duties are dead on the research's own facts

Priced against `.scratch/frontend/research/04-worker-r2.md`, not against intuition:

1. **CORS — killed.** A public R2 bucket sets CORS itself; it is a bucket-level policy
   (`wrangler r2 bucket cors set <BUCKET> --file cors.json`), and the docs confirm
   custom domains "automatically return CORS response headers for cross-origin
   requests." No Worker injects anything. And for consumer zero it is moot regardless:
   the bucket IS the `web/` tree (`publish.py:11`), so the page's own fetches are
   same-origin. CORS matters only for a DIFFERENT origin — an external app — and it is
   a dashboard toggle there too.
2. **Rate limiting — killed.** WAF Rate limiting rules are available on the **Free**
   plan: 1 rule, counting characteristic IP (no auth signal required), 10 s counting
   period, 10 s mitigation timeout, with Path and Verified Bot available in the
   expression. It sits at Cloudflare's edge AHEAD of origin. This is a platform
   feature, not application code — a Worker implementing it would be strictly worse
   and strictly more expensive.
3. **Compression — killed, and it cuts AGAINST the Worker.** See D2.

The fourth, **aggregation**, is D4.

### D2 — The compression fact is a reason NOT to reach for a Worker

`publish._put()` forwards exactly `ContentType` and `CacheControl` to `put_object`
(`publish.py:225-226`); there is no `ContentEncoding` anywhere in the repo. First
paint as published today is **3,661,475 RAW bytes vs ~738 KB gzipped** — a 5x gap,
and frontend 01 correctly refused to write a byte budget denominated in a unit this
deployment does not produce.

The Worker looks like the fix and is not. The research is explicit on the mechanics:
Cloudflare's edge cache **fronts a custom-domain public bucket automatically** (a
cache hit never reaches R2, costs zero R2 operations and zero Workers requests), and
**never fronts a Worker automatically** — "when a request arrives, it hits the Worker
before the cache is checked." Every request through a Worker is a billable invocation
plus a Class B operation on the binding read, and skipping the R2 read on a repeat
request requires the Worker to hand-implement Cache API get/put, which is itself a
no-op unless the Worker is on a custom domain. **Putting a Worker in front to
compress trades an automatic free cache for a billable invocation per request.**

Two real fixes, in this order:

- **(a) MEASURE FIRST.** One `curl -sI -H 'Accept-Encoding: gzip' <object-url>`
  against a published object on the custom domain, recording whether
  `Content-Encoding: gzip` comes back. Already a [YOU] item in `STATUS.md` from
  frontend 01; this ticket makes it a precondition of (b) rather than a curiosity.
  If the edge compresses, (b) is dead weight and must not be written.
- **(b) FALLBACK, only if (a) comes back negative: gzip in `_put` and pass
  `ContentEncoding="gzip"`.** A one-kwarg change at `publish.py:226`, in-repo, no new
  component, and it KEEPS the edge cache. It does **not** break
  `tests/test_export.py:284 test_re_export_is_byte_identical` — that test asserts
  LOCAL export bytes, and the compression happens on the wire; the local file is
  untouched.
  **Named cost of (b):** pre-compression is UNCONDITIONAL, not negotiated. A client
  that does not send `Accept-Encoding: gzip` receives a body it cannot read. Every
  browser and every `fetch` sends it; a naive `curl` does not. If that matters to a
  consumer, that is an argument for (a) or for leaving it raw — never for a Worker.

**Neither path is a reason to build a Worker. This is closed; do not re-open it on
page-weight grounds.**

### D3 — The one thing added: `files/index.json`, the contract's discovery document

Ross's ask was "an api we could leverage that integrates all of this info into **one**."
Until now "the API" was tribal knowledge inside a Python dict. A consumer — including
an agent, which the project's destination names explicitly — had to be TOLD the keys.

**Add one static file, `files/index.json`, written by the same exporter that writes
everything else.** It lists every family: key, content-type, cadence, a pointer to the
payload's schema, and the version stamps. It is a file, not a component: no runtime,
no deploy surface, no bill, and it publishes through the existing `insight` path or
its own trivially-added family.

**It also carries `contract`, an integer.** Static keys have no `/v1/` segment, so
without this a schema change to `cells.geojson` breaks an external app silently. The
integer bumps on a breaking change, which lets a consumer **refuse rather than
misread**. The KEYS themselves stay unversioned — the page is consumer zero and always
deploys together with its payloads, so versioned keys would buy nothing and double the
surface.

### D4 — Aggregation: two fetches, and the build-time merge is REFUSED

"Give me stop X's history + current tier in one call" is the only duty that survived to
be priced. It does not earn a Worker:

- **The Worker path:** 1 billable invocation + 2 Class B operations per request, with
  no automatic edge cache in front of any of it.
- **The static path:** 2 parallel fetches to the same origin, both edge-cached for
  free, both already covered by frontend 01's payload rule ("paint from ONE bulk layer
  file; detail from ONE per-asset fetch on click"). Sized on the tail, not the median:
  notify 05's per-asset max is 23,444 B (`cell:882a1062d5fffff`, 73 events).

**The build-time merge is REFUSED, not merely not-chosen.** Folding the current flood
tier into notify 05's per-asset history file would freeze a 30 s-cadence value into a
per-spine-rebuild file. It reads as a performance win and is the `frozen-age-is-not-an-age`
trap: a staleness-bearing number that stops advancing the moment its writer's cadence
diverges from its reader's expectation. Two files, two cadences, two fetches, each dated
by the READER off HTTP response headers (frontend 01's rule: `Date` − `Last-Modified`
on the origin's clock, never a new payload stamp).

### D5 — Consumers

The v1 read API serves **EXTERNAL and FUTURE consumers**, four of them:

1. **The raincheck map page itself** (`web/index.html`, extended to seven toggled
   layers by frontend 01 / 02) — consumer zero, already consumes exactly this contract
   over relative paths.
2. **Ross's future external apps** — browser or server, over the custom domain.
3. **Agents querying the dataset** — the project's stated end state; `files/index.json`
   is what makes this work without a human in the loop.
4. **orch 13's showcase** — static Data Docs / DAG graph / walkthrough, reading
   `docs/**`.

**NOT a consumer, stated here so nobody wires it later: in-repo alerting.** notify
08/10/12 own the decision function and the notifier and run **in-process on the 30 s
loop**. They must never route through HTTP. Nothing in this contract is on the
notifier's path, and an HTTP hop there would add a network failure mode to a loop that
currently has none.

### D6 — What the API REFUSES

Frozen, not re-litigable, and each refusal is structural rather than remembered:

- **No cluster ingress, ever.** The cluster accepts no inbound — a TESTED invariant, no
  LoadBalancer and no NodePort. The bucket lives OUTSIDE the cluster and is the named
  `static-host` reservation in `deploy/cloud/inbound-allowlist.yaml`. Any API is
  edge/static or it does not exist.
- **Public mode only.** A hosted surface may never set `local` mode (notify 06's rule).
  `public` is `MODES[0]` and the default; `local` ships the observation ROWS and is the
  licence boundary.
- **No SQL passthrough.** Permanent. There is no query language on a static contract at
  all — no query parameters, no filters, no server-side selection. Consumers filter
  client-side over the bulk layer files.
- **No bulk or protobuf endpoint, and no served history for live** (spec §9).
  `PUBLISHABLE` is an allowlist of web payload suffixes, so `.pb`/`.parquet`/tarballs
  are refused by construction. The live family's two keys are literals, so no tick can
  write a dated second copy — and bucket versioning stays OFF with no lifecycle rule,
  because versioning alone would silently turn the host into the served history §9
  forbids, without a line of code changing.
- **No write path, no subscribe endpoint, no auth, no keys, no per-consumer anything.**
  These are the only duties a Worker would genuinely earn, and every one of them is
  already barred by a frozen constraint. That is why the answer is static-only rather
  than static-for-now.
- **A Cell id crosses this boundary as its H3 HEX STRING** (`format(cell, "x")`), never
  the int64 — 613229535722209279 is past 2^53 and a JSON reader using doubles corrupts
  it silently.
- **No re-serving of raw MTA feeds.** `live.geojson` is a derived current-snapshot view
  and stays GATED (`LIVE_TERMS_VERIFIED is None`, rc 3) until Ross records a terms
  receipt.

### D7 — The load-bearing precondition: a CUSTOM DOMAIN

**The entire static-only case rests on the bucket sitting behind a custom domain, and
this is a [YOU] step that is not yet decided.** On `r2.dev`, Cloudflare documents: no
caching, no WAF (so **no rate limiting** — D1.2 evaporates), no bot management, public
access "rate-limited and should only be used for development purposes," explicitly
"intended for non-production traffic," and do not CNAME a hostname onto it
("unsupported").

The research found **no page stating that either R2 Custom Domains or Workers Custom
Domains requires a paid plan** — both are gated only by "the domain must be an active
Cloudflare zone in the same account," and a Cloudflare zone has a free plan.

If no suitable domain is owned, the real choice is "register one" vs "accept an
uncached, Cloudflare-rate-limited dev endpoint." **It is still not "add a Worker"** — a
Worker on `*.workers.dev` has a documented no-op Cache API and rescues nothing.

### What was killed, and why it stays killed

1. **A thin edge Worker for CORS** — the bucket does CORS itself; the page is
   same-origin anyway.
2. **A Worker for rate limiting** — free-plan WAF does it at the edge, ahead of origin,
   without auth.
3. **A Worker to compress** — trades the automatic edge cache for a billable
   invocation per request. Compression is either free at the edge (measure it) or a
   one-kwarg `publish.py` change.
4. **A Worker for key aggregation** — 2 free cached fetches beat 1 uncached billable
   invocation doing 2 Class B reads.
5. **A Worker for prettier URLs** (`/v1/assets/{id}` over `files/history/{id}.json`) —
   cosmetics; the static keys are already stable.
6. **Build-time merge of the live tier into per-asset history** — the
   `frozen-age-is-not-an-age` trap (D4).
7. **Versioned key prefixes** (`/v1/...`) — the page deploys with its payloads; the
   `contract` integer in `index.json` does the job for one file instead of every key.

### MUSTs this decision hands forward

- **[YOU] / whoever creates `raincheck-public`: attach a CUSTOM DOMAIN, not just the
  r2.dev subdomain.** Without it there is no edge cache and no WAF rate limiting, and
  two of this answer's load-bearing legs are gone. Free on a Cloudflare Free zone per
  the research. Recorded as an amendment to the existing bucket [YOU] item.
- **[YOU]: after the bucket exists, set the bucket CORS policy** (`wrangler r2 bucket
  cors set raincheck-public --file cors.json`) — needed by external consumers only, but
  it is the same 2-minute dashboard visit.
- **[YOU]: configure the ONE free WAF rate-limiting rule** (IP-keyed, 10 s/10 s). It is
  the only abuse control a public bucket gets, and it costs nothing.
- **[YOU]: run the `Accept-Encoding: gzip` curl BEFORE anyone writes gzip into
  `publish.py`.** Order is load-bearing (D2).
- ~~**notify 05 MUST also write `files/index.json`**~~ — **RETIRED 2026-08-25 by
  frontend 06 (`8bd82db`), which BUILT it. `raincheck.contract` renders the file inside
  the same `make export` run that writes the insight trio; notify 05 must NOT write a
  second copy, because two writers on one key is exactly the drift the single-renderer
  rule exists to prevent.** What notify 05 inherits instead is on its runbook summary
  line: its `history` TREE is frozen in the contract as a PREFIX (`files/history/**`), so
  adding or resharding files inside it is additive and owes no bump, while renaming the
  prefix or re-homing the family is breaking; and the stamps in `index.json` are the same
  `query.versions(con, root)` three it already resolves.
- ~~**`publish.py` MUST gain the family that publishes `index.json`**~~ — **DONE
  2026-08-25: it rides the `insight` list, LAST**, for `meta.json`'s ordering reason (an
  interrupted publish must leave an OLD contract over new payloads, never a new contract
  over payloads that are not there). `insight` is four files now and refuses if any is
  missing.
- **Nobody routes notify 08/10/12 through HTTP** (D5).

### Graduation

**Nothing graduates into fog/tickets for `/to-spec` from this ticket** — that step was
conditional on the answer being a Worker, and it is not. The build consequences are the
MUSTs above: an `index.json` checkbox on notify 05, a publish family, a conditional
one-kwarg change in `publish.py`, and four [YOU] dashboard steps. No new component and
no new ticket.

**AMENDED 2026-08-25.** `/to-spec` + `/to-tickets` did make one ticket of this after all
— **frontend 06**, which shipped `files/index.json`, the `contract` integer and
`docs/read-api-contract.md` (`8bd82db`). So the first two MUSTs above are struck through
rather than owed. Still open and unchanged: the conditional one-kwarg gzip change (D2b,
gated on the [YOU] `Accept-Encoding` curl running FIRST) and the four [YOU] dashboard
steps, custom domain included.

The map's fog keeps "**Auth/keys and abuse control for an API**" — this answer supplies
abuse control (free WAF rule) but decides auth by BARRING it, which is not the same as
solving it. If a future consumer needs a key, that is a new decision on a new map, and
it is the one condition under which a Worker would earn its place.

Status: resolved 2026-08-24.
