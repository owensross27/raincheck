# T8 — Cost guardrails and kill criteria

Status: open
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
  $34, public IPv4 $7.30, storage ~$4.50, burst ~$1.50 — **~$121.5/mo**. Spec §1's
  `~$27 remains` and §7's implicit "public IPs are free" are both wrong and should be
  corrected in the spec.

## Remaining work

- **Monthly bill review, recorded in the repo alongside this effort.** Drift caught in a
  month rather than a quarter. One dated entry per month appended to this file, actual
  against the $130 envelope, with the delta explained.
- **Write and exercise the downscale path**: the two-EC2 alternative — an always-on
  t4g.large-class instance plus a scheduled build instance, ~$25-60/mo, same freshness,
  no per-day parallelism. **Reversibility is design, not admission**, and a path that is
  never exercised is a paragraph, not a path.
- **The standing constraint that keeps it real: no stage may depend on a cluster-only
  feature.** Every stage stays runnable as `make <target>` inside the same image on one
  box. This is a constraint on every other ticket in this effort, not a note in this one.

## Kill criteria

$130 is the hard-look line, not an auto-stop. Crossing it means a recorded decision:
shrink the streaming driver, drop the third node, or take the downscale path.
