# 07 — Subscription store, operator command, and the unsubscribe handler

**What to build:** Someone can be on the notify list and can get off it — with the minimum
stored about them, and with no public write path anywhere. Spec: section 9; SEAM S.

**Blocked by:** None — can start immediately.

**Status:** ready-for-agent

- [ ] one small SQLite table beside the notifier: contact handle, asset id, asset kind, tier opt-in, consent timestamp, unsubscribe token, state
- [ ] subscriptions are asset_id grain, Unit kinds only — `bus_stop` and `complex`; a station resolves to its complex before storage; Cells are not subscribable
- [ ] one operator command adds, lists and removes; there is no HTTP path of any kind in v1
- [ ] the unsubscribe handler verifies an opaque token and deletes that handle's rows; a bad or reused token changes nothing and returns a typed refusal
- [ ] the same handler is what an HTTP endpoint would call if one is ever built, so deferring the ingress costs no redesign
- [ ] a handle past the stated maximum subscriptions is refused at add time, bounding the per-cycle fuse's worst case
- [ ] a test asserts the schema carries no column outside the permitted set — no location history, no IP, no analytics identifier
- [ ] the add / decide-sees-it / unsubscribe / rows-gone round trip is asserted by reading the store back with SQL
- [ ] the deferral's named trigger is recorded where the operator command lives: first non-tester subscriber, 25 entries, or a public announcement of the map page
