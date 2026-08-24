# T8 — Cost guardrails and kill criteria

Status: resolved — review process built and tested, downscale path written and
exercised on real EC2 (2026-08-24, ~$0.06 of spend, both instances terminated).
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
grouped by service, the whole-account total as the backstop's view, and the tag list
that says whether the tagged number means anything at all) and writes one dated entry
into the log at the bottom of this file.

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
- *The stages fit on a 2 vCPU / 8 GiB arm64 box.* **Exercised 2026-08-24 — see below.**

### The exercise, 2026-08-24

Both instances launched, driven and terminated: `t4g.large` on-demand (floor,
`i-05e1b1765caa2eb46`) and `c7g.xlarge` **spot** (build, `i-02dc400c55c93f783`), both in
us-east-1f, both tagged `Project=raincheck-cloud`, ~25 minutes, **~$0.06** against the
$0.40 estimate. The checkout went over with `git archive HEAD`; no `.env`, no
credential, no repo secret ever landed on either box.

| box | stage | result |
|---|---|---|
| floor | `make warm` | **OK, 19 s** — Spark 3.5.3 + Sedona 1.9.1 session, 2 vCPU / 7.6 GiB arm64 |
| floor | `make ref` | ran its Spark work, then failed in `build_assets` on `silver/stops/pick_id=…` |
| floor | `make flood-obs` | fetched 311 flood records, then failed on `ref/assets` |
| floor | `make flood-coastal` | failed on `ref/assets` |
| build | `make precip-hourly` | failed on `ref/cell_pixel` |
| build | `make flood-spine` | fetched CO-OPS hourly heights, then failed on `ref/assets` |
| build | `make flood-live` | failed on `ref/assets` |

Peak resident memory across the whole run: **794 MB** (floor) and **785 MB** (build)
against 7.6 GiB available. Nothing came close to the floor's capacity.

**Three findings, in descending order of how much they should worry someone.**

1. **The stage graph has a single root, and it is not reproducible.** Every stage that
   failed above failed on the *same* artefact — `ref/assets` — regardless of subsystem.
   `ref` builds it, and `ref` cannot complete because `build_assets` needs
   `silver/stops`, which comes from `make picks`, which is 401-blocked until the
   Interline/Transitland grant lands (hard date 2026-09-30, already a [YOU] item).
   So **no from-scratch rebuild is possible anywhere today** — not on EC2, not in
   ticket 03's ECR image, not on a reinstalled Mac. Worse: `data/ref/` (27 MB, 9 tables)
   is gitignored, and `box-coldpush.sh` only pushes `<root>/archive`, so `ref/` is **not
   in the R2 cold archive either**. It exists in exactly one place on earth: the Mac's
   local disk. That is a single point of failure for the entire project and it lands
   squarely on ticket 10's Mac-decommission gate — the Mac cannot be retired while the
   root of the stage graph lives only on it. **This is not a downscale defect**; the
   cluster has precisely the same hole. The exercise is just what made it visible.
2. **`pip install -e .` failed on a clean box.** `pyproject` pinned `eccodes>=2.48`,
   but 2.48.0 is the **C library** version `eccodes.__version__` reports through the
   `eccodeslib` wheel; the python package tops out at 2.47.0 on PyPI. The pin resolved
   on no platform at all — the Mac venv works only because it predates the pin. Fixed
   here (`eccodes>=2.47`), and it would have broken ticket 03's image build identically.
3. **The runtime ports cleanly, and the invocation contract holds.** AL2023 arm64, JDK 17
   from `.env` (the knob the Makefile already documents — no code change), venv install,
   Sedona session in 19 s. Every stage *started* as a plain `make <target>` and got as
   far as its data allowed; not one failed for a reason belonging to the box, the
   architecture, or the absence of a cluster.

**So the honest verdict:** the downscale path's *runtime* is proven on real hardware and
the sizing has headroom to spare. What is **not** proven is end-to-end per-day
throughput, because no box on earth can currently build the stage graph from scratch.
That is finding 1's problem, not this path's, and it blocks the cluster equally.

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
