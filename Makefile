# raincheck (spec A). Every target runs from the repo venv on the brew JDK 17. JAVA_HOME and
# TZ=UTC come from here or .env, never `brew link` (flip JAVA_HOME in .env for the openjdk@11
# fallback). RAINCHECK_ARCHIVE_ROOT (data root, default data/) and RAINCHECK_BRONZE_GB (absolute
# byte budget over <root>/archive) pass through from the shell or .env; empty means default.
-include .env
export JAVA_HOME ?= /opt/homebrew/opt/openjdk@17
export TZ := UTC
export RAINCHECK_ARCHIVE_ROOT RAINCHECK_BRONZE_GB TRANSITLAND_API_KEY
PY := .venv/bin/python

.PHONY: warm ref nbp features picks precip-hourly precip-cell schedule events gold baseline gates slice test topics flood-obs flood-spine flood-coastal precip-flood-era flood-labels flood-matrix flood-fits flood-exposure flood-detector flood-replay flood-replication flood-live flood-panel release-check

topics:  ## recreate the two bus topics to spec C - DESTRUCTIVE: drops retained Kafka messages (Bronze keeps the record)
	$(PY) -m raincheck.topics

warm:  ## start one session through the factory: warms the Ivy cache once (~240 MB), proves the stack
	$(PY) -c "from raincheck.spark import session; s = session(); print('spark', s.version); s.stop()"

ref:  ## build every ref/ lookup table (ticket 02)
	$(PY) -m raincheck.ref

nbp:  ## convert one nycbuspositions UTC day to Bronze VP (make nbp DATE=YYYY-MM-DD)
	$(PY) -m raincheck.nbp $(DATE)

# ~310 one-shot POSTs (~15 min) the first time; every rerun reads the snapshots under
# <root>/snapshots, which stay OUT of the archive root because DEC/DEP bar rehosting.
features:  ## silver/asset_features + silver/cell_stormwater for every point asset (flood 03)
	$(PY) -m raincheck.features

# The slice needs w1 + w2 = 24 zips (C1, D1, C3, D3 x six feeds); downloads 401 + exit 2
# until the ticket-13 Hobbyist/Academic grant is live - run when 13 says approved.
picks:  ## resolve + download one window's historic Picks from Transitland (make picks WINDOW=w1|w2)
	$(PY) -m raincheck.picks pull $(WINDOW)

precip-hourly:  ## Pixel-grain precip for one month (make precip-hourly SRC=aorc MONTH=YYYY-MM)
	$(PY) -m raincheck.precip hourly $(SRC) $(MONTH)

precip-cell:  ## Cell-grain precip for one month (make precip-cell SRC=aorc MONTH=YYYY-MM)
	$(PY) -m raincheck.precip cell $(SRC) $(MONTH)

schedule:  ## load one registered Pick's schedule tables (make schedule PICK=<pick_id sha1>)
	$(PY) -m raincheck.schedule $(PICK)

events:  ## Legs (R2) -> silver/leg_hours and Passages/Delay -> silver/events for one service day (make events DATE=YYYY-MM-DD)
	$(PY) -m raincheck.events $(DATE)

gold:  ## roll leg_hours -> gold/cell_hour_speed and events -> gold/cell_hour_route for one month (make gold MONTH=YYYY-MM)
	$(PY) -m raincheck.gold month $(MONTH)

baseline:  ## dry hour-of-week Speed baseline for one window (make baseline WINDOW=w1|w2)
	$(PY) -m raincheck.gold baseline $(WINDOW)

# --- flood-build ticket 04: flood observations and the event spine ----------------
# Both fetch their sources once into <root>/archive/flood and never again: a present
# snapshot is what makes the tables reproducible years after the literals have moved.
flood-obs:  ## label-grade flood observations -> silver/flood_obs (make flood-obs [SKIP_CANARY=1])
	$(PY) -m raincheck.flood_obs $(if $(SKIP_CANARY),--skip-canary)

