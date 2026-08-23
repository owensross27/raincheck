# 02 — Alert-station extractor: the remove-water era

**What to build:** The cause-anchored station-name extractor extended to the live alert vocabulary and
re-measured, so MTA alert prose keeps producing label-grade station observations — and the frozen
LIVE vocabulary the panel's alert tier will filter on. Spec: Labels and the event spine (extractor
decision); Testing seam 2.

**Blocked by:** None — can start immediately

**Status:** ready-for-agent

- [ ] the anchor vocabulary extends to the "remove water from the tracks" family and the extractor scans header AND description — zero live alerts carry the legacy 'flood'/'water cond' phrasing (measured over 449,737 captured rows), and informed-entity is no shortcut (stop_id NULL in 104/104 captured water alerts)
- [ ] precision is re-measured on the remove-water family and on the archiver's parquet serialization; the gate is ≥ 0.90 to stay label-grade; the frozen-rule holdout re-runs green against both
- [ ] output is station-named alert flood events, each landing ONE observation row at the complex (entrances inherit for display only); this ticket DEFINES the alert-incident dedupe keys as frozen named constants beside the live vocabulary — the spine (ticket 04) and the live alert tier (ticket 13) consume them, they do not define them
- [ ] the live vocabulary and match rules are frozen as named constants, ready to fold into the detector constants artifact (ticket 11)
- [ ] fixture tests on captured alert rows — no network in tests, matching the decode-census precedent
