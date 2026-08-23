# Ticket 02 prototype: station-name extraction from MTA flood alerts

2026-08-22. Inputs pulled live (SODA): `alerts_old.json` (186 rows, `3h5b-5ktz`
Subway flood/water-cond filter), `alerts_new.json` (435 rows, `7kct-peq7` NYCT
Subway), `stations.json` (496 stations / 445 complexes / 379 distinct names —
76 names shared across stations, so `affected` routes disambiguate).

## Pipeline

`matcher.py` (stdlib only): normalize both sides (uppercase, hyphen/slash ->
space, ordinal strip, Av/St/Blvd canonicalization), longest-first word-bounded
alias match, route-intersection disambiguation, flags for system-wide /
planned-work / footer-only rows, `FORMER_NAMES` alias table for renamed
stations (first hit found by self-check: "149 St-Grand Concourse" is now
"149 St-Hostos" — historical alert text uses era names, the station list is
current-only). Self-check: 5/5 known examples from
`../subway-flood-labels.md`.

Outputs: `extractions.json` (row grain, matches with spans),
`events_stations.json` (event grain: union across updates, planned-work and
footer-only rows dropped).

## Measured (pre-truth)

- 621 rows -> 518 with >=1 station (83.4%); unmatched non-system-wide rows are
  genuinely station-free ("flooding in multiple stations", route-level
  suspensions).
- Events reproduce the research note exactly: 99 new-era `event_id` + 72
  old-era `status_id` = 171.
- Event station coverage: new era 87/99 events with >=1 complex (4
  system-wide-only, 8 neither), old era 67/72; median 3-4 complexes/event.
- Ambiguity: 452/2,285 matches (20%) resolve to >1 complex after route
  filtering, concentrated in generic numbered names (96 St, 125 St, 36 St).
- Contamination signal: the top stations by event count include SIR
  service-range endpoints (Tottenville 19, Huguenot 16) — mentions, not flood
  locations. Motivates the V2 flood-context filter measured below.

## Truth protocol

120-row stratified blind sample (`sample_blind.json`, seed 20260822, 40 old +
80 new) independently hand-labeled by a separate opus agent that never saw
matcher output (`labels.json`): verbatim flood-location station substrings vs
other station mentions, plus system_wide/footer_only/planned_work flags.
`compare.py` scores micro P/R over (row, station) pairs for V1 (all mentions)
and V2 (flood-context filtered).

## Results

Iteration (all scored on the 120-row sample, complex_id grain — "E 143 St" and
"E 143 St-St Mary's St" are the same station; duplicate predictions from
repeated header+description text deduped):

| variant | precision | recall | note |
|---|---|---|---|
| v1 all mentions (alias grain) | 0.195 | 0.803 | FPs = reroute/range/terminal mentions |
| v2 keyword proximity (alias grain) | 0.339 | 0.776 | blunt; kills resumed-alerts |
| v3 cause-anchored, first cut | 0.923 | 0.632 | gate passes; FNs = name-form gaps |
| v3 final (segment aliases, b/t->between, causing/facility bridges, terminate-at blocklist), complex grain | **1.000** | **0.970** | in-sample; only miss is a pronominal reference ("flooded tracks between those stations") |

Flags vs truth: system_wide 117/120, footer_only 120/120, planned_work 120/120.

Cause rules (frozen): forward bridge anchor->AT/NEAR with bounded connector
(on/in/of/from/caused-by/causing, no AND/AT inside), backward bridge requiring
closed/skipped/suspended + because-of/due-to/after or "while we
correct/address/investigate", pre-verb AT/NEAR/bypassing/skipping with a
terminate-at blocklist, and "flooding (conditions) between A and B" spans.
Anchor vocabulary: flood*, water condition(s), water main break.

Deliverable (`events_stations.json`, cause-anchored only): new era 38/99
events with >=1 flood-located station (39 system-wide only, 22 neither), old
era 57/72; median 1 complex/event. Top stations are hydrologically credible:
Richmond Valley (SIR), Times Sq-42 St, Jamaica-179 St, E 143 St-St Mary's St.
**Ida (2021-09-02) yields 0 station-grain labels** — all 29 events are
line-level system-wide phrasing; 2023-09-29 yields 5 stations matching the
research note's event table (Botanic Garden, Newkirk Plaza, Canal St, 86 St,
47-50 Sts-Rockefeller Ctr). The biggest events produce the fewest station
labels; 01's spine absorbs this (Ida's event-day fires via 311 + Storm
Events), but station-grain positives skew to localized incidents.

One rename found (FORMER_NAMES): "149 St-Grand Concourse" -> "149 St-Hostos";
no other rename surfaced in either sample.

## Holdout (rules frozen before labeling)

40 fresh rows (`holdout_blind.json`, seed 99, disjoint from the 120),
independently labeled by a second opus agent that never saw matcher output or
the first sample (`holdout_labels.json`).

**Result: precision 1.000, recall 0.778** (TP 14, FP 0, FN 4, complex grain);
flags 40/40 on all three. The rules were NOT retuned on these misses. FN
anatomy (debugged read-only): 3 of 4 are one family — the second conjunct of
"water condition at A and Tremont Av" is blocked by the deliberate no-AND
guard (the same guard that correctly rejects "at 96 St and signal problems at
86 St"); the 4th is the labeler-uncertain unlocated range ("suspended between
Pleasant Plains and Tottenville because of flooding"), excluded by design.

Build-time recall candidates (each requires validation on a THIRD fresh
sample before adoption — the holdout is spent): B1 allow " AND " when it
directly joins two station aliases after an at-bridge (mirrors the existing
BETWEEN second-endpoint rule; would have recovered all 3 conjunct misses
without touching the signal-problems guard).

## Verdict vs the 01 gate (precision >= 0.90)

**PASS.** In-sample 1.000, frozen-rule holdout 1.000 (zero false positives in
either sample; the first-cut cause variant already passed at 0.923 before any
scoring refinements). Alert station labels are confirmed label-grade for the
01 source mix. Recall 0.970 in-sample / 0.778 holdout is the honest range;
recall costs labels, never contaminates them.
