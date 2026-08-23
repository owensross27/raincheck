# raincheck (spec A). Every target runs from the repo venv on the brew JDK 17. JAVA_HOME and
# TZ=UTC come from here or .env, never `brew link` (flip JAVA_HOME in .env for the openjdk@11
# fallback). RAINCHECK_ARCHIVE_ROOT (data root, default data/) and RAINCHECK_BRONZE_GB (absolute
# byte budget over <root>/archive) pass through from the shell or .env; empty means default.
-include .env
export JAVA_HOME ?= /opt/homebrew/opt/openjdk@17
export TZ := UTC
export RAINCHECK_ARCHIVE_ROOT RAINCHECK_BRONZE_GB TRANSITLAND_API_KEY
PY := .venv/bin/python

.PHONY: warm ref nbp features picks precip-hourly precip-cell schedule events gold baseline gates slice test topics

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

coldcheck:  ## loud gap check: every local Bronze file present remotely with matching size
	@$(COLD_READY)
	@out=$$($(COLD) sync "$${RAINCHECK_ARCHIVE_ROOT:-data}/archive" "s3://$(RAINCHECK_COLD_BUCKET)/archive" --size-only --dryrun); \
	if [ -n "$$out" ]; then printf '%s\n' "$$out"; echo "coldcheck: GAP - files above are missing or size-mismatched remotely"; exit 1; \
	else echo "coldcheck: OK - local Bronze fully present remotely"; fi

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

gapcheck:  ## hour-completeness per kind x closed day (exit 1 on fillable gaps; gapfill.DEAD hours are reported, not failed)
	$(PY) -m raincheck.gapfill check

gapverify:  ## sanity: filled hours vs adjacent archiver hours (rows, key coverage, schema)
	$(PY) -m raincheck.gapfill verify $(if $(FEED),--feed $(FEED))

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
