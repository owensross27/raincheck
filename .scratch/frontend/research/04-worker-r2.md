# 04 — Worker over R2: Cloudflare facts (primary sources, accessed 2026-08-24)

Research for `.scratch/frontend/issues/04-worker-over-r2-facts.md`. Facts only,
against developers.cloudflare.com and Cloudflare's official pricing pages. No
recommendation — that's ticket 03's call.

## Summary

- Workers free plan: 100,000 requests/day, 10 ms CPU time/request, hard cap
  (not configurable). Over the daily cap, the route either fails open
  (Worker bypassed) or fails closed (Cloudflare error 1027) — configurable
  per route. Per-request CPU overrun is a different error (1102), independent
  of the daily counter. First paid step: Workers Paid, $5/month, includes
  10M requests + 30M CPU-ms/month, CPU cap raised to 5 min/invocation
  (default 30 s).
- A public R2 bucket sets CORS itself, no Worker needed — it's a bucket-level
  policy (dashboard or `wrangler r2 bucket cors set`). Per-object
  `Cache-Control` metadata is stored on the object and echoed back on GET by
  default; this is documented as general R2 GET behavior, not tied to a
  specific hostname. But Cloudflare's edge/CDN cache only sits in front of a
  **custom domain** — the r2.dev subdomain is explicitly documented as not
  supporting caching, WAF, or bot management, and is rate-limited for
  "non-production traffic."
- A Worker reading R2 through a binding is billed R2 Class A/B operations the
  same as any other access path — the pricing page prices by operation type
  only egress is called out as free "via the Workers API, S3 API, and r2.dev
  domains," with no operations exemption for bindings. Cloudflare's edge
  cache sits in front of a public-bucket-on-custom-domain automatically (a
  cache hit never reaches R2); it does *not* sit in front of a Worker
  automatically — the Worker always runs first, and a Worker-built response
  is only cached if the Worker explicitly calls the Cache API, which itself
  has no effect unless the Worker is on a custom domain (not `*.workers.dev`).
- Custom domains: neither the Workers custom-domains doc nor the R2
  custom-domains doc states a paid-plan requirement. Both just require the
  target domain to be an active Cloudflare zone in the same account. R2
  itself is billed pay-as-you-go with its own free tier, independent of zone
  plan tier.
- Rate limiting without auth: WAF Rate limiting rules are available on the
  Free plan — 1 rule, keyed on IP alone (no auth signal required), 10 s
  counting period, 10 s mitigation timeout. Paid plans get more rules and
  longer windows (Pro 2, Business 5, Enterprise 100).

---

## 1. Workers free-tier limits

**Requests:** 100,000 per day, free plan. Resets at midnight UTC.
Source: https://developers.cloudflare.com/workers/platform/limits/ — accessed 2026-08-24
Source: https://developers.cloudflare.com/workers/platform/pricing/ — accessed 2026-08-24

**CPU time per request:** 10 ms on the free plan (hard limit, not
configurable). Paid plans default to 30 s and can be configured up to a
maximum of 5 minutes of CPU time per invocation.
Source: https://developers.cloudflare.com/workers/platform/limits/ — accessed 2026-08-24
Source: https://developers.cloudflare.com/workers/platform/pricing/ — accessed 2026-08-24

**Other free-tier limits documented on the same page:** 50 subrequests per
request (free) vs. 10,000 (paid); 3 MB compressed script size (free) vs.
10 MB (paid); 128 MB memory per isolate (same both tiers); 100 Workers per
account (free) vs. 500 (paid); 5 Cron Triggers per account (free) vs. 250
(paid); up to 20,000 static asset files per Worker version, 25 MiB max per
file.
Source: https://developers.cloudflare.com/workers/platform/limits/ — accessed 2026-08-24

**Behavior when the daily request limit is hit:** it is a per-route setting,
not a hard account-wide outage. Verbatim from the limits page:
- Fail open: "Bypasses the Worker. Requests behave as if no Worker is
  configured."
