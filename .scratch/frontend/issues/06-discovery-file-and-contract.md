# 06 — `files/index.json` and the written contract: the API becomes discoverable

**What to build:** an external consumer (person or agent) can learn the whole
read surface from one fetch: the exporter that writes the other payloads also
writes `files/index.json` — every family with key, content type, cadence,
schema pointer, and the version stamps — plus `contract`, an integer that
bumps ONLY on a breaking schema change so a consumer refuses rather than
misreads. Beside it, the human-readable contract document (families, keys,
cadences, cache semantics, the reader-side dating rule, the consumer list —
and the explicit line that in-repo alerting is NOT a consumer and never
routes through HTTP). The publisher ships the file with the family it
belongs to; publishing to the real bucket stays gated on the [YOU] bucket +
custom domain and is NOT this ticket's acceptance.

**Blocked by:** None — can start immediately (exporter + publisher + docs
work; no page dependency). Spec: `.scratch/frontend/spec.md`; the decision is
ticket 03's Answer (D3/D5) — read it.

**Status:** ready-for-agent

- [ ] `files/index.json` written by the same exporter run that writes the
      insight payloads; content covers every family incl. itself; stamps come
      from the existing version-resolution seam, never re-derived
- [ ] `contract` integer present; a test pins that the documented breaking
      conditions and the integer move together (mutation-checked: change a
      documented shape, the test demands the bump)
- [ ] The publisher includes the file in an explicit family list (never a
      directory sync); ordering/cache semantics recorded like the other
      families
- [ ] The contract document exists in the repo's docs surface, says
      static-only + custom-domain-load-bearing + the two-fetch aggregation
      rule with the refused build-time merge and why (frozen-age trap)
- [ ] Own-module tests only (exporter + publish modules); page untouched
