# 03 — The unified read API: does anything beyond the static contract earn its place?

Type: grilling
Status: open
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
