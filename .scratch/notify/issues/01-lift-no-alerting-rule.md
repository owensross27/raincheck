# 01 — Lift the no-alerting rule and retire the falsified claim string

**What to build:** The standing no-alerting rule now permits flood-tier notifications and
nothing else, and no document still tells a reader that raincheck is something you open
during a storm rather than anything that reaches you — a claim a notifier falsifies the
moment it exists. Spec: section 7; Further Notes corrections 1 and 2.

**Blocked by:** None — can start immediately.

**Status:** COMPLETE 2026-08-23 (docs only; branch `notify01-rule-lift`)

- [x] the five distinct documents recording the rule carry the scoped lift — barred except for flood tiers under `.scratch/notify/spec.md`, with a pointer to it: `.scratch/pipeline/map.md`, `.scratch/pipeline/spec.md` (`.scratch/build/spec.md` symlinks to it — one document, edited once), `.scratch/flood/map.md`, `.scratch/flood/spec.md`, `.scratch/flood-build/spec.md`
- [x] non-flood alerting stays explicitly barred in every amended document: the lift names its scope, it never deletes the rule ("Non-flood alerting, bus delay included, stays barred and would need its own validation and its own map", in all five)
- [x] all six occurrences of the retired storm-page claim are gone — the destination bullet, the fixed-strings list and the honesty clause of `.scratch/flood/spec.md`, and the same three in `.scratch/flood-build/spec.md`
- [x] one frozen replacement string keeps the honesty the original carried — ranks where a flood REPORT is likely, hour-grain evidence trailing the storm, never observes water — while surviving the existence of a notifier. **The frozen text, verbatim and not to be re-worded:**

  > raincheck ranks where a flood REPORT is likely from rain that has already fallen, on hour-grain evidence that trails the storm. A rank is not an observation of water, and a quiet panel or a quiet inbox means nothing was flagged, not that nothing flooded.

- [x] the replacement lands in the flood spec's fixed-strings list (F15's list) in both spec copies, so the panel and any message cannot contradict each other, and ticket 09 reuses it verbatim
- [x] a grep over `.scratch/` returns zero hits for the retired string

**Beyond the ticket's count, and why.** The measured six were the claims; two more
copies were *instructions* that would have put the retired claim straight back onto
the page, so they carry the frozen string instead:
`.scratch/flood-build/issues/15-flood-panel-and-exports.md` (F15's own fixed-strings
bullet — the panel builder reads this, not the spec) and
`.scratch/flood/issues/10-realtime-detector.md` (the resolved design record F15's list
was derived from, amended in place rather than rewritten). The notify effort's own
docs (this ticket, `map.md`, `spec.md`) named the retired claim by quoting it; they
now name it descriptively, so the zero-hits grep stays meaningful. Two frozen
adversarial-verdict archives quoted it as evidence
(`.scratch/flood/assets/10-adversarial-verdicts.json`,
`.scratch/flood-build/assets/ticket-adversarial-verdicts.json`): the quotes are
**redacted with a bracketed marker**, not rewritten — the reviewers' arguments stand
untouched and the original wording is recoverable from git history.
