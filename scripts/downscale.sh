#!/usr/bin/env bash
# Cloud ticket 08 / spec section 8: the downscale path, as a script rather than a
# paragraph. Two plain EC2 instances replace the cluster -- an always-on t4g.large-class
# box for capture/stream/live plus a scheduled build box for the per-day work -- keeping
# the same freshness and losing only per-day parallelism. Reversibility is design, not
# admission, so this is exercisable on demand, not described.
#
#   scripts/downscale.sh plan            arithmetic + stage list; touches no AWS, costs $0
#   scripts/downscale.sh up              launch both instances   (SPENDS MONEY)
#   scripts/downscale.sh run [floor|build]   ship this checkout and run its stages
#   scripts/downscale.sh down            terminate both          (run this)
#
# `up` refuses without RAINCHECK_DOWNSCALE_OK=1: the exercise is Ross's call, not the
# script's. Nothing here copies .env -- every exercised stage reads public sources only
# (NOAA AORC, NYC open data), so no repo credential ever lands on a throwaway box.
# Env: RAINCHECK_AWS (stub hook), RAINCHECK_DOWNSCALE_KEY (default ~/.ssh/lewis-signs-dev.pem).
set -euo pipefail

REGION=us-east-1
SUBNET=subnet-002ac7537c7b84cdb          # us-east-1f, the capture box's subnet (ticket 01)
SG=sg-0cb33dca0ac107599                  # ssh from three /32s, 443 open; no new SG needed
KEYNAME=lewis-signs-dev
AMI_PARAM=/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-arm64
TAG=raincheck-downscale                  # Project= stays raincheck-cloud so the $200 budget sees it
FLOOR_TYPE=t4g.large                     # 2 vCPU / 8 GiB, on-demand: always-on cannot be interruptible
BUILD_TYPE=c7g.xlarge                    # 4 vCPU / 8 GiB spot; stateless, so a reclaim is a retry

# Measured us-east-1f 2026-08-24: t4g.large on-demand 0.0672, t4g.large spot 0.0234,
# c7g.xlarge spot 0.0525, public IPv4 0.005/hr, gp3 0.08/GiB-mo.
FLOOR_OD=0.0672; FLOOR_SPOT=0.0234; BUILD_SPOT=0.0525; EIP=0.005

# Every stage runs as `make <target>` -- that IS the constraint this path depends on.
# These four need no credential and no cluster: warm proves the JVM fits 2 vCPU / 8 GiB,
# ref and flood-obs are real Spark writes, precip-hourly is the heaviest regular stage.
# One `make` invocation per line; the first word is the target.
FLOOR_STAGES='warm
ref
flood-obs'
# The build box is disposable, so it starts with an EMPTY data root -- and precip-hourly
# reads ref/cell_pixel to build its AORC footprint. On the real path the box attaches the
# floor's volume (or syncs the ref/ tables from R2) before this runs; rebuilding ref here
# is not the answer, since ref itself needs silver/stops from the grant-blocked `picks`.
# Measured 2026-08-24: without that data root this stage fails on the prerequisite, not
# on capacity. Attaching shared state to the build box is the one piece of the path this
# exercise did not reproduce.
BUILD_STAGES='precip-hourly SRC=aorc MONTH=2026-07'


AWS="${RAINCHECK_AWS:-aws}"
KEY="${RAINCHECK_DOWNSCALE_KEY:-$HOME/.ssh/lewis-signs-dev.pem}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

ec2() { "$AWS" ec2 "$@" --region "$REGION"; }

name_of() { echo "$TAG-$1"; }

ip_of() {  # public IP of the running instance with this Name tag, empty if none
  ec2 describe-instances --filters "Name=tag:Name,Values=$(name_of "$1")" \
      "Name=instance-state-name,Values=pending,running" \
      --query 'Reservations[].Instances[0].PublicIpAddress' --output text | tr -d '\t\n' | sed 's/None//'
}

