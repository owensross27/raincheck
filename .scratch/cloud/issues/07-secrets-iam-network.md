# T7 — Secrets, IAM, network

Status: open
Type: task
Blocked by: 01
Owns: spec §7.

## Work

- **The least-privilege split is R2 API tokens, not IAM** — R2 is Cloudflare and IRSA
  cannot scope it. Three tokens:
  - **capture-write** — the box, already in place
  - **build-read/write** — cluster batch and streaming
  - **serve-read/write** — the export path, **scoped to the public bucket only**
  Each lands as a Kubernetes Secret bound to **exactly one ServiceAccount**, never baked
  into an image, with a **written rotation procedure** in this file.
- **IRSA covers the AWS side**: ECR pull, EBS CSI, CloudWatch/budgets. One role per
  workload, no shared node role for application permissions.
- **No inbound from the internet.** No LoadBalancer or NodePort Service. Two named
  exceptions: (a) the static host, which is outside the cluster entirely (ticket 09), so
  not cluster ingress at all; (b) whatever minimal subscribe ingress
  `.scratch/notify/map.md` ticket 4 decides, which must arrive as its own reviewed decision.
- **No NAT Gateway.** At ~$32/mo it would consume more than the entire non-control-plane
  budget. Nodes sit in public subnets with public IPs and security groups that permit no
  inbound. **"No inbound" is enforced by the security groups and the absence of a load
  balancer — write it that way in the manifests and assert it, because subnet placement
  is not what is providing it here.**

## Already true after ticket 01 — verify, do not redo

The floor node SG `sg-04b76aed2bb2fb61f` has **zero CIDR sources** (only itself and the
control-plane SG). Ticket 02 adds exactly one inbound rule, from the capture box's
`sg-0cb33dca0ac107599` to the broker port. Any other inbound rule is a regression.

Also note from 01: public IPv4 is **$3.65/node/mo**, not free. The no-NAT decision still
wins — break-even is ~9 nodes — but it must stay counted as burst grows.

## Tests

Extends `tests/test_cluster_manifests.py`: every ServiceAccount maps to exactly one R2
token Secret; no Secret value appears in a container image or a plain env literal; no
`LoadBalancer`/`NodePort` Service; no SG rule granting inbound from `0.0.0.0/0` except the
named exceptions.
