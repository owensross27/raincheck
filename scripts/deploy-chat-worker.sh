#!/bin/sh
# Deploy the public "Ask the map" proxy: uploads deploy/cloudflare/chat-worker.js as
# Worker `raincheck-chat` with DEEPSEEK_API_KEY bound as a secret, routes it on
# rainchecknyc.com/api/chat*, and smoke-checks the live health probe.
#
# Needs in .env: CLOUDFLARE_API_TOKEN with "Account > Workers Scripts > Edit" AND
# "Zone > Workers Routes > Edit" (on rainchecknyc.com), plus DEEPSEEK_API_KEY.
# Idempotent: re-running re-uploads the script and leaves the existing route in place.
set -eu
cd "$(dirname "$0")/.."
set -a; . ./.env; set +a
: "${CLOUDFLARE_API_TOKEN:?add CLOUDFLARE_API_TOKEN to .env}"
: "${DEEPSEEK_API_KEY:?add DEEPSEEK_API_KEY to .env}"
ACC=3428af005305b65f4c49147db2eb8e63           # cloudflare account (holds the R2 buckets)
ZONE=2562e8f8beb3518884fce080f7f354e3          # rainchecknyc.com
API=https://api.cloudflare.com/client/v4
AUTH="Authorization: Bearer $CLOUDFLARE_API_TOKEN"

# metadata carries the secret as a binding, so upload and secret are ONE atomic call -
# a worker can never be live without its key. Written to a temp file so the key rides
# the multipart body, never a shell argument visible in ps.
META=$(mktemp)
trap 'rm -f "$META"' EXIT
cat > "$META" << EOF
{"main_module": "chat-worker.js", "compatibility_date": "2026-09-01",
 "bindings": [{"type": "secret_text", "name": "DEEPSEEK_API_KEY",
               "text": "$DEEPSEEK_API_KEY"}]}
EOF

echo "uploading worker raincheck-chat..."
curl -sf -X PUT "$API/accounts/$ACC/workers/scripts/raincheck-chat" \
  -H "$AUTH" \
  -F "metadata=@$META;type=application/json" \
  -F "chat-worker.js=@deploy/cloudflare/chat-worker.js;type=application/javascript+module" \
  | .venv/bin/python -c "import json,sys; d=json.load(sys.stdin); \
      print('upload ok' if d['success'] else d['errors']); exit(0 if d['success'] else 1)"

# the route, added once: list first so a re-deploy does not stack duplicates
if ! curl -sf -H "$AUTH" "$API/zones/$ZONE/workers/routes" \
    | grep -q '"pattern": *"rainchecknyc.com/api/chat\*"'; then
  echo "adding route rainchecknyc.com/api/chat* ..."
  curl -sf -X POST "$API/zones/$ZONE/workers/routes" -H "$AUTH" \
    -H "Content-Type: application/json" \
    -d '{"pattern": "rainchecknyc.com/api/chat*", "script": "raincheck-chat"}' \
    | .venv/bin/python -c "import json,sys; d=json.load(sys.stdin); \
        print('route ok' if d['success'] else d['errors']); exit(0 if d['success'] else 1)"
else
  echo "route already in place"
fi

echo "smoke: GET https://rainchecknyc.com/api/chat"
sleep 3
curl -s https://rainchecknyc.com/api/chat
echo
echo 'expect {"proxy": true, "key": true} - the page enables its launcher on next load'
