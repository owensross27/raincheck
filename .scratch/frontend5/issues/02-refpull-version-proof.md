# frontend5 02 — refpull pulls per-file: the fsspec directory-get doubling, fixed

Status: done
Found live 2026-08-28 reviving the stream: `refpull.pull()`'s
`f.get(f"{bucket}/ref/{name}", f"{out}/", recursive=True)` copies the DIRECTORY INTO
the destination under the image's fsspec version (`/data/ref/cell_zone/cell_zone/
part-00000.parquet`) while the Mac's version copies contents flat. The bucket is flat
(verified). DuckDB's `**` glob tolerated it (precip-live green for days); Spark's flat
read did not (`UNABLE_TO_INFER_SCHEMA` — the stream's second crash-loop tonight, fixed
in-pod by hand). Same family as "the image bakes it is not evidence the code path
runs": pulled is not read.
Files: `src/raincheck/refpull.py`, its test file (find it — likely
`tests/test_refpull.py`).

## MUSTs

1. **Per-file pull, no recursive directory get anywhere**: enumerate the table's
   objects (`f.find(f"{bucket}/ref/{name}")`) and `f.get` each to
   `out / <basename>` (ref tables are flat single-level; if `find` ever returns a
   nested key, fail loudly rather than guess). The idempotency rule (a non-empty
   local table is left alone) and the SKIP/`src` behavior are unchanged.
2. **The regression is pinned by LAYOUT, not by mocking the old bug**: after a pull
   against the test fixture fs, assert every pulled file sits DIRECTLY under
   `<root>/ref/<table>/` and no `<table>/<table>/` level exists. Assert by walking
   the result, and assert the module's source no longer contains a recursive
   directory get (anchor on the call shape, prose-safe).
3. Keep every existing refpull test green; keep the "root is already object storage"
   short-circuit and the printed summary format (the pods' logs are read by humans).
4. **Mutation round** (standing rules): restore the recursive-dir-get shape (must go
   RED on the layout test); break idempotency; drop the loud-fail on a nested key.

## Refusals

- No new dependency; s3fs stays the mechanism (it is publish.py's own).
- No behavior change for the remote-root short-circuit; no CLI change.

## Protocol

Worktree `/Users/ross/raincheck-wt/frontend5-02` from master, branch
`frontend5-02-refpull-per-file`, own-module tests via main venv + PYTHONPATH=src,
never the full suite, no pin commits, no vault writes (report your RUN-LOG entry
back). Commit explicit paths, push.

## Close-out (2026-08-27)

`pull()`'s loop no longer does a directory get at all: for each table it lists the
table's own objects with `f.find(f"{bucket}/ref/{name}")`, strips the
`<bucket>/ref/<table>/` prefix off each key, and `f.get`s that one file straight to
`out / rel` — `f.get(key, str(out / rel))`, no `recursive=` kwarg anywhere in the
module. A key whose stripped remainder still contains `/` (a nested object) raises
`ValueError` naming the table and the key instead of guessing a flat layout for it.
Idempotency (`out.is_dir() and any(out.iterdir())` skips a non-empty table) and the
SKIP/`src` behavior are byte-for-byte what they were.

Tests: 6 -> 8 `def test_`. Two new: `test_pulled_files_sit_directly_under_the_table_dir_no_doubled_level`
walks the pulled tree per table and asserts no `<table>/<table>/` level exists (MUST
2, layout-pinned); `test_the_module_never_issues_a_recursive_directory_get` parses
`refpull`'s own source with `ast` and fails on any call carrying a `recursive=True`
keyword — anchored on the call shape, so a comment or docstring using the phrase
can't retire it. `test_a_nested_key_fails_loudly_rather_than_guessing` covers the
refusal MUST 1 asked for. The three pre-existing tests that inspected `fake.got`
were updated (not just left alone): `f.get` is now called once per FILE instead of
once per TABLE directory, so `fake.got` entries are full object keys and the
table name moved from the last path segment to the second-to-last — their
assertions were rewritten to match, their intent (which tables got pulled, in
what order, src skipped) is unchanged.

Mutation round (commit `757e93b` first, `PYTHONDONTWRITEBYTECODE=1`, restore via
`git checkout -- src/raincheck/refpull.py` since the file is tracked, `git status
--short` verified empty after each restore, pristine 8/8 re-run at the end proved
the restore held):

| # | Mutation | Result |
|---|---|---|
| 0 | pristine control | 8 passed |
| A | restored the old `f.get(f"{bucket}/ref/{name}", f"{out}/", recursive=True)` single-call shape | 6 failed, 2 passed — `test_the_module_never_issues_a_recursive_directory_get` caught the call shape directly; the other five failed on `TypeError: FakeFS.get() got an unexpected keyword argument 'recursive'` (the fixture no longer accepts the old signature) |
| B | dropped the `if out.is_dir() and any(out.iterdir()): had.append(name); continue` skip | 1 failed (`test_a_table_already_present_is_left_alone`), 7 passed |
| C | removed the `if "/" in rel: raise ValueError(...)` guard and flattened a nested key to its basename instead of refusing it | 1 failed (`test_a_nested_key_fails_loudly_rather_than_guessing`, "DID NOT RAISE ValueError"), 7 passed |

All three killed; each restore left `git status --short` empty; final re-run 8/8
green at `757e93b`.

RUN-LOG (for the orchestrator):
frontend5-02 refpull-per-file — `pull()` now enumerates each table's objects via
`f.find` and `f.get`s them one file at a time (`f.get(key, str(out / rel))`, never
`recursive=True`), closing the fsspec-version-dependent directory-doubling that
broke Spark's flat read (`UNABLE_TO_INFER_SCHEMA`) while DuckDB's `**` glob hid it.
Nested key -> loud `ValueError`, never a guessed layout. Idempotency and SKIP/`src`
unchanged; printed summary format unchanged. 8 tests (was 6), one AST-anchored
against the `recursive=True` call shape (prose-safe) and one walking the pulled
tree for the doubled `<table>/<table>/` level. Mutation round: 3/3 killed, restores
verified empty via tracked-file `git checkout`. Branch
`frontend5-02-refpull-per-file` pushed at `757e93b`; worktree
`/Users/ross/raincheck-wt/frontend5-02`.

Forward-context: this ticket only fixes the LOCAL-disk pull path exercised by the
test fixture; it was not re-run against the real bucket or a live pod (no
`AWS_ENDPOINT_URL`/credentials in this session, and TRAPS.md's own note on cloud
12 says refpull already ran green in anger on `precip-live` and `raincheck-stream`
under the OLD recursive-get code, on a bucket that happens to be flat one level
deep — so nothing was visibly broken there yet). Next image build that carries
this sha is the first real proof; nothing else in the repo calls `refpull.pull()`
with a recursive-dir assumption baked in elsewhere as far as this ticket's grep
went (only `src/raincheck/refpull.py` itself and its test file matched
`recursive` inside `f.get`).
