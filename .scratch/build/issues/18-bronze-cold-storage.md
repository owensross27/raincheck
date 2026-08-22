# 18 — Bronze cold storage: one-way cloud backup of the capture tree

**What to build:** A one-way sync of the Bronze/raw capture tree (`<root>/archive/` — live capture,
static zips, nycbuspositions xz sources, converted parts, precip Bronze copies) to a cheap
object-storage cold tier, so the irreplaceable capture survives a local disk loss without
squeezing the 10 GB local budget. Backup/durability only: nothing in the pipeline ever reads
from the cloud; the working set stays local (the external-SSD `RAINCHECK_ARCHIVE_ROOT` move
is unchanged and remains the plan for the backfill working set).

**Authorization:** the HITL cloud-writes yes from Ross, 2026-08-22, relayed from his other
raincheck session — scoped to Bronze cold-storage backup only; not public hosting, not
cloud compute. Cost to stay minimal (cold tier).

**Blocked by:** None (sequencing: hook into the daily job when 15 lands; the sync itself can
be built and run standalone before that)

**Status:** ready-for-agent

- [ ] provider comparison (one short note in the ticket): S3 Glacier Instant Retrieval /
      Standard-IA vs Backblaze B2 for ~100 GB with near-zero egress; pick the cheapest sane
      default and record the $/month arithmetic
- [ ] bucket created (or a `/wizard` step for Ross if account setup / payment needs a human);
      credentials via the gitignored `.env`, never hardcoded, never committed
- [ ] one-way push sync of `<root>/archive/` (rclone or aws-cli sync class of tool — prefer a
      battle-tested syncer over hand-rolled code), idempotent re-runs (only new/changed files
      upload), never deletes remote objects
- [ ] hooked into the daily job (ticket 15) as a step, not into the archiver loop; runnable
      standalone as a make target
- [ ] one runnable check (ponytail): after a sync, a listing comparison shows every local
      Bronze file present remotely with matching size; the check is loud on any gap
