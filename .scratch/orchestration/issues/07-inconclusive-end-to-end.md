# 07 — INCONCLUSIVE end to end

**What to build:** The third outcome survives the whole path. A stage that could not
check something lands in a task state visibly distinct from both success and failure, and
the run summary counts failures and inconclusives apart. This is the distinction five
incidents were spent creating: a dead endpoint rendered as a data gap sends someone
hunting a phantom, and a check that did not run rendered as OK hides a real one.

**Blocked by:** 02 (check-result rows), 05 (the nightly DAG).

**Status:** ready-for-agent

- [ ] An rc=2 from any stage renders as a task outcome distinct from both success and failure
- [ ] No configuration of this mapping renders inconclusive as failed, and none renders it as ok — that property is the ticket
- [ ] The report task counts and names failures and inconclusives separately; neither number is inflated by the other
- [ ] The check's own row stays the authoritative record; the task state is a rendering of it
- [ ] A test drives all three outcomes through the mapping and asserts the resulting states differ