flood-spine:  ## the dated flood event spine -> silver/flood_events (make flood-spine [SKIP_CANARY=1])
	$(PY) -m raincheck.flood_spine $(if $(SKIP_CANARY),--skip-canary)

# --- flood-build ticket 07: the coastal rule layer -------------------------------
# Publishes nothing to <root>: surge_margin_ft is arithmetic over silver/asset_features
# and the frozen gauge constants, computed by flood_coastal.unit_margins() at read. This
# target re-cuts the published validation table.
flood-coastal:  ## surge_margin_ft report -> research/flood-07-coastal.md (make flood-coastal [SKIP_CANARY=1])
	$(PY) -m raincheck.flood_coastal $(if $(SKIP_CANARY),--skip-canary) > research/flood-07-coastal.md

# --- flood-build ticket 14: the coastal live tier and the winter-gate fetch --------
# Live reads, no artifact: three CO-OPS gauges against ticket 07's frozen thresholds plus
# one KNYC observation. `--json` is the shape the panel (ticket 15) consumes.
flood-live:  ## coastal chips + the winter-gate observation, now (make flood-live [JSON=1])
	$(PY) -m raincheck.flood_live $(if $(JSON),--json)

# --- flood-build ticket 05: the labels -------------------------------------------
# Positives only. Negatives are generated at read by flood_labels.negatives(); nothing
# in gold/ ever holds a negative row.
flood-labels:  ## flood_obs x ref/assets x the spine -> gold/flood_labels (make flood-labels [CENSUS=1])
	$(PY) -m raincheck.flood_labels $(if $(CENSUS),--census)

# --- flood-build ticket 06: the AORC flood-era precip extension --------------------
# The needed month list is derived from silver/flood_events, never typed; the run is
# disk-checked before it starts and writes a receipt naming the path it took.
precip-flood-era:  ## AORC precip for every fit-era union-event Window (make precip-flood-era [DRY_RUN=1])
	$(PY) -m raincheck.precip_flood_era $(if $(DRY_RUN),--dry-run)

# --- flood-build ticket 08: the training table -------------------------------------
# The (Unit, event) design matrix both fits read. PLUVIAL fit-era events only; positives
# come from gold/flood_labels and the negatives are the read-side anti-join, so the fit
# step is a read and not a judgment call. Needs 03 (features), 05 (labels) and 06 (precip).
flood-matrix:  ## asset_features x flood_labels x AORC precip -> gold/flood_matrix (make flood-matrix [CENSUS=1])
	$(PY) -m raincheck.flood_matrix $(if $(CENSUS),--census)

# --- flood-build ticket 09: the fits, the baselines, the gate -----------------------
# gold/flood_matrix is a READ here; nothing is rebuilt. ~7 min on the real matrix. The
# module writes BOTH build assets itself instead of taking a shell redirect: the run is
# minutes long, and `>` would truncate the last good asset the moment anything raised.
flood-fits:  ## two L2 logistic fits + 4 baselines + the headline gate -> research/flood-09-fits.{md,json}
	$(PY) -m raincheck.flood_fits

# --- flood-build ticket 10: the exposure artifact and the coefficient JSON ----------
# Both flood-09-fits.json and gold/flood_matrix are READS; nothing is refitted or rebuilt.
# Writes gold/flood_exposure (one row per Unit) AND research/flood-10-coefficients.json,
# the one file the detector loads. Byte-identical on a rebuild, so re-running is free.
flood-exposure:  ## flood_matrix x flood-09-fits x flood_coastal -> gold/flood_exposure + the coefficient JSON
	$(PY) -m raincheck.flood_exposure $(if $(CENSUS),--census)

