# 16 — Impact evidence: what the floods did to service

**What to build:** The offline impact record — subway service_ratio and max_gap_ratio at complex grain
from subwaydata.nyc, bus Speed ratios from the existing Gold — joined to event windows as
evidence, never as features, with the coverage honesty published. Spec: Impact signals; Testing
seam 1 for the aggregates' contracts.

**Blocked by:** 01, 04

**Status:** landed (uncommitted at time of writing: src/raincheck/flood_impact.py,
tests/test_flood_impact.py; suite green locally)

- [x] subway: service_ratio and max_gap_ratio at complex grain from subwaydata.nyc per-day CSVs — trip-start-keyed, so hours 00–05 union the previous day's file (94% undercount otherwise); route-mix residuals and same-line neighbor controls accompany any flood attribution
  - the undercount is re-measured, not inherited: 2023-09-29 hour 00 reads 341 calls from
    that day's file alone and 4,601 unioned with the 28th's — a 92.6% undercount.
  - baselines are LOCAL, not era-pooled: each event day is ratioed against its own same-weekday
    D±7 / D±14 non-event controls (median), which kills post-COVID service drift and pick changes.
  - resid_ratio = actual / (control mix x each route's SYSTEM-WIDE ratio that hour);
    nbr_ratio = service_ratio / the median service_ratio of the same-line complexes (a complex
    on several lines takes the median of its lines' medians — joining line-by-line silently
    fanned the published grain out to one row per line and was caught by the reference test).
  - a complex-hour with NO trains has no row on the day side: the day/baseline join is a FULL
    JOIN so a total outage reads service_ratio 0 instead of vanishing. It was vanishing —
    fixing it moved Ida's caught count from 105 to 157 and 2023-09-29's from 78 to 98 — and
    cost one of the reference day's flagged catches (see below), because peers lose hours too.
- [x] fixture assertion: on 2023-09-29 the combined metrics catch 5/7 of the extractor-flagged complexes
  - measured after the total-outage fix below; the flagged set is now EIGHT complexes, not seven (the landed extractor's 2023-09-29 output:
    225, 232, 236, 243, 47, 623, 626, 79). Measured: 4 of the 8 are caught — 236, 243, 47, 79.
    It read 5 before the total-outage fix: once a peer's zero hours count, complex 626's loss
    no longer stands out against its own line, and the neighbour control retires it. The
    ticket's 5/7 is superseded by measurement, not matched.
  - the caught rule had to be frozen with the attribution controls IN it. A bare "some hour lost
    half its trains or doubled its worst headway" catches 386/445 complexes on 2023-09-29 and
    101/445 on a quiet day — overnight service is sparse enough that anything trips it. Frozen:
    (service_ratio <= 0.5 OR max_gap_ratio >= 2.0) AND resid_ratio <= 0.8 AND nbr_ratio <= 0.8
    AND base_calls >= 5, for two consecutive NY hours in 06..21.
  - no fixture of subwaydata is committed (no data license). The reference-day test reads the
    local build and skips without it; the union rule and the caught rule are pinned on synthetic
    days that need neither network nor snapshot.
- [x] bus: Speed ratios from the existing Gold Cell-hour tables and their window baselines, sums-merged
  - the baseline join is window-scoped: a day outside w1/w2 (2026-08-20, the live era) gets a
    NULL ratio rather than borrowing the other window's dry speeds. DuckDB's dayofweek is
    0=Sunday against gold's Monday-based hour_of_week — the +6 % 7 shift is load-bearing.
- [x] coverage honesty published: subway covers 35/115 union event days, bus 6/115, 70% have neither
  - RECOMPUTED against the landed spine (206 events / 248 event-days, spine_version e7fcdf56):
    **subway 76/248 (30.7%), bus 13/248 (5.2%), neither 171/248 (68.9%)**, both 12/248.
    Subway's ceiling is the source era (2021-04-01..2026-08-15) — 76 is EVERY event day in it.
    Bus's 13 are the two measurement windows plus 2026-08-20; only 12 carry a dry baseline.
  - second honesty number, published beside it — a day-type-matched PLACEBO base rate. Each
    covered event day gets a clean twin 13 weeks away (same weekday); 48 of the 76 have one,
    28 sit in event history too dense for a clean twin and are dropped from the base rate.
    Caught complexes per day, event vs placebo:
      weekday  event n=57 median 5, p90 18, max 157   placebo n=37 median 4, p90 13, max 23
      weekend  event n=19 median 34, p90 53, max 55   placebo n=11 median 36, p90 51, max 64
    Read literally: the MEDIAN event day is not distinguishable from a clean day, and the
    WEEKEND is not readable at all — scheduled work (G.O.s) shuts whole segments, which trips
    the same rule the flood does and takes the same-line neighbours down with it, so the
    neighbour control cannot see it. What the evidence does show is the tail: Ida 2021-09-02
    (157), 2023-09-29 (98) and 2026-02-23 (93) are far outside anything a clean weekday reaches.
    The panel must say this, not just plot the counts.
- [x] no new Silver table — corpus aggregates are build assets; subwaydata snapshots live outside the archive root (never cold-pushed) and derived numbers are local-page-only (license not found)
  - everything lands under `<root>/snapshots/subwaydata/` (raw/, agg/, impact/) — outside
    `<root>/archive`, the only tree `make coldpush` mirrors, and inside the gitignored data root.
- [~] impact is evidence/display ONLY — asserted absent from ticket 08's matrix and never a detector input
  - held: the module publishes nothing into silver/ or gold/ and nothing imports it, so it
    CANNOT reach the model today. The matrix assertion itself is owed — ticket 08 is still
    ready-for-agent, and an absence test against a matrix that does not exist would be theatre.
    Whoever lands 08 adds it there.

**Run:** `python -m raincheck.flood_impact fetch | agg | build` (607 day-files, ~700 MB, ~20 s to
fetch; ~9 min to aggregate; both resumable). No Makefile target added — the Makefile was dirty
with another session's work at landing time; add `flood-impact` when it is clean.

**Left for the panel (ticket 15/17):** the derived numbers are local-page-only, so the panel must
read `<root>/snapshots/subwaydata/impact/` directly and never export them.
