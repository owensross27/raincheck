# frontend5 02 — refpull pulls per-file: the fsspec directory-get doubling, fixed

Status: ready-for-agent
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