plan() {
  awk -v fo="$FLOOR_OD" -v fs="$FLOOR_SPOT" -v bs="$BUILD_SPOT" -v e="$EIP" \
      -v ft="$FLOOR_TYPE" -v bt="$BUILD_TYPE" 'BEGIN {
    H = 730; BH = 30                      # always-on hours/mo; build box ~1 h/day
    floor_od = fo*H; floor_sp = fs*H; ip1 = e*H
    build = bs*BH; ip2 = e*BH
    ebs = 4.00; ebs_b = 0.07; r2 = 0.47   # 50 GiB gp3 floor; 20 GiB build, only while alive
    od = floor_od + ip1 + ebs + build + ip2 + ebs_b + r2
    sp = floor_sp + ip1 + ebs + build + ip2 + ebs_b + r2
    printf "downscale path: %s always-on + %s scheduled build box\n\n", ft, bt
    printf "| line | on-demand floor | spot floor |\n|---|---|---|\n"
    printf "| floor %s 730 h | %.2f | %.2f |\n", ft, floor_od, floor_sp
    printf "| floor public IPv4 | %.2f | %.2f |\n", ip1, ip1
    printf "| floor gp3 50 GiB | %.2f | %.2f |\n", ebs, ebs
    printf "| build %s spot, 30 h | %.2f | %.2f |\n", bt, build, build
    printf "| build IPv4 + root gp3 | %.2f | %.2f |\n", ip2+ebs_b, ip2+ebs_b
    printf "| R2 | %.2f | %.2f |\n", r2, r2
    printf "| **total** | **%.2f** | **%.2f** |\n\n", od, sp
    printf "The map'\''s $25-60/mo range is not fuzz: it is this column choice.\n"
    printf "Against the measured cluster at $121.50/mo that saves $%.2f or $%.2f a month;\n", 121.50-od, 121.50-sp
    printf "the $73.00 EKS control plane is what disappears.\n\n"
    printf "Exercise burn: %.4f/hr (%s on-demand + %s spot + 2 public IPv4 + gp3).\n", \
           fo+bs+2*e+0.0044, ft, bt
    printf "A 3-hour exercise is about $%.2f.\n", 3*(fo+bs+2*e+0.0044)
  }'
  echo
  printf '%s\n' "$FLOOR_STAGES" | sed 's/^/floor stage: make /'
  printf '%s\n' "$BUILD_STAGES" | sed 's/^/build stage: make /' 
}

up() {
  [ "${RAINCHECK_DOWNSCALE_OK:-}" = 1 ] || {
    echo "downscale: up spends money and needs Ross's ok. Read \`downscale.sh plan\`," >&2
    echo "  then re-run with RAINCHECK_DOWNSCALE_OK=1. Nothing was launched." >&2
    exit 1; }
  ami=$("$AWS" ssm get-parameters --names "$AMI_PARAM" --region "$REGION" \
          --query 'Parameters[0].Value' --output text)
  echo "downscale: AL2023 arm64 $ami"
  tags() { echo "ResourceType=instance,Tags=[{Key=Name,Value=$(name_of "$1")},{Key=Project,Value=raincheck-cloud}]"; }
  ec2 run-instances --image-id "$ami" --instance-type "$FLOOR_TYPE" --count 1 \
      --key-name "$KEYNAME" --subnet-id "$SUBNET" --security-group-ids "$SG" \
      --associate-public-ip-address \
      --block-device-mappings 'DeviceName=/dev/xvda,Ebs={VolumeSize=50,VolumeType=gp3,DeleteOnTermination=true}' \
      --tag-specifications "$(tags floor)" --query 'Instances[0].InstanceId' --output text
  ec2 run-instances --image-id "$ami" --instance-type "$BUILD_TYPE" --count 1 \
      --key-name "$KEYNAME" --subnet-id "$SUBNET" --security-group-ids "$SG" \
      --associate-public-ip-address \
      --instance-market-options 'MarketType=spot' \
      --block-device-mappings 'DeviceName=/dev/xvda,Ebs={VolumeSize=20,VolumeType=gp3,DeleteOnTermination=true}' \
      --tag-specifications "$(tags build)" --query 'Instances[0].InstanceId' --output text
  echo "downscale: both launched. \`downscale.sh run\` when they are reachable, then ALWAYS \`down\`."
}

