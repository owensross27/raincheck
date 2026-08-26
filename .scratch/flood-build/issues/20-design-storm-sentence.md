# 20 — The design-storm sentence

**What to build:** the live MRMS rain rate placed against DEP's discrete design-storm
intensities, rendered beside the extents. Box: `DESTINATION-PLAN.md` §2. What it CLAIMS:
"DEP's planning-grade map marks these areas for a storm of this intensity; MRMS measured X
in/hr here in the last hour." What it never claims: that water is present, or that a tier
moved (D2).

**Gate:** flood-build 19 + flood-build 15. Held to wave 8 — it edits flood 15's tick in
`live_loop.py`, the file flood 17 owns alone in wave 7.

**Status:** not-started — this file exists so far only to carry what 19 and 17 measured.

---

## THE SEAM YOU EDIT, from flood-build 17 (LANDED 2026-08-26, `flood17-live-impact-overlays`, `bb8d76f`)

**The reason you were held to wave 8 is now landed, so read the tick before you touch it.**
`live_loop.py` is UNCHANGED by flood 17 except for one docstring line — the overlays were
merged into flood 15's existing `flood_panel.tick`, **not** added as a second call — and a
test now enforces that: `tests/test_live_loop.py::test_the_impact_overlays_add_no_second_call_to_this_cycle`
walks the AST of `live_loop.py` and **fails if `cycle()` calls `.tick(` more than once**,
and fails if the string `flood_overlay` appears in the file at all. **Do the same thing
flood 17 did: merge into `flood_panel._tick`, never into `live_loop.cycle()`.**

**WHAT MOVED IN `flood_panel.py`, and it is what you will collide with:**

- `UNGATED, GATED, IMPACT` and **`ORDER = (UNGATED, GATED, IMPACT)`** — `write()` and
  `ship()` both loop over `ORDER`, so a fourth family is one tuple entry plus a `FILES`
  key, nothing else.
- `payloads(read, uni, truth, coastal, winter, det, art, now, impact=None)` — the new
  argument is **keyword-with-a-default on purpose**: `release_check._sample_payloads()`
  calls it positionally with eight arguments and must keep working. Add yours the same
  way.
- `_tick` calls `flood_overlay.read(con, root, now)` once and puts the result on state
  under `"impact"`. Your design-storm read belongs beside it, on the same `now`.
- `line()` appends `flood_overlay.line(state.get("impact"))`. One log line per tick is the
  supervision surface; add your field to it rather than printing a second line.

**THE MEMORY BUDGET IS TIGHTER THAN IT WAS.** MEASURED on the real root 2026-08-26, same
machine, back to back, three runs each: the tick peaks at **348.8 MiB on master and
410.2 MiB with both overlays live (+61 MiB)**, elapsed unchanged at ~1.0 s. The pod limit
is **768 Mi** and the *request* in `deploy/k8s/raincheck/live.yaml` is 512Mi. **You have
roughly 350 MiB of headroom to the limit and you are the next thing spending it** — put
your projection and predicate INSIDE the read's own statement and MEASURE, or the
regression is an OOMKill rather than a slow test.

**`flood_overlay` is where a per-Cell overlay key goes now.** `files/impact.json`'s `cells`
is keyed by the H3 hex string, absent-never-null, one dict per Cell — the same shape
`flood.json`'s `cells` has, which is where flood 15's docstring says your `design_storm`
per-Cell key belongs. Adding a key to either is additive under `contract.PROMISE[1]`; do
NOT bump `contract.CONTRACT`.

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
