# THROWAWAY — frontend ticket 02's three variations

**This is not the implementation.** It exists to answer one question:
`.scratch/frontend/issues/02-four-layers-prototype.md` — how do the seven layers ticket 01
settled read together on ONE page? Nothing here belongs in `src/` or `web/`.

## Run it

The payloads under `data/` are **gitignored** — the repo's root `.gitignore` excludes every
`data/` directory, which is the right rule here: they are derived, they need the real data
root, and `make-data.py` rebuilds all of them in about a minute. So, from the repo root:

```
RAINCHECK_ARCHIVE_ROOT=$PWD/data PYTHONPATH=src .venv/bin/python \
    .scratch/frontend/prototypes/make-data.py
python3 -m http.server 8080
```

| what | url |
|---|---|
| variant A — Stack (one fill) | http://localhost:8080/.scratch/frontend/prototypes/proto.html?variant=A |
| variant B — Channels (all at once) | http://localhost:8080/.scratch/frontend/prototypes/proto.html?variant=B |
| variant C — Ledger (map is the index) | http://localhost:8080/.scratch/frontend/prototypes/proto.html?variant=C |
| all three at **375 px** | http://localhost:8080/.scratch/frontend/prototypes/phone.html |

`←`/`→` or the pill at the top cycle variants. **`gate`** flips the three MTA-gated layers on
so the lit state can be judged too; they are DARK by default, which is today's truth
(`publish.LIVE_TERMS_VERIFIED = None`). `?gate=open` does the same from the URL.

Serve from the **repo root**, not from `web/` — `make web` passes `--directory web` and
cannot see this folder. The prototype reads `../../../web/` for the vendored MapLibre, the
real insight payloads and `web/app.css`, which it reuses verbatim rather than restyling.

## Where every byte on screen comes from

| file | what it is | invented fields? |
|---|---|---|
| `web/files/{cells,zones}.geojson`, `headline.json` | the REAL published insight payloads | none — untouched |
| `research/14-serving-prototype/files/{live.geojson,meta.json}` | the REAL ticket-14 fleet fixture, 847 vehicles | none |
| `data/truth.json` | `flood_truth.truth()` run for real against `data/` on 2026-08-24 — 386 FloodNet sensors, 1 reporting water, MTA tier `chips: []` | none |
| `data/history/*.json` | `raincheck.query('events_for_asset', mode='public')` run for real, 40 assets | none |
| `data/markers.geojson` | `ref/assets JOIN gold/flood_labels`, all **7,955** assets with history | **key names are a PROPOSAL** — see below |
| `data/impact.json` | `gold/cell_hour_speed`, 1,106 Cells, densest closed hour | **wrapper keys are a PROPOSAL** — see below |
| `data/complexes.json` | `ref/assets` complexes — the lookup a chip cannot do without | none |
| `data/chips-demo.json` | **the ONE fixture** | shape copied verbatim from `flood_truth.chips()` |

Regenerate with `make-data.py` (the header of that file records each query).

### Why one fixture, and what it does not contain

`flood_truth.mta()` returns `chips: []` today — no "water from the tracks" alert in the last
6 h — and a permanently empty layer cannot be designed against. `chips-demo.json` is
therefore the only invented payload, and it is cut to `flood_truth.chips()`' **verbatim dict
shape** (`event_id`, `stations[{complex_id, name, state}]`, `alert_ids`, `first_seen`,
`last_seen`, `state`, `age_min`) with real `complex_id`/`name` pairs out of `ref/assets`. It
carries **no real alert prose and no real `alert_ids`** — the `alert_ids` are the literal
strings `FIXTURE-0/1/2`.

### Where a schema does not exist yet, and nothing was invented to cover it

Flood 15's three export files and flood 17's two overlays are described in prose only
(`.scratch/flood-build/spec.md:410-416`, `issues/15`, `issues/17`); **no code has shipped and
no key names are frozen.** Notify 05's manifest is the same — the spec says "id, kind, event
count" in prose and `query.py` uses `asset_id`, never `id`. So rather than invent a payload
and dress it as frozen, the prototype paints those three layers from **their own real
inputs**: the truth tiers from `flood_truth.truth()`, the impact overlay from
`gold/cell_hour_speed`, the history layer from the `ref/assets`+`flood_labels` join those
tickets will read. Every wrapper key those files carry is marked a PROPOSAL above.

## What the prototype honours from ticket 01, so it tests the real thing

- ONE page with per-layer toggles; **no second page and no modes**.
- Every layer **declares at boot** with an empty `FeatureCollection` + `visibility:"none"`.
  There is not one lazy `addSource`/`addLayer` in `proto.js`.
- **`promoteId` is off everywhere.**
- Age is `<origin Date header> − <Last-Modified header>`, read per SOURCE off the response
  the page already made — never a payload stamp. Verified working: `python -m http.server`
  sends both, and the panel shows real ages.
- The live pair keeps its `vp_age_s` composite on top of file age.
- Vocabulary FRESH / STALE(+reason) / OFF / GATED — plus **AGE**, see the finding below.
- `#provenance` is mounted in all three variants and no variant can hide it.
- Freshness is not verdict: flood 15's tier states are rendered as the tier's own words
  (`state: water|dry|stale`, `display`, the muted/unknown counts), never merged into the
  freshness chip.
