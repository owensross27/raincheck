# The raincheck read API — the static contract

**Status:** contract 1. Machine-readable authority: `files/index.json` on the host
(rendered by `src/raincheck/contract.py`). This document is the human half of the same
contract; where the two disagree, `index.json` is generated from the code and this file
is not, so believe `index.json` and fix this file.

The read API is a **public R2 bucket and nothing else**. There is no server, no Worker,
no runtime, no deploy surface and no bill beyond storage and requests. The bucket IS the
`web/` tree, so the map page's relative paths and an external consumer's absolute URLs
are the same keys. Decided on measured facts in
`.scratch/frontend/issues/03-read-api-decision.md`; do not re-open it on page-weight
grounds, which is the argument that decision already priced and rejected.

## Start here: one fetch

    GET <host>/files/index.json

It lists every family with its keys, content types, schema pointers, cadence, writer,
`Cache-Control` and gate state — including itself — and carries the `contract` integer
and the version stamps. A family with `"tree": true` publishes a whole prefix rather than
a named list, so its single key ends in `**` and its `content_type` is `"*"`: the file
names are the writer's to make and each file's type comes from its own suffix. Nothing else has to be told to you, which is the point: an agent
consumer can learn the whole surface without a human in the loop.

## The families

Six, each an EXPLICIT file list or an explicit prefix. Never a directory sync — the
insight files and the live pair are written into one directory by two writers on two
cadences, so a sync would publish a gated payload and republish a stale one.

| family | keys | cadence | Cache-Control | notes |
|---|---|---|---|---|
| `site` | `index.html`, `layers.js`, `freshness.js`, `panel.js`, `insight.js`, `live.js`, `app.js`, `app.css`, `vendor/maplibre-gl.js`, `vendor/maplibre-gl.css` | deploy-time | `public, max-age=86400` | the page itself — six ES modules, `app.js` the entry, no build step; MapLibre is version-pinned |
| `insight` | `files/cells.geojson`, `files/headline.json`, `files/zones.geojson`, `files/index.json` | per build | `public, max-age=300` | all four or none |
| `live` | `files/live.geojson`, `files/meta.json` | 30 s | `no-cache` | **GATED, dark** — see below |
| `history` | `files/history/**` | per spine rebuild | `public, max-age=300` | one file per asset |
| `docs` | `docs/**` | per Airflow run | `public, max-age=300` | Great Expectations Data Docs |
| `showcase` | `showcase/**` | per landing or recorded run | `public, max-age=300` | the walkthrough, the task graph and one recorded run [orch 13] |

**`docs/**` is the CURRENT run's report, not an archive of runs.** The nightly's `gxcheck`
stage rebuilds the whole Data Docs site every run (orchestration ticket 08), so a
validation page's URL contains that run's timestamp and will not exist tomorrow. Link to
`docs/index.html`, which is stable, and never bookmark a validation page. The tree is a
static site in the ordinary sense - HTML, CSS, images and `.otf` font faces - and it
carries check-RESULT rows only: counts, dates, kinds, hour labels and ratios. No feed row
reaches it, which is what makes it publishable at all.

**`showcase/**` is the portfolio surface, and it is static because it has to be.** The
cluster has no inbound path from the internet, so the Airflow UI is reachable by
`kubectl port-forward` and by nothing else and cannot be the thing anyone is shown.
`showcase/index.html` is a walkthrough that LINKS this contract rather than restating it,
`showcase/graph.svg` is the nightly task graph rendered from `raincheck.daily.STAGES`, and
`showcase/run.json` is one recorded run's per-instance states and durations. It is a tree
family for the same reason `docs/**` is: the file names inside it belong to its writer,
so a fourth artifact is additive and owes no bump.

**Publish order inside a family is load-bearing.** `files/live.geojson` lands before
`files/meta.json`, because meta carries the freshness the page reads: a publisher that
dies mid-pair must leave a fresh fleet under an old meta (reads STALE — safe), never the
reverse. `files/index.json` lands LAST in `insight` for the same reason: it names the
files beside it and the universe that stamped them, so an interrupted publish leaves an
OLD contract over new payloads, never a new contract over old ones.

**`no-cache` on the live pair is not politeness.** A cached `live.geojson` is a frozen
city served under a fresh-looking page. Everything else is short enough that a build
reaches a returning visitor the same day.

