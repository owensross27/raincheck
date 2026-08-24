# 01 — Lift the no-alerting rule and retire the falsified claim string

**What to build:** The standing no-alerting rule now permits flood-tier notifications and
nothing else, and no document still tells a reader that raincheck is "a page you open
during a storm, not a service that watches" — a claim a notifier falsifies the moment it
exists. Spec: section 7; Further Notes corrections 1 and 2.

**Blocked by:** None — can start immediately.

**Status:** ready-for-agent

- [ ] the five distinct documents recording the rule carry the scoped lift — barred except for flood tiers under `.scratch/notify/spec.md`, with a pointer to it: `.scratch/pipeline/map.md`, `.scratch/pipeline/spec.md` (`.scratch/build/spec.md` symlinks to it — one document, edited once), `.scratch/flood/map.md`, `.scratch/flood/spec.md`, `.scratch/flood-build/spec.md`
- [ ] non-flood alerting stays explicitly barred in every amended document: the lift names its scope, it never deletes the rule
- [ ] all six occurrences of "a page you open during a storm, not a service that watches" are gone — the destination bullet, the fixed-strings list and the honesty clause of `.scratch/flood/spec.md`, and the same three in `.scratch/flood-build/spec.md` (line numbers drift; the string is the key)
- [ ] one frozen replacement string keeps the honesty the original carried — ranks where a flood REPORT is likely, hour-grain evidence trailing the storm, never observes water — while surviving the existence of a notifier
- [ ] the replacement lands in the flood spec's fixed-strings list (F15's list), so the panel and any message cannot contradict each other, and ticket 09 reuses it verbatim
- [ ] a grep over `.scratch/` returns zero hits for the retired string
