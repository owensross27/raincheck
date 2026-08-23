# 06 — AORC flood-era precip extension

**What to build:** The precipitation spine extended to cover every union-event Window: the month
partitions containing event windows plus 24 h lookback (~52 needed months, 5 exist) built through
the existing per-(src, month) job with the AORC Precip source pinned — never pooled with MRMS.
Spec: Storage and engine conventions; ADR-0002; Testing seam 1.

**Blocked by:** 01, 04

**Status:** ready-for-agent

- [ ] the needed month list derives from the spine (union-event windows + 24 h lookback) and each month builds through the existing per-(src, month) precip job, src=aorc
- [ ] the run is disk-checked against the cold-storage headroom before starting; if disk blocks, the fallback is window-sliced flood-only builds — and which path ran is recorded
- [ ] coverage assertion: every union-event Window hour has AORC Cell-hour rows for all of cells_scored — ticket 01's disjointness assertion (permanently-NULL Pixels never intersect cells_scored) is what makes full coverage attainable
- [ ] no MRMS rows enter any fit-era table (ADR-0002 / never-pooled discipline)
- [ ] the existing precip test style gains one flood-era fixture month with a known-answer value
