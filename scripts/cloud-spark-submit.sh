#!/usr/bin/env bash
# Cloud ticket 03 / spec section 3: cluster-mode submit, for the two GENUINELY WIDE jobs.
#
# Per-day work does NOT come through here. `events` is ~275 s per Service date and each
# date is independent, so one pod per day with Spark in-pod (deploy/k8s/raincheck/build.yaml)
# beats paying driver-plus-executor scheduling per day. What is wide is the `gold` monthly
# reduce over touched months and the T17 7-year backfill (2,278 files, not the nightly
# shape). No spark-operator: `--master k8s://` needs only the Role in build.yaml, which is
# what lets the driver create its own executors.
#
# The image comes from deploy/k8s/kustomization.yaml's `images:` pin, never from an
# argument: driver, executors and every pod in the cluster then run the one sha, and there
# is exactly one place to change it. Credentials are secretKeyRef into the r2-build Secret
# [cloud 07] - never argv, never a literal, and never baked into the image.
#
#   scripts/cloud-spark-submit.sh gold month 2026-08
#   scripts/cloud-spark-submit.sh --backfill nbp 2019-03-04     (gated - see below)
#
# MODULE is a real `raincheck.<module>`, checked against src/ before submitting, so a typo
# fails here rather than per-executor at import time. --backfill is a FLAG, not a module:
# T17 is 2,278 nycbuspositions days through `raincheck.nbp`, one submit per day, and there
# is no `raincheck.backfill` to name.
#
# THE BACKFILL IS GATED. It runs only after the events parity gate has passed on the
# cluster, checked here through scripts/cloud-parity-gate.sh --backfill-allowed rather
# than remembered: "the backfill is the first thing the cluster is trusted with, and not
# before it is trusted."
# Exit: 0 submitted - 1 refused / submit failed - 2 usage or missing pin.
set -euo pipefail

REGION=us-east-1
CLUSTER=raincheck
NAMESPACE=raincheck
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
KUBECTL="${RAINCHECK_KUBECTL:-kubectl}"
SUBMIT="${RAINCHECK_SPARK_SUBMIT:-$ROOT/.venv/bin/spark-submit}"

BACKFILL=0
if [ "${1:-}" = "--backfill" ]; then BACKFILL=1; shift; fi
[ $# -ge 1 ] || { echo "usage: $(basename "$0") [--backfill] MODULE ARGS..." >&2; exit 2; }
JOB="$1"; shift

[ -f "$ROOT/src/raincheck/$JOB.py" ] || {
  echo "cloud-spark-submit: no such module raincheck.$JOB" >&2; exit 2; }
if [ "$BACKFILL" -eq 1 ]; then
  "$ROOT/scripts/cloud-parity-gate.sh" --backfill-allowed || exit 1
fi

# One source for the image: the kustomize pin. A PLACEHOLDER tag means nobody has pushed
# yet, and submitting that would fail per-executor at pull time instead of here.
IMAGE="$(python3 - "$ROOT/deploy/k8s/kustomization.yaml" <<'PY'
import re, sys
text = open(sys.argv[1]).read()
name = re.search(r"(?m)^\s+newName:\s*(\S+)", text)
tag = re.search(r"(?m)^\s+newTag:\s*(\S+)", text)
print(f"{name.group(1)}:{tag.group(1)}" if name and tag else "")
PY
)"
case "$IMAGE" in
  ""|*PLACEHOLDER*) echo "cloud-spark-submit: no image pinned in deploy/k8s/kustomization.yaml -" >&2
                    echo "                    run scripts/cloud-image.sh first." >&2; exit 2 ;;
esac

API="$($KUBECTL config view --minify -o jsonpath='{.clusters[0].cluster.server}')"
echo "cloud-spark-submit: raincheck.$JOB $* -> k8s://$API as $IMAGE"

# The four R2 keys, by reference. secretKeyRef is the only form here: envFrom has no
# spark-submit equivalent, and a literal would put the token in the driver's pod spec.
SECRET_CONF=()
for key in AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_ENDPOINT_URL AWS_DEFAULT_REGION; do
  for side in driver executor; do
    SECRET_CONF+=(--conf "spark.kubernetes.${side}.secretKeyRef.${key}=r2-build:${key}")
  done
done

exec "$SUBMIT" \
  --master "k8s://$API" \
  --deploy-mode cluster \
  --name "raincheck-$JOB" \
  --conf "spark.kubernetes.container.image=$IMAGE" \
  --conf "spark.kubernetes.container.image.pullPolicy=IfNotPresent" \
  --conf "spark.kubernetes.namespace=$NAMESPACE" \
  --conf "spark.kubernetes.authenticate.driver.serviceAccountName=raincheck-build" \
  --conf "spark.kubernetes.driver.node.selector.raincheck\.io/pool=burst" \
  --conf "spark.kubernetes.executor.node.selector.raincheck\.io/pool=burst" \
  --conf "spark.executor.instances=4" \
  --conf "spark.executor.memory=3g" \
  --conf "spark.driver.memory=2g" \
  "${SECRET_CONF[@]}" \
  "local:///opt/raincheck/src/raincheck/$JOB.py" "$@"