# --- flood-build ticket 11: the detector constants artifact -------------------------
# The SECOND in-repo artifact. Reads nothing derived and builds no table: every value is
# either a frozen rule or is read from the module that already owns it (flood_live's
# budgets and query strings, flood_alerts' remove-water family), so the file cannot drift
# from the code that fetches. detector_version is a sha1 over the DECISION-bearing keys
# only, so it is byte-identical on a rebuild and a reworded note never rolls a live Window.
# The canary is a live HEAD against NODD: SKIP_CANARY=1 for an offline build.
flood-detector:  ## the frozen detector rules -> research/flood-11-detector.json (+ live MRMS pattern canary)
	$(PY) -m raincheck.flood_detect $(if $(SKIP_CANARY),--skip-canary)

# --- flood-build ticket 12: the replay gate -----------------------------------------
# THE SHIPPING GATE. Replays ticket 11's LIVE walk and evaluation, hour by hour, over every
# AORC-era union event on flood 06's precip, and reports what the PROVISIONAL cutpoints
# would have cost: per-event POD / raw FP beside flood 09's own per_event table, the pooled
# FP volume, the signed live-minus-offline feature deltas, and the RadarOnly-vs-Pass2-vs-
# AORC forcing chain. It MEASURES: the verdict ("cutpoints confirmed, or v1 ships
# rank-only") is Ross's and is recorded in research/flood-11-detector.json, which this
# target never writes. ~13 min over 195 events; ONLY=<event_id> or LIMIT=<n> to smoke it,
# RENDER=1 to rebuild only the .md from the committed .json.
flood-replay:  ## replay the live detector over history -> research/flood-12-replay.{md,json}
	$(PY) -m raincheck.flood_replay $(if $(ONLY),--only $(ONLY)) $(if $(LIMIT),--limit $(LIMIT)) $(if $(RENDER),--render-only)

# --- flood-build ticket 15: the flood panel tick and the release checklist -----------
# The tick normally runs INSIDE the 30 s live loop (`python -m raincheck.live_loop`); this
# target is the same one cycle, standalone, for a smoke check. `NOPUB=1` writes the four
# files and uploads nothing - which is what you want anywhere the serve token is absent.
flood-panel:  ## one flood cycle -> web/files/flood*.json (make flood-panel [NOPUB=1] [OUT=dir])
	$(PY) -m raincheck.flood_panel $(if $(NOPUB),--no-publish) $(if $(OUT),--out $(OUT))

# The release checklist flood 09 owed and tickets 10 and 11 both deferred. It re-evaluates
# the headline gate from the published tables with `flood_fits.gate()` rather than reading
# the verdict anyone wrote down, and refuses (rc 1) if the panel and the artifacts disagree.
# Reads only committed files: no data root, no network.
release-check:  ## re-evaluate the flood release gate and the panel's claims (rc 1 = do not release)
	$(PY) -m raincheck.release_check

# --- flood-build ticket 18: the outer replication -----------------------------------
# The 311-threshold and label-radius sweeps, which redefine the event universe and so cannot
# run in fold. Each universe rebuilds 04 -> 05 -> 06 -> 08 -> 09 onto its OWN root under
# <root>/alt/<uid>/ (symlinked inputs); the primary's bytes and its three chained identities
# are hashed before and after. ~10 min a universe, plus AORC months a loosened threshold
# needs. Resumable: per-universe results cache on the alternate root (UNIVERSE=<uid> to
# re-run one, REBUILD=1 to ignore the cache).
flood-replication:  ## alternate 311 thresholds + label radii -> research/flood-18-replication.{md,json}
	$(PY) -m raincheck.flood_replication $(if $(UNIVERSE),--universe $(UNIVERSE)) $(if $(REBUILD),--rebuild)

gates:  ## tier-2 slice acceptance gates: 10-T3, 10-T6 wired; T4/T5 report-only slots
	$(PY) -m raincheck.gates

slice:  ## the whole two-window slice: convert 124 files (T1 each), events x122, gold, baselines, gates
	$(PY) -m raincheck.slice

