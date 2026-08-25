# 06 — `files/index.json` and the written contract: the API becomes discoverable ✅ DONE

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

**Status:** done (2026-08-25)

- [x] `files/index.json` written by the same exporter run that writes the
      insight payloads; content covers every family incl. itself; stamps come
      from the existing version-resolution seam, never re-derived
- [x] `contract` integer present; a test pins that the documented breaking
      conditions and the integer move together (mutation-checked: change a
      documented shape, the test demands the bump)
- [x] The publisher includes the file in an explicit family list (never a
      directory sync); ordering/cache semantics recorded like the other
      families
- [x] The contract document exists in the repo's docs surface, says
      static-only + custom-domain-load-bearing + the two-fetch aggregation
      rule with the refused build-time merge and why (frozen-age trap)
- [x] Own-module tests only (exporter + publish modules); page untouched


## Close-out — 2026-08-25

Worktree `/Users/ross/raincheck-wt/frontend06`, branch `frontend06-discovery-contract`.
Own-module tests only (`tests/test_publish.py tests/test_export.py`), +13.

**What shipped.** `src/raincheck/contract.py` renders `files/index.json`; `export.run()`
stages it with the insight trio (all four or none, same `.tmp` + replace dance);
`publish.FAMILIES["insight"]` names it LAST; `docs/read-api-contract.md` is the human
half, pointed at from the README.

**The contract integer is a SUBSET CHECK, not a digest — and that is the design.**
`contract.PROMISE[CONTRACT]` freezes the `(family, key, content type)` triples a consumer
binds to; `contract.surface()` derives the same triples live from `publish.FAMILIES`; the
test asserts `PROMISE ⊆ surface`. Removing, renaming, re-homing or retyping a key breaks
the subset and demands the bump. ADDING a family or a key stays green, because additive
change breaks no consumer. A digest over the surface would have bumped the integer on
every additive change, and an integer that moves for reasons no consumer can see teaches
consumers to ignore it — the flood-10 lesson ("hash only what can change the published
value") applied to a contract rather than to a stamp. Cadence, writer and Cache-Control
strings are in the DOCUMENT but deliberately not in the promise, so rewording one cannot
demand a bump.

**The named limit, in the doc rather than papered over:** the integer covers the
discoverable surface (which keys exist, in which family, with which content type). It
does NOT checksum payload internals — dropping a property from `cells.geojson` is a
breaking change this mechanism cannot see. Each key carries a `schema` pointer instead,
and bumping for a payload-shape change is a judgement call an author makes by hand.

**Version stamps come from SEAM Q and are never re-derived** (`query.versions`:
assets/spine/label). They describe the FLOOD universe, i.e. the `history` family's; the
insight payloads have no version seam today and this document does not invent one for
them — that is stated in the doc rather than glossed. An unresolvable stamp is an ABSENT
`versions` key beside `versions_unresolved` (query.py's absent-never-null convention);
the detail names a local path, so it goes to the operator's stdout and never into the
payload.

**No wall clock in the file**, so `test_re_export_is_byte_identical` covers it for free —
and verified for real: two full exports against `/Users/ross/raincheck/data` produced
byte-identical `index.json` (3,331 B, real stamps `assets d3c7b0f3` / `spine e7fcdf56` /
`label 46bbfd66`), and `publish --family insight --dry-run` planned four objects with
`files/index.json` last at `public, max-age=300`.

**MUTATION-CHECKED, 10 cases, pristine control last, all correct:** removed a promised key
(RED) · renamed one (RED) · moved one between families (RED) · changed a content type
(RED) · **ADDED a key (GREEN — additive must not demand a bump)** · bumped `CONTRACT` with
no new `PROMISE` entry (RED) · doc Status stopped tracking the integer (RED) · dropped
`index.json` from the family list (RED) · published it FIRST instead of last (RED) ·
re-derived the stamps instead of reading SEAM Q (RED).

**A harness defect found on the way, and it is reusable:** the first run reported the
`CONTRACT = 1` -> `CONTRACT = 2` mutation GREEN. The edit is the SAME SIZE as the original
and landed in the same second as the restore, so CPython's `.pyc` validation (source mtime
+ size) treated the cached bytecode as valid and the test imported the UNMUTATED module.
Every mutation harness here needs `PYTHONDONTWRITEBYTECODE=1`; a same-size edit is exactly
the mutation most likely to be a real contract flip.

**NOT done, and not this ticket's acceptance:** nothing was published to a real bucket —
`raincheck-public` does not exist. Local consequence worth knowing: `make publish
FAMILY=insight` now refuses until `make export` has run, because the family is four files
or none. The refusal names the missing file.
