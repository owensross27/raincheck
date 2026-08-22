# raincheck (spec A). Every target runs from the repo venv on the brew JDK 17. JAVA_HOME and
# TZ=UTC come from here or .env, never `brew link` (flip JAVA_HOME in .env for the openjdk@11
# fallback). RAINCHECK_ARCHIVE_ROOT (data root, default data/) and RAINCHECK_BRONZE_GB (absolute
# byte budget over <root>/archive) pass through from the shell or .env; empty means default.
-include .env
export JAVA_HOME ?= /opt/homebrew/opt/openjdk@17
export TZ := UTC
export RAINCHECK_ARCHIVE_ROOT RAINCHECK_BRONZE_GB
PY := .venv/bin/python

.PHONY: warm ref test

warm:  ## start one session through the factory: warms the Ivy cache once (~240 MB), proves the stack
	$(PY) -c "from raincheck.spark import session; s = session(); print('spark', s.version); s.stop()"

ref:  ## build every ref/ lookup table (ticket 02)
	$(PY) -m raincheck.ref

test:
	$(PY) -m pytest -q
