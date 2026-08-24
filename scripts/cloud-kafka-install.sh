#!/bin/bash
# raincheck cloud T2 - stand up (or re-converge) Kafka on the EKS cluster.
#
# Steps 1-3 are idempotent (upgrade/apply/duplicate-tolerant), so re-running them is the
# repair procedure. Step 4 is NOT: `make topics` deletes and recreates the topics, dropping
# whatever they still hold. Bronze is the record, so nothing durable is lost - but do not
# re-run this on a whim while the streaming job is mid-window. What it does, in order:
#   1. Strimzi cluster operator (pinned chart version), floor-pinned, watching ns kafka.
#   2. ONE security-group rule: the capture box -> the broker's box listener (9094).
#      That is the only inbound addition to the cluster's SGs this ticket is allowed.
#   3. The manifests, rendered from deploy/k8s (Kafka CR, gp3-1f StorageClass, topics Job).
#   4. `make topics` as a Job, re-run from scratch, against the cluster broker.
#
# The AWS CLI default profile on the Mac points at us-east-2. Every call here forces
# us-east-1 - the cluster, the box and the VPC are all there.
set -euo pipefail

STRIMZI_VERSION="${STRIMZI_VERSION:-1.2.0}"
REGION=us-east-1
# The capture box's OWN security group, created for this rule. NOT sg-0cb33dca0ac107599
# ("lewis-signs-dev-sg"): that group is shared with an unrelated staging instance
# (i-0a924268a565ad38a) and itself allows 0.0.0.0/0 on tcp/443, so sourcing the broker
# rule from it would hand Kafka to staging too (measured by cloud 07, 2026-08-24).
BOX_SG=$(aws ec2 describe-security-groups --region "$REGION" \
  --filters Name=group-name,Values=raincheck-capture-box Name=vpc-id,Values=vpc-049a68bf6017d6ead \
  --query 'SecurityGroups[0].GroupId' --output text)
if [ "$BOX_SG" = "None" ] || [ -z "$BOX_SG" ]; then
  cat >&2 <<'EOS'
no raincheck-capture-box security group. It is created and attached ONCE, by hand,
because it changes the capture box's networking - list every existing group in the
modify call or the box loses what it has:

  aws ec2 create-security-group --region us-east-1 --group-name raincheck-capture-box \
    --description "raincheck capture box: source group for the private path to Kafka" \
    --vpc-id vpc-049a68bf6017d6ead \
    --tag-specifications 'ResourceType=security-group,Tags=[{Key=Project,Value=raincheck-cloud}]'
  aws ec2 modify-network-interface-attribute --region us-east-1 \
    --network-interface-id eni-098f5f2acbc73fe7d --groups sg-0cb33dca0ac107599 <new-sg-id>
EOS
  exit 1
fi
CLUSTER_SG=$(aws ec2 describe-security-groups --region "$REGION" \
  --filters Name=tag:aws:eks:cluster-name,Values=raincheck Name=group-name,Values='eks-cluster-sg-*' \
  --query 'SecurityGroups[0].GroupId' --output text)
BOX_PORT=9094                            # the `box` listener; 9092 never leaves the cluster
ROOT=$(cd "$(dirname "$0")/.." && pwd)
render() { kubectl kustomize --load-restrictor LoadRestrictionsNone "$ROOT/deploy/k8s"; }

echo "== 1. Strimzi $STRIMZI_VERSION (KRaft-only since 1.0) into ns kafka"
helm repo add strimzi https://strimzi.io/charts/ >/dev/null 2>&1 || true
helm upgrade --install strimzi-kafka-operator strimzi/strimzi-kafka-operator \
  --version "$STRIMZI_VERSION" --namespace kafka --create-namespace \
  --set 'nodeSelector.raincheck\.io/pool=floor' \
  --set 'resources.requests.cpu=100m' --set 'resources.requests.memory=256Mi' \
  --wait --timeout 5m

echo "== 2. SG rule: $BOX_SG -> $CLUSTER_SG tcp/$BOX_PORT (private, in-VPC, same AZ)"
# EC2 rejects '>' in a rule description, and a swallowed error here is a silent
# no-broker-for-the-box: tolerate ONLY the duplicate, re-raise anything else.
err=$(aws ec2 authorize-security-group-ingress --region "$REGION" --group-id "$CLUSTER_SG" \
  --ip-permissions "IpProtocol=tcp,FromPort=$BOX_PORT,ToPort=$BOX_PORT,UserIdGroupPairs=[{GroupId=$BOX_SG,Description='raincheck capture box to Kafka box listener (T2)'}]" \
  --tag-specifications 'ResourceType=security-group-rule,Tags=[{Key=Project,Value=raincheck-cloud}]' \
  2>&1 >/dev/null) || {
    case "$err" in
      *InvalidPermission.Duplicate*) echo "   rule already present" ;;
      *) echo "$err" >&2; exit 1 ;;
    esac
  }

echo "== 3. manifests"
render | kubectl apply -f -
kubectl -n kafka wait --for=condition=Ready kafka/raincheck --timeout=15m

echo "== 4. make topics, as a Job"
kubectl -n kafka delete job topics --ignore-not-found --wait
render | kubectl apply -f -
kubectl -n kafka wait --for=condition=Complete job/topics --timeout=5m
kubectl -n kafka logs job/topics

echo
echo "broker:   $(kubectl -n kafka get pod -l strimzi.io/kind=Kafka -o jsonpath='{.items[0].status.podIP}') (pod IP, a VPC IP)"
echo "next:     scripts/cloud-kafka-endpoint.sh   # point the box at that IP"
