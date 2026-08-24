# T8 — Cost guardrails and kill criteria

Status: open — the review process and the downscale path are built and tested; the
EC2 half of the downscale exercise is [YOU]-gated on ~$0.40 of temporary spend.
Type: task
Blocked by: 01
Owns: spec §8. **The budget alarm half was executed inside ticket 01** — see
`01-eks-cluster.md` for what is already live. This ticket owns what remains.

## Already done (ticket 01)

- `raincheck-cloud` budget, tag-filtered on `Project=raincheck-cloud`, **$130/mo**,
  notifying FORECASTED 100% and ACTUAL 80% / 100% / 130%. The 130% notification is this
  spec's hard-look line.
- `aws-account-total`, whole account, $210/mo, as the backstop that catches anything
  created without the tag.
- `Project` activated as a cost allocation tag.
- The envelope was raised from $100 to $130 on measurement: control plane $73, floor
  $34, public IPv4 $7.30, storage ~$4.50, burst ~$1.50 — **~$121.5/mo**.

## 1. The monthly bill review

`scripts/cloud-bill-review.sh [YYYY-MM] [--append]` — default month is the last closed
one, so the cadence is "run it on the 1st". It reads Cost Explorer twice (tagged spend
grouped by service, and the whole-account total as the backstop's view) and writes one
dated entry into the log at the bottom of this file.

```bash
scripts/cloud-bill-review.sh --append
```

**What the entry says, and why each part is there.**

| part | why |
|---|---|
| per-service lines | a $12 jump is a *which service* question; a total is not |
| `tagged total (N of M days)` | a mid-month or first-month review covers closed days only |
| run rate scaled to the whole month | drift is caught in the month, not the quarter — the AWS alarm only fires once the month has *already* crossed |
| delta against $130 | the envelope is the comparison, always signed |
| account total vs the $210 backstop | catches spend created without `Project=raincheck-cloud` |
| `Verdict:` / `Decision:` | the recorded decision, or the stamp saying one is owed |

**Three verdicts, three exit codes** — the same alphabet `gapverify` uses, for the same
reason: "could not check" is not a pass and not a fail.

- **0 OK** — under the line. `Decision: n/a`.
- **1 HARD LOOK** — actual crossed $130, *or* the run rate crosses it. The entry is
  stamped `Decision: REQUIRED - not yet recorded`, and
  `scripts/cloud-bill-review.sh --check` keeps failing until a human replaces that
  stamp with a real decision. `tests/test_cloud_cost.py` runs `--check` against this
  file, so an undecided crossing is a red module test — **not an auto-stop, and not a
  silent continuation either.** The three decisions on the table are spec §8's:
  shrink the streaming driver, drop the third node, or take the downscale path below.
- **2 INCONCLUSIVE** — Cost Explorer has no `Project=raincheck-cloud` data for the
  period, or `aws` itself failed. **A $0 tagged total is an artefact, never an
  under-budget verdict.** Measured 2026-08-24, hours after the cluster went live: the
  tag read `Status: Active` and the tagged total read $0 while the account total read
  $103.18. Activation backfills over up to 24 h; a review that rendered that as "under
  envelope" would be exactly the blindness this ticket exists to remove.

## 2. The downscale path — written, and half-exercised

`scripts/downscale.sh plan | up | run [floor|build] | down`. `plan` touches no AWS and
costs nothing; run it to see the arithmetic below regenerated from the measured prices.

**The shape.** An always-on `t4g.large` (2 vCPU / 8 GiB) carries capture, the stream,
the live export and the cron ticks. A `c7g.xlarge` spot box is launched for the per-day
build and terminated after. Same freshness; what is lost is per-day parallelism —
days run in sequence instead of fanning out across Karpenter burst nodes.

**The arithmetic** (measured us-east-1f, 2026-08-24: t4g.large on-demand $0.0672/hr,
t4g.large spot $0.0234, c7g.xlarge spot $0.0525, public IPv4 $0.005/hr, gp3 $0.08/GiB-mo):

| line | on-demand floor | spot floor |
|---|---|---|
| floor t4g.large, 730 h | 49.06 | 17.08 |
| floor public IPv4 | 3.65 | 3.65 |
| floor gp3 50 GiB | 4.00 | 4.00 |
| build c7g.xlarge spot, ~30 h/mo | 1.57 | 1.57 |
| build IPv4 + root gp3 | 0.22 | 0.22 |
| R2 | 0.47 | 0.47 |
| **total** | **58.97** | **27.00** |

**The map's `$25-60/mo` is not fuzz — it is that column choice.** On-demand buys an
always-on box that cannot be reclaimed mid-stream; spot buys $32/mo and a restart
policy. Against the measured cluster at $121.50 that saves $62.53 or $94.50 a month,
and the $73.00 EKS control plane is the whole of what disappears.

**What is proven, and what is not.** The path rests on two claims, and they are not
equally cheap to check:

- *No stage needs the cluster.* **Proven, free, permanently.** `tests/test_cloud_cost.py`
  reads the real Makefile and asserts no recipe shells out to `kubectl`/`eksctl`/`helm`/
  `k8s://`, and that no module under `src/raincheck/` imports a Kubernetes client or
  reads `KUBERNETES_SERVICE_HOST`. Today every stage recipe is `$(PY) -m raincheck.<mod>`
  and nothing else, which is why the constraint costs nothing to keep. A third test
  asserts every stage `downscale.sh` would exercise resolves to a real make target, so
  the exercise list cannot rot into fiction.
- *The stages fit on a 2 vCPU / 8 GiB arm64 box.* **Not proven without spending.** This
  is the claim that would actually invalidate the path, and the Mac cannot answer it —
  it has far more memory than a t4g.large. `up` refuses to launch without
  `RAINCHECK_DOWNSCALE_OK=1`; the exercise burns **$0.134/hr**, about **$0.40** for a
  three-hour run.

**The exercise set** — chosen so no repo credential ever lands on a throwaway box; every
one of these reads public sources only (NOAA AORC open data, NYC open data):

| box | stage | what it proves |
|---|---|---|
| floor | `make warm` | a Sedona session starts inside 8 GiB on 2 vCPU — the sizing question |
| floor | `make ref` | a real Spark write on the always-on box |
| floor | `make flood-obs` | a fetch-and-write stage end to end |
| build | `make precip-hourly SRC=aorc MONTH=…` | the heaviest regular stage, on the scheduled box |

`run` ships the checkout with `git archive` (never a working tree, never `.env`),
installs the venv, and times each stage so "same freshness" is measured rather than
asserted. The port itself is one line: AL2023 has no brew keg, so `JAVA_HOME` comes
from `.env` — the knob the Makefile already documents. No code change, which is the
same finding as the constraint test from the other direction: nothing here is
Mac-shaped *or* cluster-shaped.

## 3. The standing constraint

**No stage may depend on a cluster-only feature.** Every stage stays runnable as
`make <target>` inside the same image on one box. This binds every other ticket in this
effort, and it is now a test rather than a paragraph — see the two Makefile/module
assertions above. A ticket that needs `kubectl` inside a stage recipe has not found a
workaround; it has turned the escape hatch back into prose.

One deviation to close later: the exercise bootstraps the repo venv on AL2023 rather
than running the ECR image, because **the image is ticket 03's deliverable and does not
exist yet**. When it does, `downscale.sh`'s `bootstrap()` becomes
`docker run <ecr>:<sha> make <target>` and the claim tightens from "same repo on one
box" to spec §8's literal "same image on one box".

## Kill criteria

$130 is the hard-look line, not an auto-stop. Crossing it means a recorded decision:
shrink the streaming driver, drop the third node, or take the downscale path. The
review script stamps the requirement and `--check` refuses to go quiet until the
`Decision:` line is real.

## Bill review log

One dated entry per month, appended by `scripts/cloud-bill-review.sh --append`. This
section stays last in the file; entries are `### bill YYYY-MM`, and `--check` reads
their `Verdict:` / `Decision:` pairs. Do not hand-write an entry that the script would
have written — the point is that the numbers come from Cost Explorer, not from memory.

*(First entry due 2026-09-01 for 2026-08. Runs before the tag populates return
INCONCLUSIVE; that is a correct answer, and it is worth recording as one.)*
