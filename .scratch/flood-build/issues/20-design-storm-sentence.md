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

### The unresearched item this ticket still carries

**What DEP's "2.13 in/hr" actually IS** — a peak instantaneous rate, an hourly depth, or a
design-storm hyetograph total — is still not established, and it decides whether an MRMS
hourly `mm_1h` is comparable to it at all. flood 19 did not settle it: the geodatabases
carry the intensity in their names and in the coded-domain descriptions, and nothing in the
FGDB metadata defines the measurement. **Do not write the comparison sentence before this
is answered**; a bracket between two quantities with different definitions is a category
error dressed as arithmetic, and it is exactly the kind of claim this project's honesty
strings exist to prevent.

### What is NOT yours

`features_version` must not move. This bracket is DISPLAY (D2): adding a stormwater term to
the detector means new columns in `silver/cell_stormwater` -> `features_version` ->
`matrix_version` -> a refit. flood 19 asserts the stamp on both sides of its own run for
the same reason; keep the sentence on the serving side of that line.

---

## FROM frontend2 03 (2026-08-26) — THE ZONE LAYER YOUR SENTENCE NAMES IS ON THE PAGE

Your sentence places a live MRMS rate against DEP's discrete design-storm intensities. The
extents are now RENDERED, so the sentence has something to point at and must agree with it.

**THE LAYER, ITS IDS AND ITS PAYLOAD.** `LAYERS` id **`stormwater`**, name
"Ground: flood zones (DEP design storm)", map layers **`stormwater-fill`** and
**`stormwater-line`**, source **`stormwater`**. It is `open: false` and fetches nothing until
ticked. Its FIRST source is `files/geo/scenarios.json` — the manifest `make geo` writes, one
row per `horizon = 'current'` scenario in `silver/stormwater_extent` with `scenario`,
`horizon`, `rain_in_hr` and the `key` of that scenario's geojson — and the selected
scenario's payload is a SECOND source the draw adds. **Today the manifest has exactly one
row: `moderate`, 2.13 in/hr.** One scenario is visible at a time, chosen by a radio inside
the layer's own row that is BUILT FROM THE MANIFEST, so a second scenario is a data change.

**READ `rain_in_hr` FROM THE MANIFEST OR FROM `stormwater_extent.SCENARIOS`, NEVER RETYPED.**
1.77 / 2.13 / 3.66 are that module's constants. The page interpolates the manifest's value
into the radio label and prints DEP's own `attribution` string from the payload rather than a
copy of it — the same rule applies to your sentence: if it states an intensity, derive it.

**THE HONESTY LINE IS ALREADY ON SCREEN AND YOURS MUST NOT CONTRADICT IT.** The zone legend
renders: *"DEP design storm: 2.13 in/hr, current sea level. A PLANNING map of what would
flood at that rain rate - not an observation of water, not a forecast, and not a
site-specific determination."* Your sentence is the one that places a MEASURED rate against
those intensities; keep it to that and do not restate the planning-grade caveat in different
words, or the page says the same thing twice and slightly differently.

**`not_analyzed` IS A CATEGORY AND IT IS ON SCREEN.** It has its own swatch, its own legend
row (*"DEP did not model here — this is NOT 'no flooding'"*) and a deliberately recessive
opacity (0.16 against the depths' 0.5, because the mask polygons are the big ones and at the
depths' opacity they wash the city out). **A sentence that brackets a live rate between
scenarios must not imply that everything unpainted was modelled and found dry.**

**ONE RAMP ON SCREEN (D1) BINDS ON ANYTHING YOU ADD.** While a Cell fill is lit the zones are
outlines and the route line is uncoloured; the rule lives in `insight.js applyRamp()`. Your
sentence is TEXT, so it is unaffected — but if it ever grows a mark on the map, it joins the
rule.

**AND THE SEAM YOU ALREADY OWN IS UNCHANGED BY THIS TICKET:** frontend2 03 touched no
`src/raincheck/` module except `export.py` (a `--geo` mode over a new `web/geo.sql`), and
`live_loop.py` / `flood_panel.py` are byte-identical to master on this branch.