- Fail closed: "Returns a Cloudflare 1027 error page. Use this for
  security-critical Workers."
- "You can configure the fail mode by toggling the corresponding route."
Source: https://developers.cloudflare.com/workers/platform/limits/ — accessed 2026-08-24

**Behavior when a single request exceeds its CPU time limit** (a separate
condition from the daily request cap): "Cloudflare returns Error 1102 to the
client with the message `Worker exceeded resource limits`." It's logged in
the dashboard under Metrics > Errors > Invocation Statuses as `Exceeded CPU
Time Limits` (invocation outcome `exceededCpu`), and execution is
terminated.
Source: https://developers.cloudflare.com/workers/platform/limits/ — accessed 2026-08-24
Source: https://developers.cloudflare.com/workers/observability/errors/ — accessed 2026-08-24

**First paid pricing step — Workers Paid plan:**
- Base cost: $5 USD/month per account.
- Requests: 10 million included per month, then $0.30 per additional
  million.
- CPU time: 30 million CPU-milliseconds included per month, then $0.02 per
  additional million CPU-ms.
- CPU time per invocation: configurable up to 5 minutes (default 30 s).
- No egress/bandwidth charges.
Source: https://developers.cloudflare.com/workers/platform/pricing/ — accessed 2026-08-24

---

## 2. Public R2 bucket: CORS and per-object Cache-Control, without a Worker

**CORS — set directly on the bucket, no Worker required.** Configured via
the Dashboard (Settings > CORS Policy > Add CORS policy) or Wrangler
(`npx wrangler r2 bucket cors set <BUCKET_NAME> --file cors.json`). It's a
bucket-level policy, not something a Worker has to inject.
Source: https://developers.cloudflare.com/r2/buckets/cors/ — accessed 2026-08-24

The docs explicitly confirm this for custom domains: "Custom domains
connected to an R2 bucket with a CORS policy automatically return CORS
response headers for cross-origin requests." The same page also has generic
"public bucket" guidance not scoped to a specific hostname: "To use CORS
with a public bucket, ensure your bucket is set to allow public access. Next,
add a CORS policy to your bucket to allow the file to be shared." It does
**not** contain a sentence that separately confirms or denies CORS on the
r2.dev URL specifically — r2.dev is not named anywhere on this page.
Note: without a CORS policy, "browser-based uploads and downloads using
presigned URLs will fail, even though the presigned URL itself is valid."
Source: https://developers.cloudflare.com/r2/buckets/cors/ — accessed 2026-08-24

**Per-object Cache-Control — stored on the object, echoed back by default.**
`cacheControl` is a field on an object's HTTP metadata (`httpMetadata`),
alongside `contentType`, `contentDisposition`, `contentEncoding`,
`cacheExpiry`, etc. On download: "Generally, these fields match the HTTP
metadata passed when the object was created. They can be overridden when
issuing GET requests, in which case, the given values will be echoed back
in the response." This statement is general R2 GET-object behavior (it sits
under the Workers API reference's HTTP Metadata section) — it is not phrased
as being specific to one serving hostname over another, and no page found
draws a r2.dev-vs-custom-domain line for this specific behavior (unlike
caching, WAF, and bot management, which are explicitly split — see below).
So: yes, a `Cache-Control` value set at publish time is what a client sees
on GET against the object, on either public endpoint, by default.
Source: https://developers.cloudflare.com/r2/api/workers/workers-api-reference/ — accessed 2026-08-24

**Where r2.dev and custom domain diverge is Cloudflare's edge/CDN cache and
security features, not the metadata itself:**
- "The development URL (`r2.dev`) does not support caching, WAF, or bot
  management."
- "Public access through r2.dev subdomains is rate-limited and should only
  be used for development purposes."
- "To use features like WAF custom rules, caching, access controls, or Bot
  Management, you must configure your bucket behind a custom domain."