test:
	$(PY) -m pytest -q

# --- ticket 18: Bronze cold storage (Cloudflare R2 via aws s3 sync) ---------------
# RAINCHECK_COLD_* come from .env; scripts/cold-storage-wizard.sh writes them.
# Recipes are @-silenced so the expanded credentials never echo to the terminal.
.PHONY: coldpush coldcheck coldgaps cutover
COLD = AWS_DEFAULT_REGION=auto AWS_ACCESS_KEY_ID=$(RAINCHECK_COLD_KEY_ID) AWS_SECRET_ACCESS_KEY=$(RAINCHECK_COLD_SECRET) \
	aws s3 --endpoint-url $(RAINCHECK_COLD_ENDPOINT)
COLD_READY = test -n "$(RAINCHECK_COLD_BUCKET)" && test -n "$(RAINCHECK_COLD_ENDPOINT)" \
	|| { echo "cold storage unconfigured - run scripts/cold-storage-wizard.sh"; exit 1; }

coldpush:  ## one-way push of <root>/archive to the R2 bucket; idempotent, never deletes remote
	@$(COLD_READY)
	@echo "coldpush: $${RAINCHECK_ARCHIVE_ROOT:-data}/archive -> s3://$(RAINCHECK_COLD_BUCKET)/archive"
	@$(COLD) sync "$${RAINCHECK_ARCHIVE_ROOT:-data}/archive" "s3://$(RAINCHECK_COLD_BUCKET)/archive" --no-progress

# @-silenced like the rest: the credentials are passed through the environment, never argv.
# The old recipe captured the sync's stdout and never looked at its EXIT STATUS, so a failed
# listing printed "OK - local Bronze fully present remotely" and exited 0 (orchestration 03).
coldcheck:  ## every local Bronze object present remotely at the same size -> rows under <root>/checks/ (exit 1 gap, 2 the remote was never listed)
	@RAINCHECK_COLD_BUCKET=$(RAINCHECK_COLD_BUCKET) RAINCHECK_COLD_ENDPOINT=$(RAINCHECK_COLD_ENDPOINT) \
	RAINCHECK_COLD_KEY_ID=$(RAINCHECK_COLD_KEY_ID) RAINCHECK_COLD_SECRET=$(RAINCHECK_COLD_SECRET) \
	$(PY) -m raincheck.cold

# --- ticket 19: cloud capture runner (box scripts live in systemd/ + scripts/) ----
coldgaps:  ## hour-completeness of one closed UTC day in the bucket (make coldgaps [DATE=YYYY-MM-DD])
	@$(COLD_READY)
	@RAINCHECK_COLD_BUCKET=$(RAINCHECK_COLD_BUCKET) RAINCHECK_COLD_ENDPOINT=$(RAINCHECK_COLD_ENDPOINT) \
	RAINCHECK_COLD_KEY_ID=$(RAINCHECK_COLD_KEY_ID) RAINCHECK_COLD_SECRET=$(RAINCHECK_COLD_SECRET) \
	scripts/coldgaps.sh $(DATE)

cutover:  ## retire the Mac agent once the box proves 7 clean coldgaps days (make cutover [STATUS=1])
	scripts/cutover.sh $(if $(STATUS),--status)

# --- ticket 20: gap backfill from gtfsrt.io (recover archiver sleep-gap hours) ----
.PHONY: gapfill gapcheck gapverify
gapfill:  ## fill missing Bronze hours from gtfsrt.io (make gapfill [KIND=vp] [DATE=D[:D]]; default all five kinds, 2026-08-15..yesterday)
	$(PY) -m raincheck.gapfill fill $(KIND) $(if $(DATE),--date $(DATE))

gapcheck:  ## hour-completeness per kind x closed day -> check-result rows under <root>/checks/ (exit 1 on fillable gaps or a stale gapfill.DEAD entry; DEAD hours still missing are reported, not failed)
	$(PY) -m raincheck.gapfill check

