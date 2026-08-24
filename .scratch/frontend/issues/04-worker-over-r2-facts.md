# 04 — Research: what can a Cloudflare Worker over an R2 bucket actually do (free tier)?

Type: research
Status: resolved
Blocked by: none

## The question

Facts outside this repo, blocking ticket 03's decision. Against Cloudflare's
own documentation (primary sources only), establish as of 2026-08:

- Workers free-tier limits: requests/day, CPU time per request, and what
  happens at the limit (429? drop?). Paid tier's first pricing step.
- R2 public bucket vs Worker-fronted bucket: can a public r2.dev/custom-domain
  bucket set CORS and cache-control on its own, or does that need a Worker?
  (cloud 09 already sets per-object cache-control at publish time — verify
  whether that survives on the public endpoint.)
- Worker -> R2 bindings: does a Worker reading R2 via a binding pay R2
  class-A/B operation costs, and how does Cloudflare's edge cache sit in front
  of either path?
- Custom domains on r2.dev vs on a Worker; whether the free tier covers both.
- Rate limiting / abuse control available WITHOUT auth (Cloudflare-side
  features, not app code).

## Resolution shape

Findings as a markdown file at `.scratch/frontend/research/04-worker-r2.md`
with source links and access dates, gist under ## Answer here, one line on the
map. Facts only — the decision is ticket 03's.

## Answer

Resolved 2026-08-24. Full findings, every claim with a source URL + access
date: `.scratch/frontend/research/04-worker-r2.md` (275 lines). The gist:

- **Workers free tier**: 100,000 requests/day, 10 ms CPU/request (hard cap).
  Over the daily cap the route is CONFIGURABLE to fail open (Worker bypassed)
  or fail closed (error 1027); per-request CPU overrun is a separate error
  (1102). First paid step: Workers Paid, $5/mo — 10M requests + 30M CPU-ms
  included, CPU cap raised to 5 min.
- **No Worker needed for the basics**: CORS is a bucket-level policy
  (explicitly documented on custom domains; the docs never confirm or deny it
  for r2.dev specifically), and per-object `Cache-Control` is stored metadata
  echoed on GET on both endpoints — cloud 09's publish-time cache headers
  survive.
- **The real difference is the EDGE CACHE**: it sits automatically in front of
  a custom-domain public bucket (a hit never reaches R2), and NOT in front of
  r2.dev (which explicitly has no caching/WAF/bot management and is
  rate-limited for non-production use) and NOT automatically in front of a
  Worker (the Worker always runs first; Cache API code is required and is a
  no-op on *.workers.dev — needs a custom domain).
- **Billing**: a Worker's R2 binding reads pay Class B like any access path;
  only egress is free everywhere. So a Worker in front of the bucket ADDS
  Worker invocations without removing R2 read costs, unless it caches.
- **Custom domains**: free on both Workers and R2 — just needs the domain as
  an active Cloudflare zone (Free plan qualifies).
- **Rate limiting without auth**: WAF Rate limiting rules exist on the Free
  plan — 1 rule, IP-keyed, 10 s window / 10 s mitigation.

Ticket 03 now unblocked. The shape these facts suggest (not decided here): a
custom-domain public bucket already gives cached, cache-controlled, CORS-able
serving with no Worker; a Worker earns a place only for duties a static
bucket cannot do (aggregation, auth, shaping), and pays its own limits.
