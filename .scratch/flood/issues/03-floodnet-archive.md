# 03 FloodNet sensor data access

Type: research
Status: resolved

## Question

FloodNet NYC (floodnet.nyc) street-flood sensors: API endpoints and auth, sensor
count and locations (lat/lon), deployment dates and coverage growth since 2020,
measurement grain (depth in what units, sampling interval), historical bulk
download path, data license/terms, and any documented data quirks (sensor
dropouts, snow/ice false positives). This is the highest-confidence ground-truth
tier for the exposure score and a candidate real-time detector input, so exact
access paths and coverage dates matter. Capture findings as
`research/flood-03-floodnet.md` in the style of the existing research notes
(Verdict / Evidence with HTTP statuses / Unverified).

## Answer

Full findings: `research/flood-03-floodnet.md`.

FloodNet has a real, keyless, currently-working REST + GraphQL API at
`api.floodnet.nyc` (found via the project's public onboarding Colab
notebooks, not the marketing site). Live-verified: 440 sensor deployments
(385 pluvial, 55 coastal), deployment dates spanning 2020-10-05 to
2026-08-13, depth in millimeters at ~60s sampling (5-min pre-Nov-2021), and
per-sensor historical time series reachable back through Hurricane Ida
(2021-09-01) via the same API — capped at ~10,000 rows/request today, so a
backfill needs date-range chunking. No anonymous single-file bulk download
exists; full per-minute CSVs require a data-request form + gated Google
Drive. Data license is a custom NYU/CUNY non-commercial agreement (not the
CC BY-NC-SA 4.0 tag on the GitHub docs repo). Documented quirks: nightly
baseline recalibration, three named noise classes (blips/boxes/complex
noise) from objects under the sensor, a 254 mm/min rate-of-change filter,
`null` on no-echo dropouts, and a live homepage banner warning snow can
produce false-positive-like readings.