gapverify:  ## sanity: filled hours vs adjacent archiver hours (rows, key coverage, schema); exit 2 INCONCLUSIVE when a kind has no pair to compare (make gapverify [KIND=vp])
	$(PY) -m raincheck.gapfill verify $(KIND)

# --- orchestration ticket 03: Bronze bus schema eras -------------------------------
.PHONY: eras
eras:  ## every verified Bronze bus reader still surfaces the era columns -> rows under <root>/checks/ (exit 1 a reader dropped one, 2 no mixed-era day to read)
	$(PY) -m raincheck.eras

# --- orchestration ticket 08: the Great Expectations suites and Data Docs ------------
# Expects on the check-result rows under <root>/checks/, never on Bronze - GX renders
# unexpected values into Data Docs and Data Docs are published. Needs the optional extra
# (pip install -e '.[gx]'); without it the run is INCONCLUSIVE, not a failure.
.PHONY: gxcheck
gxcheck:  ## GX suites over the check-result rows -> Data Docs at <root>/gx/data_docs (exit 1 a suite failed, 2 a suite could not run)
	$(PY) -m raincheck.gx

# --- orchestration ticket 10: the two NON-nightly suites and their triggers ----------
# Neither is in the nightly declaration and neither is a DAG stage: they expect on data that
# CANNOT CHANGE (the closed backfill era; the reference registry), so they fire on the EVENT
# that could have moved it rather than every morning. Each renders its own Data Docs tree at
# <root>/gx/docs-<suite>; the nightly's <root>/gx/data_docs is the only one published.
#   a backfill chunk lands -> scripts/backfill-verify.py <LO> <HI> [--feeds ...] -> make gxbackfill
#   make ref               -> make refcanary                                     -> make gxref
# make CANNOT carry the three outcomes: GNU make exits 2 for ANY recipe failure, so a module
# rc of 1 arrives here as 2 as well (measured again on these three). Nothing is gated on it -
# none of them is a DAG stage - but to tell a real gap from a could-not-check, invoke the
# module directly or read the persisted batch under <root>/checks/check=<backfill|ref>/.
.PHONY: refcanary gxbackfill gxref
refcanary:  ## the reference canaries (frozen counts, assets_version, key stability) -> rows under <root>/checks/ (exit 1 a canary moved, 2 no ref/assets on this root)
	$(PY) -m raincheck.ref_canary

gxbackfill:  ## GX over the backfill census rows scripts/backfill-verify.py wrote (exit 1 the suite failed, 2 it could not run)
	$(PY) -m raincheck.gx backfill-census

gxref:  ## GX over the reference-canary rows make refcanary wrote (exit 1 the suite failed, 2 it could not run)
	$(PY) -m raincheck.gx ref-canaries

# --- ticket 11: MRMS live precip ---------------------------------------------------
.PHONY: precip-live
precip-live:  ## one live RadarOnly tick -> live/precip_cell (the 300 s LaunchAgent runs this)
	$(PY) -m raincheck.precip_live

# --- ticket 12: the streaming job (on demand, foreground, not a daemon) --------------
.PHONY: stream
stream:  ## Kafka -> live/vp + live/tu until Ctrl-C (make stream FRESH=1 discards the checkpoints)
	FRESH=$(FRESH) $(PY) -m raincheck.stream

# --- ticket 15: the daily catch-up job (its 06:00 America/New_York LaunchAgent) -------
.PHONY: daily
daily:  ## catch up what a sleeping Mac missed: gapfill/verify/check, coldpush/check, events+gold, MRMS month, live prune
	$(PY) -m raincheck.daily

