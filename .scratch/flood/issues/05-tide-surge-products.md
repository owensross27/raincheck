# 05 Tide/surge history and nowcast products

Type: research
Status: resolved

## Question

Two halves. History: which NYC-area CO-OPS stations beyond the Battery 8518750
(Kings Point 8516945? others in/near the five boroughs) have long water-level
records and published flood thresholds, so coastal exposure isn't a single-point
series; exact rules to build an exceedance-day/hour series in NAVD88 (datum
param vs the 6.06 ft STND offset, `hourly_height` vs `high_low` traps already
known). Real-time: what keyless products exist for surge/coastal-flood nowcast
and short-term forecast — CO-OPS 6-min obs + predictions, NWS/NOS surge guidance
(ETSS/STOFS/P-Surge), coastal flood advisories/warnings via IEM watchwarn — with
endpoints, cadence, and horizon, for the detector ticket. Capture as
`research/flood-05-tide-surge.md` (Verdict / Evidence / Unverified).

## Answer

Six CO-OPS stations qualify for NYC-area flood thresholds (Battery 8518750,
Kings Point 8516945, Sandy Hook 8531680, Bridgeport 8467150, New Haven 8465705,
New London 8461490) — Robbins Reef 8530973 is currents-only, no thresholds, no
historic series. `datum=NAVD` works directly on `datagetter`; the STND->NAVD88
offset is per-station, not the Battery's 6.06 (Kings Point is 17.09). `high_low`
truncation is 1979-1980 station-dependent, not a fixed 1979. For real-time:
STOFS-2D-Global is live and directly fetchable (grib2, 4x/day, 0-180h horizon)
as ETSS's dead replacement; P-Surge is reachable but empty absent an active
storm; IEM `watchwarn.py` returns real coastal-flood hits for OKX but silently
ignores `phenomena[]`/`significance[]` filters unless `limitps=yes` is set.
Full findings: `research/flood-05-tide-surge.md`.
