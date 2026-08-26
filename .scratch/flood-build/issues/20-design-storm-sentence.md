# 20 — The design-storm sentence

**What to build:** the live MRMS rain rate placed against DEP's discrete design-storm
intensities, rendered beside the extents. Box: `DESTINATION-PLAN.md` §2. What it CLAIMS:
"DEP's planning-grade map marks these areas for a storm of this intensity; MRMS measured X
in/hr here in the last hour." What it never claims: that water is present, or that a tier
moved (D2).

**Gate:** flood-build 19 + flood-build 15. Held to wave 8 — it edits flood 15's tick in
`live_loop.py`, the file flood 17 owns alone in wave 7.

**Status:** not-started — this file exists so far only to carry what 19 measured.

---

## FROM flood-build 19 (2026-08-25, branch `floodbuild19-stormwater-extents`)

### The table you bracket against

**`silver/stormwater_extent/`** on the data root — GeoParquet, CRS84, one row per polygon:

```
scenario  horizon  rain_in_hr  category  poly  geometry  src_asof  zip_sha256
```

`src_asof` is `2026-08-23` and `zip_sha256` is `features.SW_ZIP_SHA256` on every row, so a
sentence can name the snapshot it is speaking about without a second lookup. Read the
intensities from `stormwater_extent.SCENARIOS` (`Scenario.rain_in_hr`) or from the table —
**do not retype them into `live_loop.py`**; a bracket whose thresholds are a third copy is
how the two homes drift.

### THE THREE LITERAL INTENSITIES, and what your bracket can honestly say

| `rain_in_hr` | `scenario` | `horizon` | built | on the public host |
| --- | --- | --- | --- | --- |
| **1.77** | `limited` | `current` | **NO** — see below | no |
| **2.13** | `moderate` | `current` | yes | **yes** |
| **2.13** | `moderate` | `2050` | yes | no (D3) |
| **3.66** | `extreme` | `2080` | yes | no (D3) |

**Two of the three brackets have no extent a reader can look at**, and the sentence has to
survive that rather than imply otherwise:

- **1.77 in/hr is not in the table at all.** DEP's Limited geodatabase stores its feature
  class in Esri's compressed CDF container; the open `OpenFileGDB` driver cannot decompress
  it (GDAL 3.8.5 reads ZERO features silently, GDAL 3.12.4 refuses the dataset), and no
  queryable service exists for this data. A bracket that says "below Limited" is naming a
  number that is real — DEP publishes the intensity — but an extent nobody can draw.
- **3.66 in/hr exists only at 2080 sea level**, and D3 keeps sea-level-rise horizons off the
  public host. So "above Moderate, approaching Extreme" is a sentence about an intensity
  whose map the reader cannot open.

The honest v1 is therefore a sentence about **the one extent that is drawn** — "MRMS
measured X in/hr here in the last hour; DEP's Moderate design storm (2.13 in/hr) marks
these areas" — with the other two intensities named as context and NOT as layers. If you
want the other two drawable, that is a source problem (Limited) and a Ross decision
(2080), not a rendering one.

### ANSWERED 2026-08-26 by forecast 01 — what DEP's "2.13 in/hr" IS

**It is a ONE-HOUR DEPTH read off an IDF curve, so it IS the same estimand as `mm_1h`.**
This section used to say the item was unresearched and told you not to write the sentence.
It is researched now; write the sentence.

Settled from DEP's own methodology source — the *NYC Stormwater Resiliency Plan* (2021),
which the Socrata dataset `9i7c-xyvv` names as its methodology in its own description
(`www1.nyc.gov/assets/orr/pdf/publications/stormwater-resiliency-plan.pdf`, read
2026-08-26; **WebFetch 403s on nyc.gov, plain `curl -A "Mozilla/5.0"` gets it**):

> "The methodology used to design sewers for runoff conveyance is based on precipitation
> **intensity-duration-frequency (IDF) curves** ... The data are analyzed and arrayed
> graphically as **precipitation intensity (inches/hour) as a function of rainfall
> duration** (minutes or hours)."

> "The standard design criterion in New York City is to use the intensity-duration values
> based on a storm with a 5-year return period (**e.g., 1.75 inches per hour for a one
> hour storm** ...)"

> Moderate: "approximately **two inches of rain falling in one hour** (also referred to as
> the 10-year storm ...)". Extreme: "approximately **3.5 inches of rain falling in one
> hour** (also referred to as the 100-year storm ...)".

