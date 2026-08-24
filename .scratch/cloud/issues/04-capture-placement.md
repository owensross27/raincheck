# T4 — Capture placement after the cutover

Status: open
Type: task
Blocked by: 11
Owns: spec §4.

Date gate: nothing here happens before the box's **2026-08-31** fail-closed cutover [T19].

## Work

- The box runs **untouched** through the 2026-08-31 cutover. This effort never touches
  that gate or its task.
- **DEFAULT: capture stays on the box after the cutover.** The blast-radius rule is
  decisive — a cluster upgrade must never be able to take capture down, and a small box
  that only captures is a legitimate, cheap answer.
- *Overturn* only through a T19-style gate of its own: two independent proofs per day,
  seven clean days, plus an explicit blast-radius argument. **The bar is higher than
  T19's because the Mac backstop is gone by then.**
- Lambda, ECS and Fargate remain rejected for the capture shape [T19]. Not re-litigated.

## Acceptance

Either a written decision to leave capture on the box (the default, and the cheapest
outcome), or a passed gate with its evidence recorded in this file. Anything else is not
a decision.