- r2.dev is explicitly "intended for non-production traffic," and Cloudflare
  documents you should avoid CNAMEing a custom hostname onto it ("Avoid
  creating a CNAME record pointing to the r2.dev subdomain" — unsupported).
Source: https://developers.cloudflare.com/cache/interaction-cloudflare-products/r2/ — accessed 2026-08-24
Source: https://developers.cloudflare.com/r2/buckets/public-buckets/ — accessed 2026-08-24

**Net for cloud 09's use case:** the `Cache-Control` header set at publish
time should still come back on a GET against either r2.dev or a custom
domain (it's object metadata, not a cache-layer feature). What changes
between the two is whether *Cloudflare's own edge cache* honors/uses that
header to skip R2 on repeat requests — that only happens behind a custom
domain. On r2.dev every request is documented as reaching R2 directly, and
is rate-limited on top of that.

---

## 3. Worker + R2 binding: operation costs, and where the edge cache sits

**Does a Worker pay R2 Class A/B costs via a binding?** The R2 pricing page
prices Class A and Class B operations strictly by operation type (e.g.
`PutObject`/`ListObjects` = Class A; `GetObject`/`HeadObject` = Class B),
with no carve-out anywhere on the page for the Workers binding API vs. the
S3 API vs. the dashboard. The only per-access-method statement on the whole
page concerns egress, not operations: "Egressing directly from R2, including
via the Workers API, S3 API, and r2.dev domains, does not incur data
transfer (egress) charges and is free." That sentence names the Workers API
as one of several ordinary access paths for the egress exemption — it does
not carve bindings out of operations billing, and no other sentence on the
page does either. Read together, a `GetObject`-equivalent call made through
a Workers binding is a Class B operation like any other.
Source: https://developers.cloudflare.com/r2/pricing/ — accessed 2026-08-24

**Free tier for R2 (Standard storage only):** 10 GB-month storage, 1 million
Class A operations/month, 10 million Class B operations/month. Beyond that:
Standard Class A $4.50/million, Class B $0.36/million (Infrequent Access:
$9.00/million Class A, $0.90/million Class B — and IA has no free
allowance).
Source: https://developers.cloudflare.com/r2/pricing/ — accessed 2026-08-24

**Edge cache in front of (a) a public bucket URL:** Only works behind a
custom domain. "Domain access through a custom domain allows you to use
Cloudflare Cache to accelerate access to your R2 bucket." On a cache miss,
the edge "fetches directly from R2"; Tiered Cache can route misses through
an upper-tier data center first, "reducing direct R2 requests" — i.e., cache
hits are served without reaching R2 (and its per-operation billing) at all.
r2.dev gets none of this — every request goes to R2.
Source: https://developers.cloudflare.com/cache/interaction-cloudflare-products/r2/ — accessed 2026-08-24
Source: https://developers.cloudflare.com/r2/buckets/public-buckets/ — accessed 2026-08-24

**Edge cache in front of (b) a Worker's response:** Not automatic. "When a
request arrives, it hits the Worker before the cache is checked" — the
Worker always executes (a billable request/CPU-time event) regardless of
whether the eventual response could have been served from cache. Inside the
Worker, a `fetch()` subrequest to an origin automatically follows the zone's
normal cache rules ("Cache settings on `fetch` automatically apply caching
rules based on your Cloudflare settings"), but a Response the Worker builds
itself (e.g., from an R2 binding read) is only cached at the edge if the
Worker explicitly calls the Cache API (`caches.default`/`caches.open()`).
And the Cache API is a no-op on `*.workers.dev`: "any Cache API operations
in the Cloudflare Workers dashboard editor and Playground previews will
have no impact," and "Workers deployed to custom domains have access to
functional cache operations" (implying workers.dev deployments do not) —
the same custom-domain-vs-dev-subdomain split R2 has for its own cache.
Source: https://developers.cloudflare.com/cache/interaction-cloudflare-products/workers/ — accessed 2026-08-24
Source: https://developers.cloudflare.com/workers/runtime-apis/cache/ — accessed 2026-08-24
Source: https://developers.cloudflare.com/workers/reference/how-the-cache-works/ — accessed 2026-08-24

Net mechanical difference: a public bucket behind a custom domain gets
automatic edge caching (cache hit ⇒ zero R2 ops, zero Workers request) with
no code. A Worker-in-front gets no such thing automatically — every request
is a billable Worker invocation, and skipping the R2 binding read on a
repeat request requires the Worker to explicitly implement Cache API
get/put logic, and only works at all if the Worker is on a custom domain.

---

## 4. Custom domains: R2 public buckets vs. Workers — free tier or not

**Workers Custom Domains:** the setup doc's stated requirements are "an
active Cloudflare zone" and "a Worker to invoke" — i.e., the target hostname
must be an onboarded Cloudflare zone in the account. "You cannot create a
Custom Domain on a hostname with an existing CNAME DNS record or on a zone
you do not own." No plan-tier requirement (Free/Pro/Business/Enterprise) is
stated anywhere on the page, and the Workers pricing page has no
feature-availability table gating Custom Domains behind a paid plan either
— that pricing page covers usage limits/costs only (requests, CPU,
storage), not a feature checklist.
Source: https://developers.cloudflare.com/workers/configuration/routing/custom-domains/ — accessed 2026-08-24
Source: https://developers.cloudflare.com/workers/platform/pricing/ — accessed 2026-08-24

**R2 Custom Domains:** requirement is the same shape — "the domain being
used must have been added as a zone in the same account as the R2" bucket,
or set up via partial (CNAME) setup if not already on Cloudflare. The one
plan-specific caveat found is the reverse of a Free-tier restriction:
Enterprise zones "need to release the zone hold before adding the custom
domain" — an extra step for Enterprise, not a gate that excludes Free. R2
itself requires only "a Cloudflare account with an R2 subscription" (its own
pay-as-you-go product, billed per the free tier in section 3, independent
of the zone's plan tier) — no minimum account plan tier is stated.
Source: https://developers.cloudflare.com/r2/buckets/public-buckets/ — accessed 2026-08-24
Source: https://developers.cloudflare.com/r2/get-started/ — accessed 2026-08-24

**Cross-check against the top-level pricing page:** Cloudflare's current
plans/pricing page organizes by per-product free tiers (e.g. Workers:
"100k / day" requests free; R2: "10 GB-month" free) rather than a single
Free/Pro/Business/Enterprise gate for these features, and does not list
"Custom Domains" as a separately paywalled line item for either product.
Source: https://www.cloudflare.com/plans/ — accessed 2026-08-24

**Conclusion (fact, not inference beyond what's stated):** no page found in
this research states that either Workers Custom Domains or R2 Custom
Domains requires a paid plan. Both are gated only by "the domain must be an
active Cloudflare zone in the account" — which itself has a free tier (a
Cloudflare Free zone plan).

---

## 5. Rate limiting / abuse control without auth (Cloudflare-side, not app code)

**WAF Rate limiting rules — available on the Free plan.** From the
"Availability" table:
- Free: 1 rule; counting characteristic "IP"; counting period 10 s;
  mitigation timeout 10 s.
- Pro: 2 rules.
- Business: 5 rules.
- Enterprise (with either Application Security or Advanced Rate Limiting):
  100 rules.
- Higher tiers unlock longer counting periods and mitigation timeouts than
  the Free plan's fixed 10 s/10 s.

The Free plan's counting characteristic is IP alone — no authentication
signal is required for the rule to key on. "Available fields in rule
expression" on Free include Path and Verified Bot, on top of IP.
Source: https://developers.cloudflare.com/waf/rate-limiting-rules/ — accessed 2026-08-24 (Availability section)

This sits at Cloudflare's edge, ahead of the origin/Worker/R2 — it is a
platform feature, not something implemented in application code, and it
requires no user authentication to function (it counts by IP/path).
