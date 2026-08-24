# T7 — Secrets, IAM, network  ✅ DONE (2026-08-24, branch `cloud07-secrets-iam-network`)

Status: done
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

CREATED `tests/test_cluster_manifests.py` here — cloud 02 was to have created it and had not, so this ticket did; later tickets EXTEND it (15 tests): every ServiceAccount maps to exactly one R2
token Secret; no Secret value appears in a container image or a plain env literal; no
`LoadBalancer`/`NodePort` Service; no SG rule granting inbound from `0.0.0.0/0` except the
named exceptions.


---

# Close-out (2026-08-24, branch `cloud07-secrets-iam-network`)

## What landed

| file | what it is |
|---|---|
| `deploy/k8s/serviceaccounts.yaml` | namespace `raincheck` + ServiceAccounts `raincheck-build` and `raincheck-serve`, each annotated with the ONE R2 Secret and the ONE bucket it may reach |
| `deploy/cloud/inbound-allowlist.yaml` | every inbound rule the cluster SGs may carry, the two named exceptions, and cloud 02's pending slot |
| `scripts/r2-secrets.sh` | creates/rotates `r2-build` / `r2-serve` from the operator's environment; `--check` proves a token reaches its bucket |
| `scripts/inbound-audit.py` | compares the live security groups against the allowlist; rc 0 clean / 1 violations / 2 INCONCLUSIVE |
| `tests/test_cluster_manifests.py` | 15 tests: the SA↔Secret binding, no secret material, no LoadBalancer/NodePort/hostPort/Ingress, the allowlist's shape, and the audit driven against a verbatim `describe-security-groups` capture |

**No R2 token was created by this ticket** — that is a Cloudflare dashboard step and no
Cloudflare account API token exists on this Mac. `r2-build` and `r2-serve` do not exist
yet; the first cluster workload that reads or writes R2 (cloud 03) needs Ross to walk the
creation procedure below first. Filed in the runbook's [YOU] standing items.

## Rotation procedure (also the creation procedure — step 1 is the only difference)

Verified against Cloudflare's R2 API-token docs on 2026-08-24. **R2 tokens have exactly
four permission levels — "Admin Read & Write", "Admin Read only", "Object Read & Write",
"Object Read only" — and Object-level tokens scope to specific BUCKETS. There is no
prefix scoping and no write-only level.** Two consequences worth stating plainly:

- capture-write and build are both `Object Read & Write` on `raincheck-bronze`, i.e.
  **identical grantable power**. The split buys independent rotation and a smaller blast
  radius per credential, not different capabilities. If prefix separation ever matters it
  needs separate buckets, not separate tokens.
- serve is the one that is genuinely narrower, because the public bucket is a different
  bucket. That is exactly why spec §9 refuses to reuse `raincheck-bronze`, and why the
  manifest test asserts the two buckets differ.

**Rotate a token (no downtime, old credential stays valid until the last step):**

1. Cloudflare dashboard → R2 → **API** → *Create API token*. Permission
   `Object Read & Write`, scoped to **specific buckets**: `raincheck-bronze` for
   `build`, the public bucket for `serve`. Name it `raincheck-<role>-<YYYY-MM>` so the
   token list reads as a rotation history. Copy the Access Key ID and Secret Access Key —
   **the secret is shown once and is not retrievable afterwards.**
2. Put them in the environment (never in a file in this repo, never on a command line):
   `export RAINCHECK_R2_BUILD_KEY_ID=… RAINCHECK_R2_BUILD_SECRET=… RAINCHECK_R2_BUILD_BUCKET=raincheck-bronze`
3. `scripts/r2-secrets.sh build --check` — proves the new token can list its bucket
   **before** anything depends on it. A bad paste stops here, while the old token still works.