**The live family is GATED and currently dark.** `live.geojson` is a derived
current-snapshot view of an MTA feed, and publishing it is gated on a human verification
of MTA's redistribution terms (`raincheck.publish.LIVE_TERMS_VERIFIED`). Until that
receipt exists the publisher refuses with rc 3 — a designed state, not a failure. Three
structural rules keep it a view rather than a feed even when it opens: current snapshot
only (the two keys are literals, so no tick can write a dated second copy, and bucket
versioning stays OFF with no lifecycle rule), no bulk or protobuf endpoint (an allowlist
of web payload suffixes), and MTA attribution on the page.

## Dating a payload: the reader dates the file

**Every payload's age is computed by the CONSUMER from the response it already made:**

    age = <response `Date`> − <response `Last-Modified`>

Both headers come from the origin, so both are on one clock and no consumer clock skew
enters. A cached CDN copy returns the original `Last-Modified`, so the error is toward
STALE. An unparseable stamp reads stale, never fresh.

**No payload carries a wall-clock stamp of when it was written, and this is deliberate.**
A number the writer freezes into a file is not an age: a dead exporter, a dead publisher
or a cached copy serves the same small number forever and paints a stopped city as a live
one. This project shipped that bug once and closed it. A writer's stamp is also the wrong
measurement even when it is fresh — a file written a minute ago over a week-old table
still reads FRESH. Consumers that need to know how old the DATA is read the version
stamps (below) or the payload's own domain fields, never the file's freshness.

A second reason, smaller but binding: `tests/test_export.py::test_re_export_is_byte_identical`
asserts that re-exporting the same root produces the same bytes, and a wall-clock stamp
in any insight payload turns it red. `files/index.json` therefore contains no clock.

## Version stamps

`index.json` carries `versions`, resolved through the repo's single stamp seam
(`raincheck.query.versions`) and never re-derived here:

- `assets_version` — the identity of the asset registry (`ref/assets`)
- `spine_version` — the flood event spine
- `label_version` — the asset-to-event attachment
- `score_version` — the exposure model and every input behind it (`gold/flood_exposure`),
  present only on a root that publishes scores

They describe the **flood universe**, which is the `history` family's universe and the
one an aggregating consumer joins across. The `insight` payloads have no version seam of
their own today; this document does not invent one for them, and a consumer must not read
these as stamping `cells.geojson`.

`score_version` is the one stamp that can be **absent while the others resolve**: it is
read from `gold/flood_exposure`, so a root built without the exposure table publishes the
other three and no score stamp. That absence is the honest answer — nothing on such a root
carries a score — and it is the same absent-never-null rule as everywhere else, not a
partial failure. There is deliberately **no `model_id` stamp**: the exposure model is
per-Unit (`point:l2_logistic` scores stops and complexes, `cell:l2_logistic` scores Cells),
so it is a property of an answer and rides in the `exposure_of` payload instead.

If the stamps cannot be resolved, `versions` is **ABSENT** and `versions_unresolved`
carries the reason. Absent, never null: a consumer that needs a stamp refuses on the
missing key rather than reading a placeholder. The same convention applies inside every
payload here — an unpublishable value is an absent key, not a null.

## The `contract` integer

Static keys carry no `/v1/` path segment, and adding one would double the surface for no
gain: the page is consumer zero and always deploys together with its payloads. Instead
`index.json` carries `contract`, an integer, and a consumer that does not recognise it
**refuses rather than misreads**.

    if (index.contract !== 1) throw new Error("raincheck read API contract changed");

**What bumps it.** The frozen surface a consumer binds to — the family a key lives in,
the key itself, and its content type — is recorded as data in
`raincheck.contract.PROMISE[<contract>]`, and a test asserts it is still a subset of what
`publish.FAMILIES` renders. Removing a key, renaming one, moving it between families or
changing its content type breaks that subset relation and the test demands the bump.

**What does not.** Adding a family or adding a key is additive: existing consumers keep
working, so it does not bump. That asymmetry is why the promise is a subset check rather
than a digest — a digest would move on every additive change, and an integer that moves
for reasons no consumer can see teaches consumers to ignore it.

Worked example, 2026-08-25: `web/app.js` was split into six ES modules and the five new
modules became five new `site` keys. Every key contract 1 promised is still rendered, so
the subset held and the integer did **not** move — which is the right answer, because no
consumer binds to the page's internal file layout. A digest over the surface would have
bumped for it.

