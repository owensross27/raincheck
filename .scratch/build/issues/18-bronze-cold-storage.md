# 18 — Bronze cold storage: one-way cloud backup of the capture tree

**What to build:** A one-way sync of the Bronze/raw capture tree (`<root>/archive/` — live capture,
static zips, nycbuspositions xz sources, converted parts, precip Bronze copies) to cheap
object storage, so the irreplaceable capture survives a local disk loss without
squeezing the 10 GB local budget.

**Scope change 2026-08-22 (Ross, via his overview session): there is no SSD and there will
not be one for now — cloud object storage is the durable home of Bronze, not just a backup.**
Consequences:
- Provider must be zero-egress or near it (Cloudflare R2 first candidate, Backblaze B2
  second; NOT S3 Glacier — retrieval fees punish the read-back pattern). Keep the $/month
  arithmetic in the comparison note; target is ~$1-2/month at 100 GB.
- The sync stays one-way push and never deletes remote, but reading Bronze back from the
  bucket is now an allowed future pattern (ticket 17 will decide whether the full backfill
  works cloud-resident). Nothing in the current pipeline reads from the cloud yet.
- The external-SSD `RAINCHECK_ARCHIVE_ROOT` guidance is dead; local disk is small
  (~9 GB free on the Mac as of today). Local `data/` holds only the active working set.

**Authorization:** the HITL cloud-writes yes from Ross, 2026-08-22, relayed from his other
raincheck session — Bronze storage in a private bucket only; not public hosting, not
cloud compute. Cost to stay minimal.

**Blocked by:** None (sequencing: hook into the daily job when 15 lands; the sync itself can
be built and run standalone before that)

**Status:** built — waiting on one human step (Ross runs `scripts/cold-storage-wizard.sh`)

- [x] provider comparison (one short note in the ticket): S3 Glacier Instant Retrieval /
      Standard-IA vs Backblaze B2 for ~100 GB with near-zero egress; pick the cheapest sane
      default and record the $/month arithmetic
- [ ] bucket created (or a `/wizard` step for Ross if account setup / payment needs a human);
      credentials via the gitignored `.env`, never hardcoded, never committed
      — **wizard authored at `scripts/cold-storage-wizard.sh`; Ross runs it** (account,
      bucket, scoped token, writes RAINCHECK_COLD_* to .env, verifies, offers first push)
- [x] one-way push sync of `<root>/archive/` (rclone or aws-cli sync class of tool — prefer a
      battle-tested syncer over hand-rolled code), idempotent re-runs (only new/changed files
      upload), never deletes remote objects — `make coldpush`: `aws s3 sync` (aws CLI already
      installed; rclone is not) against the R2 S3 endpoint; sync never deletes without
      `--delete`, re-runs upload only new/changed
- [x] xz sources are in the push scope (flagged by the 06 session 2026-08-22): Bronze VP drops
      8 source columns, so the nycbuspositions xz is the only lossless copy once the volunteer
      bucket vanishes. Sequencing rule for future runs (17): push xz to the bucket BEFORE the
      local low-disk delete. The 06 slice's already-deleted xz are re-downloadable from the
      public bucket today; re-fetch lazily or fold into 17's run — do not block on them now.
      — xz live under `<root>/archive/nycbuspositions/`, inside the push scope by construction
- [x] hooked into the daily job (ticket 15) as a step, not into the archiver loop; runnable
      standalone as a make target — standalone `make coldpush` done; 15 calls it as a step
      when it lands (left for 15's ticket)
- [x] one runnable check (ponytail): after a sync, a listing comparison shows every local
      Bronze file present remotely with matching size; the check is loud on any gap
      — `make coldcheck`: `aws s3 sync --size-only --dryrun`; any would-be upload prints and
      exits 1 ("GAP"), empty means every local file is remote at matching size

## Provider comparison (2026-08-22)

Local Bronze today: 3.73 GB. Target arithmetic at 100 GB:

| provider | storage $/mo @100 GB | egress | read-back 100 GB | notes |
|---|---|---|---|---|
| Cloudflare R2 | $1.35 (first 10 GB free — **$0 today**) | $0 always | $0 | ops pennies at our volume (Class A $4.50/M, 1M free) |
| Backblaze B2 | $0.60 | free to 3x stored/mo, then $0.01/GB | $0 | cheapest storage; egress capped not zero |
| S3 Glacier Instant | $0.40 | $0.09/GB | ~$12 (retrieval $0.03/GB + egress) | rejected: read-back punished |
| S3 Standard-IA | $1.25 | $0.09/GB | ~$10 | rejected: same egress problem |

**Pick: R2** — Ross's first candidate, $0/month at today's size, and unconditionally zero
egress, which is what matters once the bucket is Bronze's durable home and ticket 17 may
read the backfill straight from it. B2 stays the fallback ($0.75/mo cheaper at 100 GB) if
R2 grows friction. Glacier-class rejected per the scope change.

## Implementation note (2026-08-22, agent)

`make coldpush` / `make coldcheck` (Makefile, appended at end to avoid the ticket-08
Makefile overlap), credentials as `RAINCHECK_COLD_{ENDPOINT,BUCKET,KEY_ID,SECRET}` in the
gitignored `.env` only — recipes are @-silenced so expanded credentials never echo; the
COLD_* names avoid colliding with any global AWS identity. Wizard:
`scripts/cold-storage-wizard.sh` (bash -n clean, committed as the repeatable setup path).
Verified: unconfigured guard exits loudly; Makefile parses; full end-to-end push+check
runs in wizard stage 5 once Ross creates the bucket.
