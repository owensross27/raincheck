# 19 — Cloud capture runner: always-on archiver off the laptop

**What to build:** The archiver's capture loop running on a small always-on Linux box, so
2026 storm continuity stops depending on the Mac's lid. The box captures the same feeds the
LaunchAgent does today (bus VP/TU/alerts, eight subway feeds + subway alerts, daily static
zips) and pushes to the same R2 bucket (`make coldpush` equivalent) on a timer. The Mac
stays the compute node: enrichment pulls Bronze from R2 (egress is $0) or reads its own
local capture; the local LaunchAgent becomes redundant backup or is retired once the box
proves out over a week.

**Authorization:** Ross, 2026-08-23, via his overview session: "we need to set this up to
run for real over the cloud. my sleeping laptop is not going to cut it" — the cloud-compute
yes for CAPTURE ONLY, scoped to one small VM polling public keyless feeds and writing to
the private R2 bucket. Not public hosting; enrichment/Spark stays local.

**Blocked by:** None (18 resolved — bucket, credentials and sync conventions exist)

**Status:** built — wizard awaits Ross (`scripts/cloud-capture-wizard.sh`)

- [x] provider pick, one short note: Oracle Always-Free ARM (a1.flex, $0, capacity/signup
      friction risk) vs Hetzner CAX11 (~EUR 3.3/mo, boring and reliable). Default to
      whichever the wizard reaches first; the runner must be provider-agnostic (plain
      systemd + python3 + aws cli, nothing else). — see Provider note below
- [x] archiver runs under systemd on the box (timer or long-running service matching the
      LaunchAgent cadences: VP 30s, TU 120s, alerts 300s, subway 60s, static daily) with
      the existing 10-min-part Bronze layout; TZ=UTC; disk cap with loud stop like 05's.
      — `systemd/raincheck-archiver.service`: the unmodified archiver loop (cadences and
      layout live in the code); `Restart=on-failure` honors the exit-0 STOPPED_BUDGET
      loud stop, `RAINCHECK_BRONZE_GB` on the box defaults to 20
- [x] `coldpush` equivalent on a timer (hourly is fine) from the box to the same bucket
      prefix; never deletes remote; the box keeps only a small rolling local buffer
      (push-then-prune once verified remote, mirroring low-disk mode).
      — `scripts/box-coldpush.sh` + `systemd/raincheck-coldpush.{service,timer}` (hourly):
      sync, then prune only files >6h old that a size-only dryrun no longer lists;
      etags.json and STOPPED_BUDGET never pruned; an old-but-unverified file fails the
      unit loudly (STUCK)
- [x] `/wizard` for the human steps: provider account, VM create, ssh key, `.env` on the
      box (R2 creds + RAINCHECK_*), service install, first-push verify. Ross runs it.
      — `scripts/cloud-capture-wizard.sh`, 8 stages, both provider paths; stages 5-8
      are automated over ssh (install, /etc/raincheck.env, units, first push)
- [ ] cutover note recorded on this ticket: date the box's capture is verified continuous
      for 7 days; decision then whether the Mac LaunchAgent stays as backup or is booted
      out (`launchctl bootout gui/$(id -u)/com.raincheck.archiver`).
- [x] one runnable check: an hour-completeness query (24 hour-dirs per feed per closed UTC
      day in the bucket) that is loud on any gap; doubles as the daily health check.
      — `scripts/coldgaps.sh` (6 kinds x 24 hour-dirs, exit 1 + COLDGAPS lines on any
      miss): `make coldgaps [DATE=...]` from the Mac, daily 02:15 UTC on the box via
      `systemd/raincheck-coldgaps.{service,timer}`

## Provider note (2026-08-22)

Oracle Always-Free ARM first: a1.flex at $0/month forever is the right price for a
poller, and the box only needs outbound https — but signup friction and "Out of
capacity" on A1 shapes are real, so the wizard treats it as attempt one, not a
commitment. Hetzner CAX11 (~EUR 3.3/mo, Falkenstein/Helsinki only — latency is
irrelevant at 30s cadence) is the boring fallback the same wizard sets up end-to-end.
The runner is deliberately provider-agnostic — Ubuntu 24.04 + systemd + python3 venv +
pip awscli, nothing else — so switching is one wizard re-run against a fresh IP.

## Implementation note (2026-08-22, agent)