**The named limit, stated rather than papered over.** The integer covers the DISCOVERABLE
SURFACE: which keys exist, in which family, with which content type. It does **not**
checksum the inside of a payload — dropping a property from `cells.geojson` is a breaking
change that this mechanism cannot see, because hashing payload internals would either
require building every payload at contract time or bump the integer on every additive
property. Payload-internal shape is pointed at instead: each key in `index.json` carries a
`schema` pointer to the in-repo authority that defines it. If you change a payload's shape
breakingly, bumping `contract` is a judgement call you have to make by hand — make it, and
say so in the commit.

**How to bump.** Add a new frozen entry to `PROMISE` beside the old one (never edit an
old entry — an edited promise is a contract nobody can audit), set `CONTRACT`, and update
this document's Status line, in one commit.

## Aggregating: two fetches, and the build-time merge is REFUSED

"Give me stop X's flood history and its current tier in one call" is two parallel fetches
to the same origin, both edge-cached:

    GET <host>/files/history/<asset_id>.json      per spine rebuild
    GET <host>/files/<current-tier payload>       30 s

**Folding the current tier into the per-asset history file at build time is refused, not
merely not-chosen.** It would freeze a 30 s-cadence value into a per-rebuild file, which
is the frozen-age trap above wearing a performance costume: the merged number stops
advancing the moment the writer's cadence diverges from the reader's expectation, and
nothing in the payload says so. Two files, two cadences, two fetches, each dated by the
reader from its own response headers.

Sizing, measured on the tail rather than the median (a median from a random sample is the
wrong number for sizing one click): the per-asset history maximum is 23,444 bytes.

## Client-side only

There is no query language on this contract, permanently: no query parameters, no
filters, no server-side selection, no SQL passthrough. Consumers fetch a bulk layer file
and filter it in the client. There is no write path, no subscribe endpoint, no auth and
no per-consumer anything — every one of those is barred by a frozen constraint elsewhere
in the project, which is why the answer is static-only rather than static-for-now.

Two boundary rules a consumer must honour:

- **An H3 Cell id crosses this boundary as its hex string**, never the int64:
  `613229535722209279` is past 2^53 and a JSON reader using doubles corrupts it silently.
  Cell asset ids are spelled `cell:<h3-hex>`.
- **`public` mode only.** The restricted classes (FloodNet depths, the observation rows
  themselves, subwaydata-derived impact numbers) are never rendered onto this host. The
  boundary is enforced upstream in `raincheck.query`, not by filtering here.

## The custom domain is load-bearing

**The bucket must sit behind a custom Cloudflare domain, not the `r2.dev` subdomain.**
This is not cosmetic and it is not a nicety. On `r2.dev` Cloudflare documents: no edge
cache, no WAF (therefore no rate limiting), public access "rate-limited", "intended for
non-production traffic", and do not CNAME onto it. Two legs of the static-only decision —
the free automatic edge cache in front of every key, and the one free-plan WAF
rate-limiting rule that is the only abuse control a public bucket gets — exist only
behind a custom domain. Neither R2 custom domains nor Workers custom domains requires a
paid plan; both are gated only on an active Cloudflare zone in the same account, and a
zone has a free plan.

Compression is unresolved and honest about it: nothing in this repo compresses
(`publish._put` sends `ContentType` and `CacheControl` and no `ContentEncoding`), so
whether responses arrive gzipped depends on edge behaviour nobody has measured yet.
Until one `curl -sI -H 'Accept-Encoding: gzip' <object-url>` against the real host is
recorded, treat every size number here as RAW bytes.

## Consumers

1. **The raincheck map page** (`web/index.html`) — consumer zero, over relative paths.
2. **Future external apps**, browser or server, over the custom domain.
3. **Agents querying the dataset** — the project's stated end state; `index.json` is what
   makes that work without a human in the loop.
4. **The showcase** (orchestration ticket 13) — static Data Docs, DAG graph and
   walkthrough, reading `docs/**`.

**In-repo alerting is NOT a consumer, and must never be wired as one.** The decision
function and the notifier (notify 08/10/12) run in-process on the 30 s live loop. Nothing
in this contract is on the notifier's path, and an HTTP hop there would add a network
failure mode to a loop that currently has none. If you find yourself about to fetch a
published file from inside the loop, read the table it came from instead.

## Publishing

    python -m raincheck.publish --family insight --dry-run    # print the plan, touch nothing
    make publish FAMILY=insight

Exit codes from the module: 0 published, 3 the gate is closed (designed), 1 refused or
broken. `make` flattens all three to its own rc 2, so a caller that must tell "gated" from
"broken" runs the module, never the make target.

Publishing to the real bucket is gated on the bucket existing with its custom domain, CORS
policy and WAF rule — an operator step tracked in the project runbook.
