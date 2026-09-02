#!/bin/sh
# One flood-panel cycle with the serve credentials mapped from .env - the same
# RAINCHECK_SERVE_* -> AWS_* mapping live-bronze-loop.sh uses, plus the region R2
# demands (ambient ~/.aws/config region fails PutObject with InvalidRegionName).
# Run by launchd/com.raincheck.flood-panel.plist every 120 s: the laptop stand-in for
# cloud 05's 30 s loop, which is parked. flood_panel catches GateClosed itself, so the
# gated families (flood-mta, impact) report "designed" while the flood family publishes.
set -eu
cd "$(dirname "$0")/.."
set -a; . ./.env; set +a
AWS_ACCESS_KEY_ID="$RAINCHECK_SERVE_KEY_ID" \
AWS_SECRET_ACCESS_KEY="$RAINCHECK_SERVE_SECRET" \
AWS_ENDPOINT_URL="$RAINCHECK_SERVE_ENDPOINT" \
AWS_DEFAULT_REGION=auto \
  exec .venv/bin/python -m raincheck.flood_panel
