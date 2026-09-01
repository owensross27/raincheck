#!/bin/sh
# Storm-triggered flood-record refresh (spec: the flood record freezes at flood_obs.ASOF;
# the daily 9 AM scheduled task advances it, and THIS watcher jumps the queue when the
# live MRMS table shows widespread heavy rain, so a storm evening surfaces on the map
# the same evening instead of next morning).
#
# Trigger: any hour in the trailing 4 with >= 2000 Cells at >= 10 mm/h, MEASURED on
# live/precip_cell 2026-09-01: the 2026-08-27 storm ran 2,004-12,180 such cells for six
# straight hours; the rest of the week never exceeded 1,440. Cooldown 3 h - the chain is
# idempotent, and a storm evening whose 311 reports have not crossed the p99 yet gets
# retried while the rain is still on the table.
#
# JUDGMENT STAYS OUT OF THIS SCRIPT. Every gate the refresh procedure defines - the
# source canary, the p99 pin re-freeze, a spine diff that removes events or shifts a
# boundary by more than a day - exits loudly here (set -e or the explicit exits below)
# and leaves the tree for the daily scheduled task (raincheck-flood-refresh) to resolve.
# FORCE=1 skips the rain predicate and cooldown, for exercising the chain by hand.
set -eu
cd "$(dirname "$0")/.."
PY=.venv/bin/python
STATE=data/checks/flood-trigger.last
COOLDOWN=10800
mkdir -p data/checks data/logs

if [ "${FORCE:-0}" != 1 ]; then
  hot=$($PY - <<'EOF'
import duckdb
n = duckdb.sql("""
  select coalesce(max(c), 0) from (
    select count(*) as c
    from read_parquet('data/live/precip_cell/valid_ts=*/part-*.parquet',
                      hive_partitioning=1, union_by_name=1)
    where cast(valid_ts as varchar) >= strftime(now() - interval 4 hour, '%Y-%m-%dT%H')
      and mm_1h >= 10
    group by valid_ts)
""").fetchone()[0]
print(int(n))
EOF
)
  [ "$hot" -ge 2000 ] || exit 0
  now=$(date -u +%s)
  last=$(cat "$STATE" 2>/dev/null || echo 0)
  [ $((now - last)) -ge $COOLDOWN ] || exit 0
  echo "$now" > "$STATE"
  echo "=== flood-rain-trigger $(date -u +%FT%TZ): $hot cells >= 10 mm/h - refreshing ==="
else
  echo "=== flood-rain-trigger $(date -u +%FT%TZ): FORCE=1 ==="
fi

$PY - <<'EOF'
import re
from datetime import date
p = "src/raincheck/flood_obs.py"
s = open(p).read()
t = date.today()
open(p, "w").write(re.sub(r"ASOF = date\(\d+, \d+, \d+\)",
                          f"ASOF = date({t.year}, {t.month}, {t.day})", s, count=1))
EOF

make flood-obs   # the canary: a renamed source literal fails here, loudly, unresolved
OLD=$(mktemp -t flood_events_old).parquet
cp data/silver/flood_events/part-00000.parquet "$OLD"
make flood-spine # the p99 gate: a pin move fails here; re-freezing is the 9 AM task's call

rc=0
OLD="$OLD" $PY - <<'EOF' || rc=$?
import duckdb, os, sys
q = "select event_id, day_start, day_end from read_parquet('%s')"
old = {r[0]: r[1:] for r in duckdb.sql(q % os.environ["OLD"]).fetchall()}
new = {r[0]: r[1:] for r in duckdb.sql(q % "data/silver/flood_events/*.parquet").fetchall()}
added = sorted(set(new) - set(old))
removed = sorted(set(old) - set(new))
shifted = [k for k in set(old) & set(new)
           if abs((new[k][0] - old[k][0]).days) > 1 or abs((new[k][1] - old[k][1]).days) > 1]
print(f"spine diff: added={added} removed={removed} shifted_gt_1d={shifted}")
if removed or shifted:
    sys.exit(f"GATE: removed={removed} shifted={shifted} - stopping for the daily task")
if not added:
    print("no new event yet (311 reports may still be accumulating) - stopping clean")
    sys.exit(3)
EOF
if [ $rc -eq 3 ]; then exit 0; fi
if [ $rc -ne 0 ]; then exit $rc; fi

make flood-labels
make export
make summary
$PY -m pytest tests/test_flood.py tests/test_summary.py tests/test_history.py tests/test_page.py -q

# explicit paths only - parallel sessions share this tree. flood_spine.py never changes
# on this path (a pin move already exited above).
git add src/raincheck/flood_obs.py
git commit -m "chore: storm-triggered flood-record refresh (ASOF $(date +%F))"
git push
make publish FAMILY=summary
make publish FAMILY=insight
make publish FAMILY=history
echo "=== flood-rain-trigger done $(date -u +%FT%TZ) ==="
