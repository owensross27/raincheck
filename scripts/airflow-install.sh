#!/bin/bash
# raincheck cloud T6 - stand up (or re-converge) the Airflow platform on the EKS cluster.
#
# PLATFORM ONLY. No DAG is delivered here; DAG structure and delivery belong to the
# orchestration effort. What this creates:
#   1. Four Secrets, once, if they do not already exist: the metadata DB password + its
#      SQLAlchemy URI, and the three Airflow signing keys. Generated here rather than by
#      the chart so a `helm upgrade` cannot rotate them under a running task.
#   2. The metadata Postgres StatefulSet (gp3 in us-east-1f, floor NodePool).
#   3. The official Airflow chart, KubernetesExecutor, from deploy/airflow/values.yaml.
#
# EVERY STEP IS IDEMPOTENT and re-running the whole script is the repair procedure -
# unlike scripts/cloud-kafka-install.sh, nothing here drops data. The Secrets are created
# only when absent, `kubectl apply` converges, and `helm upgrade --install` converges.
#
# Secrets are written with --from-file, never --from-literal: a literal would put the
# generated password into argv, where every user on the host can read it with `ps`.
set -euo pipefail

CHART_VERSION="${AIRFLOW_CHART_VERSION:-1.22.0}"
NAMESPACE="${AIRFLOW_NAMESPACE:-raincheck}"
RELEASE=airflow
ROOT=$(cd "$(dirname "$0")/.." && pwd)

# One place that knows how to make a Secret from generated material without ever putting
# it on a command line or on the terminal. $2.. are "key=value" pairs; the value goes to a
# file in a 0700 tmpdir that is removed on exit.
TMP=$(mktemp -d)
chmod 700 "$TMP"
trap 'rm -rf "$TMP"' EXIT
secret_once() {
  local name=$1; shift
  if kubectl get secret "$name" -n "$NAMESPACE" >/dev/null 2>&1; then
    echo "   $name already exists - left alone (rotating it would invalidate what uses it)"
    return 0
  fi
  local args=()
  for pair in "$@"; do
    local key=${pair%%=*}
    printf '%s' "${pair#*=}" > "$TMP/$key"
    args+=(--from-file="$key=$TMP/$key")
  done
  kubectl create secret generic "$name" -n "$NAMESPACE" "${args[@]}"
}

echo "== 0. preflight"
kubectl get namespace "$NAMESPACE" >/dev/null || {
  # Deliberately NOT the whole kustomize render: that also carries the Kafka topics Job,
  # and re-applying that is not a safe repair (see scripts/cloud-kafka-install.sh step 4).
  echo "namespace $NAMESPACE and its ServiceAccounts are cloud 07's, and are not applied yet:" >&2
  echo "  kubectl apply -f $ROOT/deploy/k8s/serviceaccounts.yaml" >&2
  exit 1
}
if ! kubectl get secret r2-build -n "$NAMESPACE" >/dev/null 2>&1; then
  cat >&2 <<'EOS'
   NOTE: Secret r2-build does not exist, so REMOTE LOGGING WILL BE DARK. Airflow still
   starts (the envFrom is marked optional on purpose) and tasks still succeed - the
   amazon provider's log upload fails soft - but task logs die with their pod instead of
   landing in R2. Minting the token is a Cloudflare dashboard step; the procedure is in
   .scratch/cloud/issues/07-secrets-iam-network.md. Afterwards:
       kubectl rollout restart -n raincheck deploy/airflow-scheduler deploy/airflow-api-server deploy/airflow-dag-processor
EOS
fi

echo "== 1. secrets (created once, never rotated by a re-run)"
# Alphanumeric only: the DB password is also embedded in the SQLAlchemy URI below, where
# + and / would have to be percent-encoded.
#
# `cut`, not `head -c`, and openssl rather than a raw read of /dev/urandom. Under
# `set -o pipefail` a `head -c N` closes the pipe the moment it has N bytes, the upstream
# reader of /dev/urandom takes SIGPIPE, and the whole script dies with 141 having printed
# nothing. cut reads its input to EOF, so there is no pipe to break.
alnum() { openssl rand -base64 "$2" | tr -dc 'A-Za-z0-9' | cut -c"1-$1"; }
PGPASS=$(alnum 32 96)
secret_once airflow-metadata-db \
  "postgres-password=$PGPASS" \
  "connection=postgresql://airflow:$PGPASS@airflow-metadata-db.$NAMESPACE.svc:5432/airflow"
unset PGPASS
secret_once airflow-jwt        "jwt-secret=$(alnum 128 256)"
secret_once airflow-api-secret "api-secret-key=$(alnum 32 96)"
# Fernet needs a 32-byte urlsafe-base64 key, not free-form text: Airflow feeds it straight
# to cryptography.fernet.Fernet, which rejects anything else.
secret_once airflow-fernet     "fernet-key=$(openssl rand -base64 32 | tr '+/' '-_')"

echo "== 2. metadata Postgres (gp3-1f, floor)"
# Applied as the plain file, not through the kustomize render: the render also contains
# the Kafka objects, and an Airflow installer has no business re-applying the topics Job.
# The file and its rendered form are identical - the kustomization's only transformer is
# cloud 03's `images:`, which rewrites the image named `raincheck` and therefore never
# touches this StatefulSet's `postgres:17.6-alpine`. If a transformer is ever added that
# DOES rewrite this file (a namespace or a name prefix), this line has to become a
# rendered-and-filtered apply. tests/test_cluster_manifests.py asserts the file is in the
# render either way.
kubectl apply -f "$ROOT/deploy/k8s/airflow/postgres.yaml"
kubectl rollout status statefulset/airflow-metadata-db -n "$NAMESPACE" --timeout=5m

echo "== 3. Airflow $CHART_VERSION, KubernetesExecutor"
helm repo add apache-airflow https://airflow.apache.org >/dev/null 2>&1 || true
helm repo update apache-airflow >/dev/null
# NO --wait, and that is not an oversight. `airflow-run-airflow-migrations` is a
# post-install/post-upgrade HOOK, and helm's order with --wait is: create resources ->
# wait for them to be Ready -> run post-install hooks. Every Airflow Deployment has a
# `wait-for-airflow-migrations` init container, so --wait deadlocks: helm waits for pods
# that are waiting for a Job helm has not started yet, and the install dies 15 minutes
# later on "Progress deadline exceeded" (measured 2026-08-24). Without --wait the hook
# runs immediately - helm always waits for HOOKS - and the readiness wait is the explicit
# rollout status below, which fails loudly and names the deployment that did not come up.
helm upgrade --install "$RELEASE" apache-airflow/airflow \
  --version "$CHART_VERSION" --namespace "$NAMESPACE" \
  -f "$ROOT/deploy/airflow/values.yaml" \
  --timeout 15m
for d in airflow-scheduler airflow-api-server airflow-dag-processor; do
  kubectl rollout status "deploy/$d" -n "$NAMESPACE" --timeout=10m
done

cat <<EOS

Airflow is up in ns $NAMESPACE. There is no Ingress and no LoadBalancer, by design:

  kubectl port-forward -n $NAMESPACE svc/airflow-api-server 8080:8080

The UI user is 'admin'. SimpleAuthManager generates its password at api-server start and
logs it, so the credential lives behind cluster access and nowhere in this repo:

  kubectl logs -n $NAMESPACE deploy/airflow-api-server | grep "Password for user"

EOS