4. `scripts/r2-secrets.sh build` — writes/overwrites Secret `raincheck/r2-build`.
5. Restart the consumers (a running pod keeps the env it started with):
   `kubectl -n raincheck rollout restart deploy -l raincheck.io/r2-secret=r2-build`, and
   re-run any Job/CronJob that failed in the window.
6. Confirm the workloads are healthy, **then** delete the OLD token in the Cloudflare
   dashboard. Deleting first is what turns a rotation into an outage.
7. The box's `capture-write` token is not in this cluster: it rotates by editing `.env`
   on the box and restarting `raincheck-archiver`/`raincheck-coldpush` (ticket 18/19).
   `make coldcheck` is its equivalent of step 3.

**Secret hygiene the tooling enforces, not just asks for:** `r2-secrets.sh` passes values
through a 0600 temp file (`--from-env-file`), never `--from-literal`, because argv is
readable by every user on the host via `ps`; nothing echoes a value; the Makefile's cold
recipes are already `@`-silenced. `tests/test_cluster_manifests.py` fails if a manifest
gains a Secret with `data`/`stringData`, if a container gets a credential as a literal
`value:`, or if the script starts using `--from-literal`.

## The Secret's contents (frozen — cloud 03/05/06 consume these key names)

`r2-build` and `r2-serve` each hold exactly: `AWS_ACCESS_KEY_ID`,
`AWS_SECRET_ACCESS_KEY`, `AWS_ENDPOINT_URL`, `AWS_DEFAULT_REGION=auto` (R2 rejects real
AWS region names — ticket 18). A workload consumes one with
`envFrom: [{secretRef: {name: r2-build}}]` and `serviceAccountName: raincheck-build`.
The bucket is NOT in the Secret — it is not a secret; it is on the ServiceAccount as
`raincheck.io/r2-bucket`.

## IRSA inventory — measured 2026-08-24, and NO new IAM role was created

One role per workload, no application permission on a node role. What exists today
already satisfies that, so this ticket created nothing:

