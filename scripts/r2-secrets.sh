#!/usr/bin/env bash
# Cloud ticket 07: create, rotate and verify the cluster's R2 token Secrets.
#
# One Secret per ServiceAccount, never shared, never in a manifest and never in an image:
#   build -> secret r2-build -> ServiceAccount raincheck-build (bucket raincheck-bronze)
#   serve -> secret r2-serve -> ServiceAccount raincheck-serve (the public bucket)
# The box's capture-write token is NOT here - it lives in .env on the box (ticket 18/19).
#
# Values are read from the environment and passed to kubectl through a 0600 temp file,
# never through argv: argv is visible to every user on the host via ps. Nothing here
# echoes a secret, and the apply output is a name, not a value.
#
#   scripts/r2-secrets.sh build            # create or rotate secret r2-build
#   scripts/r2-secrets.sh serve --check    # prove the token in the env can reach its bucket
#
# Env: RAINCHECK_R2_{BUILD,SERVE}_{KEY_ID,SECRET}, RAINCHECK_R2_{BUILD,SERVE}_BUCKET,
#      RAINCHECK_R2_ENDPOINT (defaults to RAINCHECK_COLD_ENDPOINT - one account, one
#      endpoint; only the token differs). Full rotation procedure:
#      .scratch/cloud/issues/07-secrets-iam-network.md
set -euo pipefail

NS=raincheck
ROLE="${1:-}"
MODE="${2:-apply}"
case "$ROLE" in
  build|serve) ;;
  *) echo "usage: r2-secrets.sh build|serve [--check]" >&2; exit 1 ;;
esac
[ "$MODE" = "--check" ] || [ "$MODE" = "apply" ] || { echo "second argument, if given, must be --check" >&2; exit 1; }

U=$(printf '%s' "$ROLE" | tr '[:lower:]' '[:upper:]')
KEY_VAR="RAINCHECK_R2_${U}_KEY_ID"
SEC_VAR="RAINCHECK_R2_${U}_SECRET"
BKT_VAR="RAINCHECK_R2_${U}_BUCKET"
: "${!KEY_VAR:?set $KEY_VAR (the R2 token Access Key ID)}"
: "${!SEC_VAR:?set $SEC_VAR (the R2 token Secret Access Key)}"
: "${!BKT_VAR:?set $BKT_VAR (the ONE bucket this token is scoped to)}"
ENDPOINT="${RAINCHECK_R2_ENDPOINT:-${RAINCHECK_COLD_ENDPOINT:?set RAINCHECK_R2_ENDPOINT or RAINCHECK_COLD_ENDPOINT}}"
BUCKET="${!BKT_VAR}"

if [ "$ROLE" = "serve" ] && [ "$BUCKET" = "raincheck-bronze" ]; then
  echo "refused: the serve token must never be scoped to raincheck-bronze - public and archive are different buckets (spec sec.9)" >&2
  exit 1
fi

if [ "$MODE" = "--check" ]; then
  # Proves the token reaches its bucket. Used in rotation BEFORE the old token is
  # deleted, so a bad paste is caught while there is still a working credential.
  if AWS_DEFAULT_REGION=auto AWS_ACCESS_KEY_ID="${!KEY_VAR}" AWS_SECRET_ACCESS_KEY="${!SEC_VAR}" \
     "${RAINCHECK_AWS:-aws}" s3 ls "s3://$BUCKET/" --endpoint-url "$ENDPOINT" >/dev/null 2>&1; then
    echo "r2-secrets: OK - the $ROLE token in the environment can list s3://$BUCKET/"
  else
    echo "r2-secrets: FAIL - the $ROLE token in the environment cannot list s3://$BUCKET/ (wrong token, wrong bucket, or the token lacks Object Read)" >&2
    exit 1
  fi
  exit 0
fi

umask 077
tmp=$(mktemp)
trap 'rm -f "$tmp"' EXIT INT TERM
# --from-env-file, not --from-literal: --from-literal puts the secret in argv.
{
  printf 'AWS_ACCESS_KEY_ID=%s\n' "${!KEY_VAR}"
  printf 'AWS_SECRET_ACCESS_KEY=%s\n' "${!SEC_VAR}"
  printf 'AWS_ENDPOINT_URL=%s\n' "$ENDPOINT"
  printf 'AWS_DEFAULT_REGION=auto\n'   # R2 rejects real AWS region names (ticket 18)
} > "$tmp"

kubectl create namespace "$NS" --dry-run=client -o yaml | kubectl apply -f - >/dev/null
kubectl -n "$NS" create secret generic "r2-$ROLE" --from-env-file="$tmp" \
  --dry-run=client -o yaml | kubectl apply -f - >/dev/null
kubectl -n "$NS" annotate secret "r2-$ROLE" --overwrite \
  "raincheck.io/r2-bucket=$BUCKET" "raincheck.io/serviceaccount=raincheck-$ROLE" >/dev/null

echo "r2-secrets: applied secret $NS/r2-$ROLE (bucket $BUCKET) for ServiceAccount raincheck-$ROLE"
echo "r2-secrets: restart the workloads using it - a running pod keeps the old env"
