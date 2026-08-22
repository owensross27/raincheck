# raincheck (spec A). Every target runs from the repo venv on the brew JDK 17. JAVA_HOME and
# TZ=UTC come from here or .env, never `brew link` (flip JAVA_HOME in .env for the openjdk@11
# fallback). RAINCHECK_ARCHIVE_ROOT (data root, default data/) and RAINCHECK_BRONZE_GB (absolute
# byte budget over <root>/archive) pass through from the shell or .env; empty means default.
-include .env
export JAVA_HOME ?= /opt/homebrew/opt/openjdk@17
export TZ := UTC
export RAINCHECK_ARCHIVE_ROOT RAINCHECK_BRONZE_GB
PY := .venv/bin/python

.PHONY: warm ref nbp precip-hourly precip-cell schedule events gold baseline gates slice test

warm:  ## start one session through the factory: warms the Ivy cache once (~240 MB), proves the stack
	$(PY) -c "from raincheck.spark import session; s = session(); print('spark', s.version); s.stop()"

ref:  ## build every ref/ lookup table (ticket 02)
	$(PY) -m raincheck.ref

nbp:  ## convert one nycbuspositions UTC day to Bronze VP (make nbp DATE=YYYY-MM-DD)
	$(PY) -m raincheck.nbp $(DATE)

precip-hourly:  ## Pixel-grain precip for one month (make precip-hourly SRC=aorc MONTH=YYYY-MM)
	$(PY) -m raincheck.precip hourly $(SRC) $(MONTH)

precip-cell:  ## Cell-grain precip for one month (make precip-cell SRC=aorc MONTH=YYYY-MM)
	$(PY) -m raincheck.precip cell $(SRC) $(MONTH)

schedule:  ## load one registered Pick's schedule tables (make schedule PICK=<pick_id sha1>)
	$(PY) -m raincheck.schedule $(PICK)

events:  ## Legs (R2) -> silver/leg_hours and Passages/Delay -> silver/events for one service day (make events DATE=YYYY-MM-DD)
	$(PY) -m raincheck.events $(DATE)

gold:  ## roll leg_hours into gold/cell_hour_speed for one month (make gold MONTH=YYYY-MM)
	$(PY) -m raincheck.gold speed $(MONTH)

baseline:  ## dry hour-of-week Speed baseline for one window (make baseline WINDOW=w1|w2)
	$(PY) -m raincheck.gold baseline $(WINDOW)

gates:  ## tier-2 slice acceptance gates: 10-T3, 10-T6 wired; T4/T5 report-only slots
	$(PY) -m raincheck.gates

slice:  ## the whole two-window slice: convert 124 files (T1 each), events x122, gold, baselines, gates
	$(PY) -m raincheck.slice

test:
	$(PY) -m pytest -q
