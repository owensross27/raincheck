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

---

**Claim note (2026-08-22, busy-goldstine session — orientation only, no implementation).**
Stood down at Ross's usage-limit round-up after reading the spec, verdicts, prototype and
live capture. Findings for the implementing session:

- Port target is `research/flood-02-station-prototype/matcher.py` (+ README): norm rules,
  alias table off hyphen segments, cause bridges, flags. Holdout precision 1.000 / recall
  0.778 with rules frozen; the B1 " AND "-conjunct recall candidate needs a THIRD fresh
  sample before adoption (holdout is spent).
- Live capture re-measured this session over `archive/subway_alerts` (now 1,793,172 rows;
  the ticket's 449,737 was an earlier snapshot): legacy 'flood'/'water cond' phrasing =
  0 rows on the FULL capture; water rows 410 = 24 alert_ids = 9 incidents; stop_id NULL
  in 410/410 (informed-entity no-shortcut re-confirmed).
- alert_id grammar: `lmm:alert:<event>:<update>` (e.g. 264026 across updates 26/29/30/34)
  — the incident dedupe key is the event component, mirroring the Socrata new era's
  event_id/update_number. Freeze the parse + key as the named constants this ticket owns.
- Live vocabulary family, measured verbatim: REMOVE|REMOVING|REMOVED WATER FROM THE
  TRACKS, always bridged AT/NEAR <station>. Active-vs-cleared maps cleanly: present
  forms / "What's Happening?" = active; "after we removed" / "What Happened?" = cleared.
- One physical flood mints several event ids (WTC/Chambers 2026-08: 264031 E-line,
  264043 F, 264050 B/D) — one observation row per (event, complex); cross-event merging
  is the spine's (04), not this ticket's.
- "near World Trade Center/Chambers St" slash-pair: check whether both aliases resolve
  to ONE complex in ref/assets before inventing a pair rule (likely same complex — rule
  unnecessary).
- ref/assets (flood-build 01) carries kind=station/complex rows with name, complex_id,
  daytime_routes — replaces the prototype's stations.json entirely.
- Live alert text uses current-era names (149 St-Hostos appears verbatim); FORMER_NAMES
  only matters for historic Socrata rows.
- Suggested shape: new `src/raincheck/flood_alerts.py` reading ref/assets; frozen
  constants (LIVE vocab, bridges, dedupe keys, flags); fixtures cut from captured
  parquet rows (no network, decode-census precedent); precision re-measure via a blind
  labeling pass over a stratified live sample, scored against the gate >= 0.90; the
  frozen-rule holdout re-run against the parquet serialization.
