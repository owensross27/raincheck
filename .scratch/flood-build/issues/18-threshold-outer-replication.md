# 18 — 311-threshold outer replication

**What to build:** The sensitivity sweep that cannot run in-fold because it redefines the event universe:
the spine re-derived at alternate 311 thresholds, labels and training rebuilt under each alternate
universe, the fits re-run, and the delta table published — parameterizing the 04→09 machinery,
not writing new logic. Spec: Exposure score (validation — the 311-threshold sweep is an outer
replication); Testing: build-asset evidence.

**Blocked by:** 09

**Status:** ready-for-agent

- [ ] the spine re-derives at the alternate 311 daily-count thresholds (around the frozen p99-union primary), reusing ticket 04's derivation as a pure function of the threshold constant — no fork of the logic
- [ ] labels (05), the flood-era coverage check (06) and the training table (08) rebuild under each alternate event universe through the same jobs, version stamps distinguishing every alternate universe from the primary
- [ ] the fits re-run per universe and a delta table publishes as a build asset: headline metrics per alternate threshold beside the frozen primary, so reviewers see the knob without the knob having selected the result
- [ ] the primary artifacts are untouched: nothing under the frozen primary's version stamps changes byte-wise during the replication