# --- ticket 13: insight export, vendored MapLibre, the static page ----------------
# `make export` needs the slice loaded (gold + baselines + precip); `make vendor` needs
# the network once. web/files/ and web/vendor/ are gitignored derived output.
.PHONY: vendor export web basemap
MAPLIBRE := 5.9.0
# v6 is ESM-only (its package.json exports only `import` and dist/maplibre-gl.js 404s),
# so 5.9.0 is the UMD pin. Checksums pin the bytes, not just the version tag.
MAPLIBRE_JS_SHA := 2276259c7bd8ec632cc055115efdad53783b7da6e7104fad4c4837ea467d908d
MAPLIBRE_CSS_SHA := 43c1d886b5fdf0aac4e7135bd6f84b823d9f48283a648012665f9be52c01389f

# frontend2 02's basemap, and every byte of it is pinned. THREE web assets vendored here
# (a demo must not be one unpkg request from a black screen) and ONE tile archive built by
# `make basemap` below.
#   pmtiles.js       the MapLibre protocol, as the UMD build. The ESM build was tried FIRST
#                    and is NOT usable: `dist/esm/index.js` carries a BARE `from"fflate"`,
#                    which no browser resolves without an import map (measured - node's
#                    resolver refused it; a grep for import lines had missed it in the
#                    minified bundle). `dist/pmtiles.js` bundles fflate, defines the global
#                    `pmtiles`, and is a classic tag beside MapLibre's, which is the shape
#                    this page already has for a vendored library.
#   basemap-dark.json  the STYLE: protomaps-themes-base's prebuilt DARK flavour, the layer
#                    list the page splices in. Never fetched from a third host at runtime.
#   notosans-0-255.pbf  ONE glyph range for ONE fontstack. MapLibre cannot draw a label
#                    without glyphs, and the style names three stacks (Regular/Medium/
#                    Italic); web/basemap.js collapses all three onto this one, which is
#                    also the right call visually - the basemap must recede under the
#                    Cell ramp, not carry a weight hierarchy of its own. 0-255 is Latin-1,
#                    which is every place name in the extract's frame.
PMTILES_JS := 4.5.0
BASEMAP_THEME := 4.5.0
PMTILES_JS_SHA := caf981bc46f6327ee7e65d5dc964d89d38a69f60edca2bd4c5c890c21b554c6c
BASEMAP_STYLE_SHA := 58080437fe322014b1ed41bca8c01c0c98151b777602fc018ef7194d89de0fbb
BASEMAP_FONT_SHA := 62c6d49b15fa836eb6aa45e259c7ca6762f44b011b09e47776efbe4a6db1b397

