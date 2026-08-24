#!/bin/bash
# raincheck cloud T2 - point the capture box's archiver at the cluster broker.
#
# The path is private by construction: under the VPC CNI the broker's pod IP IS a VPC
# address, so the box talks to it directly - no external listener, no NodePort, no load
# balancer, no public bootstrap. What the box cannot do is resolve cluster DNS, so the
# broker's `box` listener advertises kafka0.raincheck.internal and the box resolves that
# name from its own /etc/hosts. Re-run this after the broker moves (spot reclaim, node
# roll): the pod IP changes, the NAME does not, so nothing on the box is reconfigured
# except one line of /etc/hosts - and the archiver is NOT restarted for that, because
# librdkafka re-resolves on reconnect and a restart is a capture gap.
#
#   scripts/cloud-kafka-endpoint.sh            # converge
#   scripts/cloud-kafka-endpoint.sh --status   # report only, change nothing
set -euo pipefail

BOX_HOST="${RAINCHECK_BOX_HOST:-44.218.135.197}"
BOX_USER="${RAINCHECK_BOX_USER:-ubuntu}"
KEY="${RAINCHECK_BOX_SSH_KEY:-$HOME/.ssh/lewis-signs-dev.pem}"
NAME=kafka0.raincheck.internal   # must equal the Kafka CR's advertisedHost for listener `box`
PORT=9094
ssh_box() { ssh -i "$KEY" -o BatchMode=yes -o ConnectTimeout=10 "$BOX_USER@$BOX_HOST" "$@"; }

ip=$(kubectl -n kafka get pod -l strimzi.io/kind=Kafka -o jsonpath='{.items[0].status.podIP}')
[ -n "$ip" ] || { echo "no broker pod: is the Kafka CR ready?" >&2; exit 1; }
echo "broker $NAME -> $ip:$PORT"

if [ "${1:-}" = "--status" ]; then
  ssh_box "grep -H '$NAME' /etc/hosts || echo 'no /etc/hosts entry'
           sudo grep -H '^RAINCHECK_KAFKA=' /etc/raincheck.env || echo 'RAINCHECK_KAFKA unset'
           systemctl is-active raincheck-archiver"
  exit 0
fi

# The remote half runs as root and reports what it changed. Only the env file needs a
# restart to take effect; /etc/hosts does not.
ssh_box "sudo bash -s '$ip' '$NAME' '$PORT'" <<'REMOTE'
set -euo pipefail
ip=$1; name=$2; port=$3
if ! grep -qE "^${ip}[[:space:]]+${name}\$" /etc/hosts; then
  sed -i "/[[:space:]]${name}\$/d" /etc/hosts
  printf '%s %s\n' "$ip" "$name" >> /etc/hosts
  echo "hosts: $name -> $ip"
fi
if ! grep -qx "RAINCHECK_KAFKA=${name}:${port}" /etc/raincheck.env; then
  sed -i '/^RAINCHECK_KAFKA=/d' /etc/raincheck.env
  printf 'RAINCHECK_KAFKA=%s:%s\n' "$name" "$port" >> /etc/raincheck.env
  systemctl restart raincheck-archiver
  echo "env: RAINCHECK_KAFKA=$name:$port (archiver restarted)"
fi
systemctl is-active --quiet raincheck-archiver || { echo "archiver NOT active" >&2; exit 1; }
REMOTE
echo "archiver active; producing to $NAME:$PORT"
