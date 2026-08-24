# 04 — Research: what can a Cloudflare Worker over an R2 bucket actually do (free tier)?

Type: research
Status: open
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
