# 09 — Fits, baselines, validation, and the headline gate

**What to build:** The two L2 logistic fits and the validation battery designed to embarrass them — four
baselines, two split schemes, the bootstrap, the sensitivity sweeps — ending in the headline gate
that decides which model id ships. Spec: Exposure score (models, validation); Testing: build-asset
evidence, not pytest.

**Blocked by:** 08

**Status:** ready-for-agent

- [ ] two fits, L2 logistic, unweighted, lambda by inner CV: the pooled POINT model (entrances + bus stops, shared feature vector + kind indicator) and the CELL model over cells_scored; GBM, hand-weighted index and a third complex-level fit stay rejected
- [ ] complex score = max over child-entrance scores; the 155 alert-sourced complex-event pairs stay out of training and validate at complex grain independently
- [ ] four baselines: base rate, precip-only, unit climatology (B2), density-only (B3)
- [ ] splits: primary = event-grouped 5-fold (deterministic sha1 folds); secondary = location-blocked 5-fold (grouped by Cell); the history-covariate with/without contrast reports under the location-blocked split
- [ ] metrics: pooled CSI/POD/FAR at the in-fold operating point with an event-cluster bootstrap (B=1000); per-event POD + raw false-positive count (61% of events are single-positive — no per-event CSI); PR-AUC secondary
- [ ] HEADLINE GATE: the model beats B2 AND B3 under the location-blocked split; if B2 wins, the shipped model id is B2 and the alternate panel strings are selected — the release checklist asserts whichever branch fired
- [ ] sweeps: ~25 one-at-a-time configs around the frozen primary (100 m, p99-union, ring15_med, history-on); one weight-sensitivity fit (1/fan-out); {50,100,200} m radius sweep in-fold — the 311-threshold sweep is NOT here: it redefines the event universe and runs as its own outer-replication ticket (18)
- [ ] the bus-stop churn deltas publish as a build asset: metrics with and without the era-restricted bus-stop negatives, naming why the original sensitivity method was dropped (no historical Picks locally)
- [ ] the MRMS-era out-of-sample replication metrics publish alongside the AORC-fit metrics, read under the 0.86–0.92 Pass2/AORC scale band with the band caveat stamped on the table
- [ ] pre/post-2014 split published with the label-availability confound stamped on it
- [ ] the published CSI table carries the FIM reference band (published FIM systems run CSI 0.26–0.45) and the comparison is stamped order-of-magnitude-only
- [ ] all validation tables publish as build assets the release links; the runnable check is a small test that the fold assignment is deterministic and the gate evaluation is a pure function of the published tables