An "in/hr" at duration = 1 hour is the depth that falls in that hour. **So the bracket is
arithmetic between two of the same quantity, not a category error.** In mm:

| scenario | in/hr | **mm in one hour** |
| --- | ---: | ---: |
| limited | 1.77 | **44.96** |
| moderate | 2.13 | **54.10** |
| extreme | 3.66 | **92.96** |

**Convert at read time from `stormwater_extent.SCENARIOS` — do NOT retype these mm values
into `live_loop.py`.** They are `rain_in_hr * 25.4` and that is the only home the inch
figures should have (19's MUST, unchanged).

### THREE QUALIFIERS THE SENTENCE MUST CARRY

1. **The DEP numbers are NOT the historical IDF, so do not print "the 10-year storm" and
   "2.13 in/hr" as if they were one claim.** NOAA Atlas 14 Vol 10 v3 at Central Park
   (40.7823, -73.9654), partial-duration, **60-minute depths in inches**: 1-yr 1.07 ·
   2-yr 1.28 · 5-yr 1.62 · **10-yr 1.90** · 25-yr 2.28 · 50-yr 2.57 · **100-yr 2.88**
   (`hdsc.nws.noaa.gov/cgi-bin/hdsc/new/fe_text_mean.csv`, 2026-08-26). DEP's 2.13 is
   **12% above** Atlas 14's 10-yr and 3.66 is **27% above** its 100-yr — the plan's own
   text records why (Cornell NRCC projections take the Central Park 5-yr/1-h from an
   observed 1.63-1.83 in/hr to a projected **2.15 in/hr for 2040-2069**). Quote DEP's
   label OR the frequency, never both as agreeing.
2. **STILL OPEN, and it bounds what the extent half of the sentence may claim.** "The
   models input **complex rainfall hyetographs** compounded with tidal conditions." The
   headline intensity is the hour's depth; the flood EXTENT depends on how that depth was
   distributed *inside* the hour, and an hourly total does not carry that. The plan's
   Appendix B describes the InfoWorks ICM 1D-2D build and the validation and **never
   states the hyetograph shape or the total storm duration**. So the honest form compares
   the *intensity* to DEP's *intensity* and says DEP "marks these areas for a storm of
   this intensity" — it must not imply that reaching 54.10 mm in an hour reproduces the
   drawn extent.
3. **The rainfall figure is identical at both sea levels** (Moderate current-SL and
   Moderate 2050 are both 2.13 in/hr; only the tide boundary differs). That is what
   `horizon` already encodes — do not let the sentence imply the rain differs.

### BASE RATE — measured, so the sentence knows how often it can fire

`live/precip_cell`, **111 retained hours x 4,113 Cells = 456,543 Cell-hours** (2026-08-26):
**Limited reached in 18 Cell-hours (0.0039%), in 1 of 111 hours; Moderate 0; Extreme 0.**
Highest single-Cell `mm_1h` in the whole window: **53.93 mm — 0.17 mm short of Moderate.**
It is not vanishing over a longer record (Ida's hour ending 2021-09-02 02:00Z put **1,945
of 4,113 Cells at or above 54.1 mm** in AORC), but on a normal live week the bracket sits
below Limited essentially always. Size the sentence's default wording for that, not for Ida.

### AND THE FORECAST VARIANT IS OFF THE TABLE (forecast 01, 2026-08-26)

DESTINATION-PLAN D4 imagined this bracket applied to a FORECAST rate as the honest carrier
for Ross's word "might". **forecast 01 recommends NONE**, so 20 stays a sentence about the
**live MRMS** rate only. The short reason: over the 24 wettest citywide NYC hours
2014-2025, HRRR's CSI at 54.10 mm/h is **0.185 at 1 h lead, 0.006 at 2 h, 0.000 at 3-4 h**
(zero hits in 3,482 Cell-hours), and its one skilful lead publishes **9.06 min** ahead of
the MRMS observation this project already ingests. Full detail:
`~/vault/nyc-precip-forecast-reference.md`.

### What is NOT yours

`features_version` must not move. This bracket is DISPLAY (D2): adding a stormwater term to
the detector means new columns in `silver/cell_stormwater` -> `features_version` ->
`matrix_version` -> a refit. flood 19 asserts the stamp on both sides of its own run for
the same reason; keep the sentence on the serving side of that line.