# The box runs THE image (cloud 03), not a venv it builds itself. This closes the
# deviation this script shipped with: the old bootstrap dnf-installed a toolchain and
# `pip install -e .`d the repo on EVERY exercise -- the same per-run setup cost the
# cluster rule bans -- and then re-resolved the Sedona jars from Maven on top. One
# `docker pull` of a sha-tagged image replaces both, and it is the SAME artefact the
# cluster runs, so the escape hatch stops being a second runtime that can drift.
#
# Still no repo credential on a throwaway box: the only secret that crosses is a 12 h ECR
# registry token, minted on the Mac and piped to `docker login --password-stdin` so it
# never reaches argv or the box's shell history.
bootstrap() {
  cat <<'BOOT'
set -eux
sudo dnf -y install docker
sudo systemctl enable --now docker
mkdir -p ~/raincheck/data
BOOT
}

# The image the cluster runs, read from the one pin. Empty when nobody has pushed yet.
pinned_image() {
  python3 - "$ROOT/deploy/k8s/kustomization.yaml" <<'PIN'
import re, sys
text = open(sys.argv[1]).read()
name = re.search(r"(?m)^\s+newName:\s*(\S+)", text)
tag = re.search(r"(?m)^\s+newTag:\s*(\S+)", text)
ok = name and tag and "PLACEHOLDER" not in tag.group(1)
print(f"{name.group(1)}:{tag.group(1)}" if ok else "")
PIN
}

run() {
  which="${1:-floor}"
  case "$which" in floor) stages="$FLOOR_STAGES" ;; build) stages="$BUILD_STAGES" ;;
                   *) echo "downscale: run floor|build" >&2; exit 2 ;; esac
  ip=$(ip_of "$which")
  [ -n "$ip" ] || { echo "downscale: no running $which instance -- \`up\` first" >&2; exit 2; }
  ssh_() { ssh -i "$KEY" -o StrictHostKeyChecking=accept-new "ec2-user@$ip" "$@"; }
  echo "downscale: $which at $ip"
  image="$(pinned_image)"
  [ -n "$image" ] || { echo "downscale: no image pinned in deploy/k8s/kustomization.yaml --" >&2
                       echo "  run scripts/cloud-image.sh first; the box runs that image." >&2; exit 2; }
  echo "downscale: image $image"
  bootstrap | ssh_ 'bash -s'
  registry="${image%%/*}"
  "$AWS" ecr get-login-password --region "$REGION" \
    | ssh_ "sudo docker login --username AWS --password-stdin $registry"
  ssh_ "sudo docker pull $image"
  # one `make <target>` per stage, timed: the freshness claim is measured, not asserted.
  # `make` inside the image is the same make the cluster and the Mac run -- that IS the
  # constraint this path depends on, and running it any other way would stop proving it.
  # stages travel as an env var, not on stdin: stdin is the script itself here, and a
  # heredoc would silently replace the piped list with nothing to read.
  ssh_ "IMAGE=$image STAGES='$stages' bash -s" <<'STAGES'
printf '%s\n' "$STAGES" | while read -r stage; do
  [ -n "$stage" ] || continue
  s=$(date +%s)
  if sudo docker run --rm -v "$HOME/raincheck/data:/data" -e RAINCHECK_ARCHIVE_ROOT=/data \
       "$IMAGE" make -C /opt/raincheck $stage
  then echo "downscale-stage ${stage%% *} OK $(( $(date +%s) - s ))s"
  else echo "downscale-stage ${stage%% *} FAILED"; fi
done
STAGES
}

down() {
  ids=$(ec2 describe-instances --filters "Name=tag:Name,Values=$TAG-*" \
          "Name=instance-state-name,Values=pending,running,stopped" \
          --query 'Reservations[].Instances[].InstanceId' --output text)
  [ -n "$ids" ] && [ "$ids" != "None" ] || { echo "downscale: nothing to terminate"; return 0; }
  # shellcheck disable=SC2086
  ec2 terminate-instances --instance-ids $ids --query 'TerminatingInstances[].InstanceId' --output text
  echo "downscale: terminated"
}

case "${1:-plan}" in
  plan) plan ;;
  up)   up ;;
  run)  run "${2:-floor}" ;;
  down) down ;;
  *) echo "usage: $(basename "$0") plan|up|run [floor|build]|down" >&2; exit 2 ;;
esac