| workload | identity | how |
|---|---|---|
| EBS CSI controller | `eksctl-raincheck-addon-aws-ebs-csi-driver-Role1-dDD8mT9Q6U5v` | IRSA on `kube-system/ebs-csi-controller-sa` (ticket 01's `wellKnownPolicies`) |
| Karpenter | `eksctl-raincheck-iamservice-role` | IRSA on `karpenter/karpenter` |
| ECR image pull | node role, `AmazonEC2ContainerRegistryPullOnly` | kubelet-level image pull, not an application permission — no pod calls ECR |
| CloudWatch / Budgets | none in-cluster | the budget alarms are account-level (ticket 01); nothing in the cluster publishes metrics |
| `raincheck-build`, `raincheck-serve` | none | they speak S3 to Cloudflare R2, which no AWS identity can grant |

Node roles carry only `AmazonEKSWorkerNodePolicy`, `AmazonSSMManagedInstanceCore`,
`AmazonEC2ContainerRegistryPullOnly` (+ `AmazonEKS_CNI_Policy` on the Karpenter node
role) and no inline policies — verified, not assumed. OIDC provider:
`https://oidc.eks.us-east-1.amazonaws.com/id/43040ADB32E8FFB30E19EFE1135FB504`.

**The rule for later tickets: a pod that needs an AWS API call needs a NEW IAM role, and
a new IAM role is a Ross decision — pause and ask.** Annotating a ServiceAccount with
`eks.amazonaws.com/role-arn` is that moment.

## Network — verified, not redone

`scripts/inbound-audit.py` run against the live account on 2026-08-24: **OK, three cluster
security groups, zero CIDR sources.**

| SG | inbound |
|---|---|
| `sg-04b76aed2bb2fb61f` (`eks-cluster-sg-raincheck-695028236`) | itself + `sg-03b1743dee87eb474` only |
| `sg-03b1743dee87eb474` (eksctl ClusterSharedNodeSecurityGroup) | itself + `sg-04b76aed2bb2fb61f` only |
| `sg-0c610cd458155ee42` (eksctl ControlPlaneSecurityGroup) | none at all |

Egress is `0.0.0.0/0` and stays that way: with no NAT Gateway the nodes need direct
egress. Public IPv4 is **$3.65/node/mo** and stays counted — break-even against a NAT
Gateway is ~9 nodes, so the no-NAT decision holds, but burst growth moves that number.

**Trap for anyone running an AWS command here: this Mac's default region is `us-east-2`.
The cluster is `us-east-1`. Without `--region us-east-1` you get `InvalidGroup.NotFound`
and might conclude the SG was deleted.**

### Hazard handed to cloud 02

The capture box `i-098a6ea89c4b15502` (private `172.31.66.109`) carries
`sg-0cb33dca0ac107599` — named **`lewis-signs-dev-sg`**, a shared dev SG that a second,
unrelated instance also uses (`i-0a924268a565ad38a`, `vinylpig-staging`) and which itself
allows `0.0.0.0/0` on tcp/443. **A broker rule sourced from that SG grants Kafka to
`vinylpig-staging` too.** Source it from `172.31.66.109/32` and record it under
`cidr_exceptions` with the ticket number, or give the box its own SG first — attaching a
new SG to that instance touches another project, so ask Ross before doing it that way.

### The two named exceptions — both still undrawn

- **static host (cloud 09)** — outside the cluster entirely, so it is not cluster ingress
  and needs no rule. Named only so it is never mistaken for one.
- **notify subscribe ingress (notify 04)** — a RESERVATION. notify 07 landed 2026-08-24
  with no HTTP write path at all, so nothing is drawn. What reopens it is
  `raincheck.notify_store.DEFERRAL_TRIGGER`: the first non-tester subscriber, 25 entries,
  or a public announcement of the map page. When one fires it arrives as its own reviewed
  decision — a NetworkPolicy/ingress design, not an edit to the allowlist.

## Deliberate omissions

- **No RBAC restricting `get secrets` per ServiceAccount.** Kubelet mounts a Secret
  regardless of the pod's RBAC, so RBAC would only stop an API-mediated read — and cloud
  03's cluster-mode Spark driver genuinely needs API access. The binding is enforced where
  it is actually enforceable: in the manifests, by the test. Upgrade path if a workload is
  ever untrusted: `automountServiceAccountToken: false` on `raincheck-serve` (it calls no
  Kubernetes API) plus a Role limiting `get secrets` to its own name.
- **No NetworkPolicy.** Nothing to isolate yet — one namespace, no ingress, and the VPC
  CNI needs network-policy support switched on to enforce one. It arrives with the notify
  exception, if that ever fires.

## Defect found and fixed 2026-08-24 (during cloud 12's session, at Ross's direction)

**`kubectl apply` was writing the token into an ANNOTATION.** `r2-secrets.sh` was careful
in every other respect - values through a 0600 temp file, never argv, nothing echoed - but
the final `... -o yaml | kubectl apply -f -` is a CLIENT-SIDE apply, and a client-side
apply records the entire object it sent in
`kubectl.kubernetes.io/last-applied-configuration`. For a Secret, that object IS the
token. The annotation then defeats the one redaction the tooling gives you for free:
`kubectl describe secret` prints `.data` as a byte count and prints annotations IN FULL.
Measured on the live `r2-build` Secret the moment it was created.

FIXED: the apply is now `--server-side --force-conflicts
--field-manager=raincheck-r2-secrets`, which tracks ownership in `managedFields` and writes
no such annotation, plus a defensive `kubectl annotate ... last-applied-configuration-` to
strip one an older client-side apply may have left. Verified: a re-run leaves only the two
`raincheck.io/*` annotations, and `describe` shows byte counts only.

**Applies to any Secret this repo ever applies**, not just these two - the same one-line
mistake is available everywhere `create secret ... | kubectl apply` is written.
