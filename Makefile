# raincheck (spec A). Every target runs from the repo venv on the brew JDK 17. JAVA_HOME and
# TZ=UTC come from here or .env, never `brew link` (flip JAVA_HOME in .env for the openjdk@11
# fallback). RAINCHECK_ARCHIVE_ROOT (data root, default data/) and RAINCHECK_BRONZE_GB (absolute
# byte budget over <root>/archive) pass through from the shell or .env; empty means default.
-include .env
export JAVA_HOME ?= /opt/homebrew/opt/openjdk@17
export TZ := UTC
export RAINCHECK_ARCHIVE_ROOT RAINCHECK_BRONZE_GB TRANSITLAND_API_KEY
PY := .venv/bin/python

.PHONY: warm ref nbp features picks precip-hourly precip-cell schedule events gold baseline gates slice test topics flood-obs flood-spine flood-coastal precip-flood-era flood-labels flood-matrix flood-fits flood-exposure flood-replication flood-live

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
gapfill:  ## fill missing Bronze hours from gtfsrt.io (make gapfill [FEED=vp] [DATE=D[:D]]; default all five kinds, 2026-08-15..yesterday)
	$(PY) -m raincheck.gapfill fill $(if $(FEED),--feed $(FEED)) $(if $(DATE),--date $(DATE))

gapcheck:  ## hour-completeness per kind x closed day -> check-result rows under <root>/checks/ (exit 1 on fillable gaps or a stale gapfill.DEAD entry; DEAD hours still missing are reported, not failed)
	$(PY) -m raincheck.gapfill check

gapverify:  ## sanity: filled hours vs adjacent archiver hours (rows, key coverage, schema); exit 2 INCONCLUSIVE when a kind has no pair to compare
	$(PY) -m raincheck.gapfill verify $(if $(FEED),--feed $(FEED))

# --- orchestration ticket 03: Bronze bus schema eras -------------------------------
.PHONY: eras
eras:  ## every verified Bronze bus reader still surfaces the era columns -> rows under <root>/checks/ (exit 1 a reader dropped one, 2 no mixed-era day to read)
	$(PY) -m raincheck.eras

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
.PHONY: vendor export web
MAPLIBRE := 5.9.0
# v6 is ESM-only (its package.json exports only `import` and dist/maplibre-gl.js 404s),
# so 5.9.0 is the UMD pin. Checksums pin the bytes, not just the version tag.
MAPLIBRE_JS_SHA := 2276259c7bd8ec632cc055115efdad53783b7da6e7104fad4c4837ea467d908d
MAPLIBRE_CSS_SHA := 43c1d886b5fdf0aac4e7135bd6f84b823d9f48283a648012665f9be52c01389f

# Download to .new, verify, and only then replace: writing straight to the final path would
# destroy the last known-good copy on the way to failing the checksum.
vendor:  ## fetch the pinned MapLibre UMD build into web/vendor (no CDN at demo time)
	@mkdir -p web/vendor
	curl -fsSL -o web/vendor/maplibre-gl.js.new https://unpkg.com/maplibre-gl@$(MAPLIBRE)/dist/maplibre-gl.js
	curl -fsSL -o web/vendor/maplibre-gl.css.new https://unpkg.com/maplibre-gl@$(MAPLIBRE)/dist/maplibre-gl.css
	@printf '%s  %s\n' "$(MAPLIBRE_JS_SHA)" web/vendor/maplibre-gl.js.new \
	                   "$(MAPLIBRE_CSS_SHA)" web/vendor/maplibre-gl.css.new | shasum -a 256 -c - \
	  || { rm -f web/vendor/maplibre-gl.js.new web/vendor/maplibre-gl.css.new; \
	       echo "vendor: checksum FAILED, previous copy left untouched"; exit 1; }
	@mv web/vendor/maplibre-gl.js.new web/vendor/maplibre-gl.js
	@mv web/vendor/maplibre-gl.css.new web/vendor/maplibre-gl.css
	@echo "vendor: maplibre-gl $(MAPLIBRE) verified"

export:  ## insight files from Gold -> web/files (make export [GATE=0.30] sweeps the interval gate)
	$(PY) -m raincheck.export $(if $(GATE),--gate $(GATE))

web:  ## serve web/ with the stdlib server (make web [PORT=8000]); nothing needs Range requests
	$(PY) -m http.server $(or $(PORT),8000) --directory web

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
publish:  ## publish one payload family to the public static host (make publish FAMILY=site|insight|live|docs|history [DRY=1])
	$(PY) -m raincheck.publish --family $(FAMILY) $(if $(DRY),--dry-run)