The box deploys `src/raincheck/` exactly as committed (no archiver changes; ticket 10's
in-flight work is untouched). Layout on the box: code + venv + data under
`/opt/raincheck`, secrets in root-owned `/etc/raincheck.env` (600), units run as the
nologin `raincheck` user. Local rolling buffer: hourly push-then-prune keeps ~6h of
parts; if R2 is unreachable the prune stops, the disk fills toward RAINCHECK_BRONZE_GB
and the archiver's own loud stop fires. Tests: `tests/test_cloud_scripts.py` (stub aws;
prune keep/delete/stuck matrix, coldgaps loud/quiet).

Ticket-10 interaction (landed as 5130ba2 while this built): the archiver now publishes
bus vp/tu to Kafka as a per-poll side effect, exception-wrapped so capture never blocks.
The box venv includes `confluent-kafka` anyway: without it the lazy import raises ~150
caught-but-logged ImportErrors/hour into the journal; with it, librdkafka quietly retries
localhost:9092, messages expire at 30s, and errors report once per flush window. Point
RAINCHECK_KAFKA at a real broker in /etc/raincheck.env if the box should ever feed one.

Known wrinkle while BOTH the Mac and the box capture: parts for the same window differ
by fetch timing, so whichever pushed last wins in the bucket and the Mac's
`make coldcheck` may report size mismatches. That is overlap, not data loss — either
side's part is a valid capture. Goes away at cutover.

## Running the wizard (Ross)

From the repo root on the Mac: `scripts/cloud-capture-wizard.sh` — ~20-30 min active.
Pre-reqs: `.env` already carries RAINCHECK_COLD_* (it does; the wizard checks and
refuses otherwise); a card for identity verification at whichever provider.

- Stage 1 picks the path: y = Oracle Always-Free (a1.flex, $0/mo; expect signup friction
  and possible "Out of capacity" — if it blocks, re-run and answer n), n = Hetzner CAX11
  (~EUR 3.3/mo, Falkenstein/Helsinki, instant). The runner is identical on both.
- Stage 2 uses/creates an ssh key; you paste the printed pubkey into the provider console.
- Stages 5-8 are automated over ssh (install, /etc/raincheck.env with mode 600, systemd
  units, first push + journal check). Interrupting any time is safe: re-run resumes with
  saved values.
- Afterwards, daily health is `make coldgaps` from the Mac or `systemctl --failed` on the
  box; review found and closed one blind spot — the archiver's clean-exit budget stop is
  surfaced by coldgaps (marker check), not by --failed alone.

Review record (2026-08-23): 3-lens adversarial workflow (18 agents), 9 unique confirmed
findings all fixed pre-merge — headline: the prune "verified remote" match compared
absolute paths against aws's cwd-relative dryrun output, so the STUCK guard was
unreachable and old unverified Bronze could be deleted; the test stub emitted the same
fiction and masked it. Both rewritten (exact ROOT-relative line match, truthful stub,
cwd=/ in tests). Also fixed: /etc/raincheck.env 0644 creation window, apt lock race on
fresh VMs, fatal is-active probe, ssh errors hidden on retry loop, rsync -e quoting
(replaced with tar-over-ssh), aws errors misreported as capture gaps, budget-stop
invisibility. Refuted (no change needed): box-token delete-scope escalation chain,
"permanent invisible outage" scenario. Suite 144/144 green on rebased master.

## Cutover (pending)

Box first-push date: ______ (wizard stage 8). After 7 consecutive clean
`coldgaps` days, record the date here and decide: Mac LaunchAgent stays as backup or
`launchctl bootout gui/$(id -u)/com.raincheck.archiver`.

## Provider decision amended (2026-08-23, Ross)

Ross has an always-on EC2 dev box — deploy the runner THERE instead of creating an
Oracle/Hetzner VM. Lambda and ECS were considered and rejected: the archiver is a
long-running 30 s poller (worst shape for Lambda — would need a rewrite into stateless
invocations), and an always-on ECS/Fargate service costs more than the already-running
box. The runner is provider-agnostic by design, so this is the wizard's stages 5-8
(ssh install, /etc/raincheck.env, units, first push + coldgaps) pointed at the EC2 box;
stages 1-4 (account/VM creation) are skipped. Needs from Ross at deploy time: the box's
ssh alias/IP + key, confirmation it's Ubuntu-ish with outbound https, and a nod that
raincheck may claim /opt/raincheck + three systemd units on it. Nothing else on the box
gets touched.
