#!/usr/bin/env bash
# Cloud ticket 03 / spec section 3: build and push THE image. One image for every raincheck
# pod - the per-day build pods, precip, streaming, the cluster-mode gold/backfill driver
# and the topics Job - because five specialised images would be five drifting runtimes.
#
# TAGGED BY GIT SHA, NEVER `:latest`. A moving tag makes "which code produced this
# partition?" unanswerable, and `imagePullPolicy: IfNotPresent` on a moving tag serves a
# stale image forever. The tag therefore has to MEAN the tree, so a dirty tree is refused
# rather than tagged with a sha it does not match (--dirty overrides, for a scratch push).
#
# It also writes the tag into deploy/k8s/kustomization.yaml's `images:` transformer, which
# is the ONE place any manifest names an image: the manifests say `image: raincheck` and
# kustomize rewrites all of them together. The manifest test then only has one thing to
# check, and a half-updated rollout is not expressible.
#
# arm64 only - the whole cluster is Graviton (spec section 1).
#
# TWO TAGS, ONE SHA, ONE REPOSITORY (orchestration ticket 04). `:<sha>` is the runtime
# every raincheck pod runs; `:<sha>-airflow` is the same tree's DAGs on the official Airflow
# base, which is how the DAG folder is delivered (no git-sync, no DAG volume). They are
# built and pushed together from one tree so that "the DAG and the code it schedules are
# the same version" is true by construction; the second one is pinned into
# deploy/airflow/values.yaml the way the first is pinned into the kustomize transformer,
# and tests/test_dag_delivery.py fails if the two pins stop naming one sha.
#
#   scripts/cloud-image.sh [--dirty] [--no-push]
# Exit: 0 pushed and pinned - 1 refused (dirty tree, or a tool/login failure)
# Env: optional RAINCHECK_AWS, RAINCHECK_DOCKER (stub hooks).
set -euo pipefail

# us-east-1 is the cluster's region and this Mac's default is us-east-2, so every call
# pins it: without --region a describe returns InvalidGroup.NotFound and reads exactly
# like a deleted resource (KNOWN TRAPS).
REGION=us-east-1
REPO_NAME=raincheck
PLATFORM=linux/arm64

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
AWS="${RAINCHECK_AWS:-aws}"
DOCKER="${RAINCHECK_DOCKER:-docker}"
DIRTY=0
PUSH=1
for a in "$@"; do
  case "$a" in
    --dirty)   DIRTY=1 ;;
    --no-push) PUSH=0 ;;
    *) echo "usage: $(basename "$0") [--dirty] [--no-push]" >&2; exit 1 ;;
  esac
done

SHA="$(git -C "$ROOT" rev-parse --short=12 HEAD)"
if [ -n "$(git -C "$ROOT" status --porcelain)" ] && [ "$DIRTY" -eq 0 ]; then
  echo "cloud-image: working tree is dirty - the tag would name a tree that is not what" >&2
  echo "             gets built. Commit first, or pass --dirty for a scratch push." >&2
  exit 1
fi
[ "$DIRTY" -eq 1 ] && SHA="$SHA-dirty"

ACCOUNT="$($AWS sts get-caller-identity --query Account --output text --region "$REGION")"
REGISTRY="$ACCOUNT.dkr.ecr.$REGION.amazonaws.com"
IMAGE="$REGISTRY/$REPO_NAME"
echo "cloud-image: $IMAGE:$SHA ($PLATFORM)"

# Idempotent: describe-repositories is the create guard, because `create` on an existing
# repo is an error and `|| true` around it would swallow a real failure too.
if ! $AWS ecr describe-repositories --repository-names "$REPO_NAME" --region "$REGION" >/dev/null 2>&1; then
  echo "cloud-image: creating ECR repository $REPO_NAME"
  $AWS ecr create-repository --repository-name "$REPO_NAME" --region "$REGION" \
    --image-tag-mutability IMMUTABLE \
    --tags Key=Project,Value=raincheck-cloud >/dev/null
fi

# --target is required now that the Dockerfile has two stages: without it docker builds the
# LAST one, and every raincheck pod would silently start running the Airflow base image.
$DOCKER build --platform "$PLATFORM" --target runtime -f "$ROOT/docker/Dockerfile" -t "$IMAGE:$SHA" "$ROOT"
# The DAG image carries the runtime tag it was built beside, as a build ARG: nothing renders
# kustomize inside an Airflow pod, so this is where the `image: raincheck` spelling in the
# placement table gets resolved. It is baked into the IMAGE rather than set on the Airflow
# Deployments because env on a Deployment does not reach task pods, and it is the WORKER
# that parses the DAG and builds the stage pod's spec.
$DOCKER build --platform "$PLATFORM" --target dags -f "$ROOT/docker/Dockerfile" \
  --build-arg "RAINCHECK_IMAGE=$IMAGE:$SHA" -t "$IMAGE:$SHA-airflow" "$ROOT"

if [ "$PUSH" -eq 1 ]; then
  $AWS ecr get-login-password --region "$REGION" | $DOCKER login --username AWS --password-stdin "$REGISTRY"
  $DOCKER push "$IMAGE:$SHA"
  $DOCKER push "$IMAGE:$SHA-airflow"
fi

# The one place a tag lives. sed over `kustomize edit set image` on purpose: kubectl's
# built-in kustomize has no `edit`, and adding the standalone binary as a build dependency
# for a two-line rewrite is not worth it.
KUST="$ROOT/deploy/k8s/kustomization.yaml"
python3 - "$KUST" "$IMAGE" "$SHA" <<'PY'
import re, sys
path, image, sha = sys.argv[1:]
text = open(path).read()
new = re.sub(r"(?m)^(\s+newName:\s).*$", rf"\g<1>{image}", text)
new = re.sub(r"(?m)^(\s+newTag:\s).*$", rf"\g<1>{sha}", new)
assert new != text or (image in text and sha in text), "kustomization.yaml has no images: block to pin"
open(path, "w").write(new)
PY
echo "cloud-image: pinned deploy/k8s/kustomization.yaml -> $IMAGE:$SHA"

# The Helm half. Helm values are not Kubernetes objects, so the kustomize transformer
# cannot reach them - `images.airflow` (scheduler, api-server, dag-processor) and
# `images.pod_template` (every task pod the executor stamps) are pinned here instead.
# Only the two repository/tag pairs INSIDE the images: block are rewritten; the file's
# other keys, its comments and its component blocks are left exactly as they are.
VALUES="$ROOT/deploy/airflow/values.yaml"
python3 - "$VALUES" "$IMAGE" "$SHA-airflow" <<'PIN'
import re, sys
path, image, tag = sys.argv[1:]
lines = open(path).read().splitlines(keepends=True)
start = next(i for i, l in enumerate(lines) if l.startswith("images:"))
end = next((i for i in range(start + 1, len(lines))
            if lines[i].strip() and not lines[i][0].isspace()), len(lines))
edits = 0
for i in range(start + 1, end):
    new = re.sub(r"^(\s+repository:\s).*$", rf"\g<1>{image}", lines[i].rstrip("\n"))
    new = re.sub(r"^(\s+tag:\s).*$", rf'\g<1>"{tag}"', new) + "\n"
    edits += new != lines[i]
    lines[i] = new
assert edits == 4, f"expected 4 image pins under images:, rewrote {edits}"
open(path, "w").writelines(lines)
PIN
echo "cloud-image: pinned deploy/airflow/values.yaml -> $IMAGE:$SHA-airflow"
echo "cloud-image: commit both pins - the manifests, the DAGs and the image are one change"
