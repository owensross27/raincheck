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

**Status:** ready-for-agent

- [ ] provider pick, one short note: Oracle Always-Free ARM (a1.flex, $0, capacity/signup
      friction risk) vs Hetzner CAX11 (~EUR 3.3/mo, boring and reliable). Default to
      whichever the wizard reaches first; the runner must be provider-agnostic (plain
      systemd + python3 + aws cli, nothing else).
- [ ] archiver runs under systemd on the box (timer or long-running service matching the
      LaunchAgent cadences: VP 30s, TU 120s, alerts 300s, subway 60s, static daily) with
      the existing 10-min-part Bronze layout; TZ=UTC; disk cap with loud stop like 05's.
- [ ] `coldpush` equivalent on a timer (hourly is fine) from the box to the same bucket
      prefix; never deletes remote; the box keeps only a small rolling local buffer
      (push-then-prune once verified remote, mirroring low-disk mode).
- [ ] `/wizard` for the human steps: provider account, VM create, ssh key, `.env` on the
      box (R2 creds + RAINCHECK_*), service install, first-push verify. Ross runs it.
- [ ] cutover note recorded on this ticket: date the box's capture is verified continuous
      for 7 days; decision then whether the Mac LaunchAgent stays as backup or is booted
      out (`launchctl bootout gui/$(id -u)/com.raincheck.archiver`).
- [ ] one runnable check: an hour-completeness query (24 hour-dirs per feed per closed UTC
      day in the bucket) that is loud on any gap; doubles as the daily health check.