# Download to .new, verify, and only then replace: writing straight to the final path would
# destroy the last known-good copy on the way to failing the checksum.
vendor:  ## fetch the pinned web assets into web/vendor (no CDN at demo time): MapLibre, PMTiles, the basemap style and its glyphs
	@mkdir -p web/vendor
	curl -fsSL -o web/vendor/maplibre-gl.js.new https://unpkg.com/maplibre-gl@$(MAPLIBRE)/dist/maplibre-gl.js
	curl -fsSL -o web/vendor/maplibre-gl.css.new https://unpkg.com/maplibre-gl@$(MAPLIBRE)/dist/maplibre-gl.css
	curl -fsSL -o web/vendor/pmtiles.js.new https://unpkg.com/pmtiles@$(PMTILES_JS)/dist/pmtiles.js
	curl -fsSL -o web/vendor/basemap-dark.json.new https://unpkg.com/protomaps-themes-base@$(BASEMAP_THEME)/dist/styles/dark/en.json
	curl -fsSL -o web/vendor/notosans-0-255.pbf.new 'https://protomaps.github.io/basemaps-assets/fonts/Noto%20Sans%20Regular/0-255.pbf'
	@printf '%s  %s\n' "$(MAPLIBRE_JS_SHA)" web/vendor/maplibre-gl.js.new \
	                   "$(MAPLIBRE_CSS_SHA)" web/vendor/maplibre-gl.css.new \
	                   "$(PMTILES_JS_SHA)" web/vendor/pmtiles.js.new \
	                   "$(BASEMAP_STYLE_SHA)" web/vendor/basemap-dark.json.new \
	                   "$(BASEMAP_FONT_SHA)" web/vendor/notosans-0-255.pbf.new | shasum -a 256 -c - \
	  || { rm -f web/vendor/*.new; \
	       echo "vendor: checksum FAILED, previous copies left untouched"; exit 1; }
	@for f in maplibre-gl.js maplibre-gl.css pmtiles.js basemap-dark.json notosans-0-255.pbf; do \
	   mv web/vendor/$$f.new web/vendor/$$f; done
	@echo "vendor: maplibre-gl $(MAPLIBRE), pmtiles $(PMTILES_JS), basemap theme $(BASEMAP_THEME) verified"

export:  ## insight files from Gold -> web/files (make export [GATE=0.30] sweeps the interval gate)
	$(PY) -m raincheck.export $(if $(GATE),--gate $(GATE))

# frontend2 02's basemap. `pmtiles extract` range-reads the pinned daily planet build and
# writes only the tiles inside the bbox - 69 requests for 52 MB out of a 128 GiB archive,
# which is the whole argument for the format. MEASURED byte-DETERMINISTIC (two runs of the
# line below produced identical sha256), which is what makes the output pin below mean
# something rather than decorate.
#
# WHEN THE BUILD DATE 404s (Protomaps keeps roughly three weeks of daily builds), this is a
# TWO-LINE edit and not a redesign: pick a date from https://maps.protomaps.com/builds,
# set PMTILES_BUILD, run the extract, and record the new NYC_PMTILES_SHA. That is the same
# bump `make vendor` takes when MapLibre moves.
#
# The bbox is the METRO frame, not the five boroughs: the page opens at zoom 10.1 and pans,
# so a city-tight extract would end in a hard edge inside the first viewport. Measured
# alternatives at the same build - city z0-15 116 MB, city z0-14 38 MB, city z0-13 16 MB,
# metro z0-15 316 MB, metro z0-13 52 MB. maxzoom 13 with MapLibre overzooming past it keeps
# roads and shorelines legible all the way in, on a page whose subject is a ~1,200-Cell
# citywide ramp and not a street atlas.
PMTILES_BUILD := 20260824
BASEMAP_BBOX := -74.90,40.10,-72.90,41.30
BASEMAP_MAXZOOM := 13
NYC_PMTILES_SHA := c5b08d90657332ef297135204715f965bdc60c2157b5dffe3485eab31f5e6fc3

basemap:  ## build the pinned NYC PMTiles basemap into web/tiles (needs the pmtiles CLI)
	@command -v pmtiles >/dev/null || { echo "basemap: the pmtiles CLI is not on PATH."; \
	  echo "  brew install pmtiles   (or a pinned release from"; \
	  echo "  https://github.com/protomaps/go-pmtiles/releases)"; exit 1; }
	@mkdir -p web/tiles
	pmtiles extract https://build.protomaps.com/$(PMTILES_BUILD).pmtiles web/tiles/nyc.pmtiles.new \
	  --bbox=$(BASEMAP_BBOX) --maxzoom=$(BASEMAP_MAXZOOM)
	@printf '%s  %s\n' "$(NYC_PMTILES_SHA)" web/tiles/nyc.pmtiles.new | shasum -a 256 -c - \
	  || { rm -f web/tiles/nyc.pmtiles.new; \
	       echo "basemap: checksum FAILED, previous copy left untouched"; exit 1; }
	@mv web/tiles/nyc.pmtiles.new web/tiles/nyc.pmtiles
	@echo "basemap: nyc.pmtiles from build $(PMTILES_BUILD) verified - publish it with 'make publish FAMILY=tiles'"

# NOT `python -m http.server`: it answers 200 with the WHOLE body to a Range request, and a
# PMTiles archive is nothing but range requests, so the basemap would download 52 MB per
# tile fetch and never render. raincheck.webserve is that server plus single-range support.
web:  ## serve web/ with the stdlib server, Range included (make web [PORT=8000])
	$(PY) -m raincheck.webserve $(or $(PORT),8000) --directory web

# --- orchestration ticket 13: the showcase surface ---------------------------------
.PHONY: showcase
showcase:  ## the portfolio surface -> web/showcase (make showcase [LOGS=<airflow log dir> LABEL=probe|shadow|nightly])
	$(PY) -m raincheck.showcase $(if $(LOGS),--logs $(LOGS) --label $(LABEL))

# --- flood-build 19: DEP's design-storm extents, kept as polygons -------------------
# Reads the same sha-pinned snapshot `make features` does and writes a table nothing
# hashed into features_version touches. `make geo` needs `make stormwater-extent` first.
# NOTE both targets can exit 2 for a check that could not run - and GNU make exits 2 for
# ANY recipe failure, so read the batch under <root>/checks/check=stormwater_extent/ or
# invoke the module directly if you have to tell "could not read" from "broke".
.PHONY: stormwater-extent geo
stormwater-extent:  ## DEP's four scenario extents -> silver/stormwater_extent + check rows (flood-build 19)
	$(PY) -m raincheck.stormwater_extent

geo:  ## the current-sea-level extents -> web/files/geo/*.geojson (publish family `geo`)
	$(PY) -m raincheck.stormwater_extent --geo

# --- ticket 14: the live export loop (foreground, 30 s, Ctrl-C stops it) -----------
.PHONY: live-export
live-export:  ## live.geojson + meta.json every 30 s (make live-export [SOURCE=bronze] [ONCE=1])
	$(PY) -m raincheck.live_export $(if $(SOURCE),--source $(SOURCE)) $(if $(ONCE),--once)

# --- cloud ticket 08: cost guardrails and the downscale path ----------------------
# Neither is a pipeline stage, so neither belongs in `daily`: bill-review is monthly and
# writes into the ticket file, downscale is the escape hatch you exercise on purpose.
.PHONY: bill-review downscale
bill-review:  ## one month of Project=raincheck-cloud spend vs the $200 envelope (make bill-review [MONTH=YYYY-MM] [APPEND=1]); rc 1 = hard look, rc 2 = could not check
	scripts/cloud-bill-review.sh $(MONTH) $(if $(APPEND),--append)

downscale:  ## the two-EC2 escape hatch (make downscale [DO=plan|up|run|down] [BOX=floor|build]); plan touches no AWS
	scripts/downscale.sh $(or $(DO),plan) $(BOX)

# --- cloud ticket 07: the AWS half of "no inbound from the internet" ---------------
# The manifest test covers the Kubernetes half with no cluster; security groups live in
# AWS where no test can see them, and with no NAT Gateway they are what keeps the
# internet out. rc 0 clean, 1 violations, 2 INCONCLUSIVE (the describe itself failed).
.PHONY: inboundaudit
inboundaudit:  ## cluster security groups vs deploy/cloud/inbound-allowlist.yaml (needs AWS creds)
	$(PY) scripts/inbound-audit.py

# --- cloud ticket 09: the public static host ---------------------------------------
# One family per invocation, each on its own cadence (see raincheck.publish). The bucket
# is raincheck-public and never raincheck-bronze; the host lives OUTSIDE the cluster, so
# nothing here touches kubectl and no cluster rule is drawn for it.
# The module exits 3 when the MTA redistribution gate is closed - a designed state, not a
# failure - but MEASURED: make flattens any recipe failure to its own rc 2, so anything
# that has to tell "gated" from "broken" calls the module, never this target.
.PHONY: publish
publish:  ## publish one payload family to the public static host (make publish FAMILY=site|insight|live|docs|history|showcase [DRY=1])
	$(PY) -m raincheck.publish --family $(FAMILY) $(if $(DRY),--dry-run)
