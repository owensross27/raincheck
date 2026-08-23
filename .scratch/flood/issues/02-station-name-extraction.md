# 02 Station-name extraction from alert text

Type: prototype
Status: resolved

## Answer

Resolved 2026-08-22. Yes — measured well past the gate. Prototype, data, and
evidence: `../../research/flood-02-station-prototype/` (README has the full
iteration table and frozen rules).

**The verdict: alert station labels are label-grade.** The cause-anchored
extractor (stdlib regex: normalize both sides, hyphen-segment aliases,
route-intersection disambiguation, cause bridges anchored on
flood*/water-condition/water-main-break) measured **precision 1.000 on both
samples** — the 120-row stratified sample AND a 40-row frozen-rule holdout
labeled by a second independent agent — with zero false positives anywhere
(the 01 gate needed >= 0.90; the first cut already passed at 0.923). Recall:
0.970 in-sample, 0.778 holdout — misses cost labels, never contaminate them.
Flags: footer_only and planned_work perfect on both samples, system_wide
117/120 + 40/40.

**Deliverable**: `events_stations.json` — all 171 events (99 post-2020
event_ids + 72 pre-2020 status_ids) with cause-anchored station complexes:
new era 38/99 events station-labeled (39 system-wide only, 22 neither), old
era 57/72. Top stations are hydrologically credible (Richmond Valley SIR,
Times Sq-42 St, Jamaica-179 St, E 143 St-St Mary's St).

**Facts the map needs**:
- **Ida yields ZERO station-grain alert labels** — all 29 of its events use
  line-level system-wide phrasing; 2023-09-29 yields 5 stations matching the
  research note. Station positives skew to localized incidents; 01's spine
  absorbs this (Ida's event-day fires via 311 + Storm Events), and 01's
  system-wide exclusion from station denominators is confirmed necessary.
- One station rename found: "149 St-Grand Concourse" -> "149 St-Hostos"
  (FORMER_NAMES table in the matcher; only one in either sample).
- Attachment path delivered: matched alias -> station rows -> complex_id
  (route-filtered via `affected`); entrances join on complex_id per 01.
- Known recall families for the build (validate on a THIRD sample before
  adopting — the holdout is spent): the "at A and B" second conjunct
  (candidate rule B1 in the README), pronominal references ("flooded tracks
  between those stations").

## Question

Can a cheap matcher (regex/alias table against the ~472-name GTFS subway stop
list, plus complex names) recover the station named in alert `header`/
`description` at measured precision/recall? Prototype it on the 621 subway
flood-keyword rows (hand-label a sample as truth), handle the known phrasings
("water condition at X", "flooding at street-level at X", system-wide rows with
no station), and emit the post-2020 station-labeled event table (99 `event_id`s)
as the asset. The measured P/R decides whether alert labels are a first-class
label source at station grain or a garnish.

Gates and deliverables set by 01's resolution: the label-grade bar is
precision >= 0.90 on the hand-labeled sample (below -> garnish, and 01's
source mix loses the alert member); exclude boilerplate flood-reminder footers
and flood protection/mitigation/barrier/resiliency planned-work rows; emit a
`system_wide` flag for events naming no station (excluded from station-grain
POD denominators, they never trigger event-days); deliver the attachment path
matched name -> GTFS stop_id(s) -> complex_id -> `i9wp-a4ja` entrances as part
of the asset.

## Comments

2026-08-23 — finding from 10 (Real-time detector design), measured: the
cause-anchored extractor's FLOOD_KW/ANCHOR set (/FLOOD|WATER COND.../)
matches ZERO alerts of the "remove water from the tracks" family — 10
alert_ids in the archiver capture 2026-08-20..23, 35 distinct event_ids on
Socrata, none with 'flood'/'water cond' in the header — so the measured
0.970/0.778 recall was estimated on a sample selected BY the old
vocabulary and is structurally blind to this family. informed-entity is no
shortcut (stop_id NULL in 104/104 captured water rows; route_id
populated). Build gate before 10's live chip ships: extend ANCHOR/BRIDGE
to the remove-water clause, scan header AND description, re-measure
precision on the family (>= 0.90 gate), and re-run the frozen-rule holdout
against the archiver parquet serialization (live-path parity unverified).
Detail: issues/10-realtime-detector.md.
