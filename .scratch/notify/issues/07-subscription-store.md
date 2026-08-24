# 07 — Subscription store, operator command, and the unsubscribe handler

**What to build:** Someone can be on the notify list and can get off it — with the minimum
stored about them, and with no public write path anywhere. Spec: section 9; SEAM S.

**Blocked by:** None — can start immediately.

**Status:** resolved 2026-08-24 — `src/raincheck/notify_store.py`, `tests/test_notify_store.py` (21 tests)

- [x] one small SQLite table beside the notifier: contact handle, asset id, asset kind, tier opt-in, consent timestamp, unsubscribe token, state — `<data_root>/live/subscriptions.db`, columns frozen in `notify_store.COLUMNS`
- [x] subscriptions are asset_id grain, Unit kinds only — `bus_stop` and `complex`; a station resolves to its complex before storage (so does an entrance: same one parent link); Cells are refused `not_subscribable` even when scored
- [x] one operator command adds, lists and removes; there is no HTTP path of any kind in v1 — `python -m raincheck.notify_store add|list|remove|unsubscribe`, and a test asserts the module imports no server/socket machinery
- [x] the unsubscribe handler verifies an opaque token and deletes that handle's rows; a bad or reused token changes nothing and returns a typed refusal (`Refused.name == "unknown_token"`)
- [x] the same handler is what an HTTP endpoint would call if one is ever built — `unsubscribe(con, token) -> int`, no CLI or request object in its signature
- [x] a handle past the stated maximum subscriptions is refused at add time — `MAX_PER_HANDLE = 10`, counted on ACTIVE rows per normalised handle
- [x] a test asserts the schema carries no column outside the permitted set — `PRAGMA table_info` equals `COLUMNS`; the table is `WITHOUT ROWID`, so not even a surrogate id is kept
- [x] the add / decide-sees-it / unsubscribe / rows-gone round trip is asserted by reading the store back with SQL
- [x] the deferral's named trigger is recorded where the operator command lives — `DEFERRAL_TRIGGER` is the `--help` epilog, and `list` shouts on stderr once the store passes 25 entries

## Notes from the build (2026-08-24)

- **The handle is normalised (`strip().lower()`) before anything counts it.** Email is the
  only channel, and the handle is the identity the cap is enforced on: without
  normalisation `A@b.com` and `a@b.com` are two handles and the cap is bypassed by
  shifting case. A non-email handle is refused `bad_handle`.
- **One token per HANDLE, not per row** — the spec's unsubscribe removes "the rows"
  (plural). Every row a handle owns shares its token; a second add reuses the existing
  token rather than minting one, so a message sent last week still unsubscribes today.
- **`state` is honoured, not decorative:** only `active` rows are returned to the notify
  decision and only `active` rows count toward the cap. There is deliberately no CLI verb
  to pause — the column exists so a future one costs a migration-free UPDATE.
- Carrier resolution reads `ref/assets` (`asset_id, kind, parent_asset_id`) — a station or
  entrance whose `parent_asset_id` is a complex lands as that complex. This is the store's
  ONLY data-root read; it is what makes `unknown_asset` real rather than a prefix guess.
- Contract tests are mutation-checked: inverting the cap comparison, the Carrier
  resolution, the per-handle token, the handle normalisation, and the Cell refusal each
  turns the suite red.
