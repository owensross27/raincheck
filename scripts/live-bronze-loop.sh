#!/bin/bash
# The 30 s live-fleet bridge, on the Mac, until the cluster can serve its own fleet.
#
# Chartered by Ross 2026-08-27 ("I want it to be always running, and then we'll just
# trigger it to be turned off in a week or something"): the stream's live/ tables are
# pod-local (live/-on-R2 is a still-open writer conversion), so the page's fleet rides
# bronze exports. This loop = one export tick + one publish, every INTERVAL seconds,
# run by the com.raincheck.live-bronze LaunchAgent (KeepAlive).
#
#   ON:   launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.raincheck.live-bronze.plist
#   OFF:  launchctl bootout   gui/$(id -u)/com.raincheck.live-bronze
#
# ponytail: two interpreter starts per tick (~4 s of the 30) - fold into one process
# only if this outlives its one-week charter. Serve creds come from .env (600,
# gitignored), never from arguments or this file.
set -u
cd "$(dirname "$0")/.." || exit 1
set -a; . ./.env; set +a
INTERVAL="${INTERVAL:-30}"

while :; do
  .venv/bin/python -m raincheck.live_export --source bronze --once >/dev/null 2>&1
  AWS_ACCESS_KEY_ID="$RAINCHECK_SERVE_KEY_ID" \
  AWS_SECRET_ACCESS_KEY="$RAINCHECK_SERVE_SECRET" \
  AWS_ENDPOINT_URL="$RAINCHECK_SERVE_ENDPOINT" \
  AWS_DEFAULT_REGION=auto \
    .venv/bin/python -m raincheck.publish --family live >/dev/null 2>&1
  sleep "$INTERVAL"
done
