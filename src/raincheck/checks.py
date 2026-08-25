"""Check-result rows (orchestration ticket 02): the one vocabulary every verification
stage speaks, so the CLI, the DAG and a GX suite all read the same verdict.

A Row names WHAT was checked (`check` + `subject`), the OUTCOME (`ok` / `fail` /
`inconclusive`) and the MEASUREMENTS behind it. Three outcomes, not two: a check that
could not run tells you nothing about the data, and reporting that as either a pass or a
gap sends someone hunting a phantom. rc is the CLI rendering of a batch:

    1 if any row failed, else 2 if any row is inconclusive, else 0

- a real gap outranks a not-run check, so an inconclusive beside a failure is still 1.

Rows carry NO feed payload - counts, dates, kinds, hour labels, ratios and shas only.
GX renders unexpected values into Data Docs, so a batch of Bronze would publish MTA rows
to a public host. `write()` asserts each row's flat column tuple against the producer's
declared one, in order, so drift is a crash and not a leak.
"""
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

OK, FAIL, INCONCLUSIVE = "ok", "fail", "inconclusive"
OUTCOMES = (OK, FAIL, INCONCLUSIVE)
CORE = ("check", "subject", "outcome", "detail")  # every producer's first four columns
VALUE = (int, float, str, bool, type(None))


@dataclass(frozen=True)
class Row:
    check: str            # the producer: "gapcheck", "gapverify", ...
    subject: str          # what it looked at: "vp 2026-08-15", a partition, a canary name
    outcome: str          # OK / FAIL / INCONCLUSIVE
    detail: str = ""      # the printed line's tail; short, payload-free
    measures: dict = field(default_factory=dict)

    def __post_init__(self):
        assert self.outcome in OUTCOMES, self.outcome

    def flat(self) -> dict:
        return {"check": self.check, "subject": self.subject, "outcome": self.outcome,
                "detail": self.detail, **self.measures}


def rc(rows) -> int:
    """The aggregation rule. Note an EMPTY batch is 0: a producer with nothing to say must
    emit an inconclusive row rather than no rows - that is the false-OK this ticket kills.

    The 2 below has ONE mirror, and it is deliberate: `daily.INCONCLUSIVE_RC`, which has to
    be a literal because the DAG image reads daily.py as data and has no raincheck package
    to import from (ticket 07). tests/test_daily.py derives that constant from THIS function
    rather than comparing it to a 2, so moving the rule here goes red there."""
    if any(r.outcome == FAIL for r in rows):
        return 1
    return 2 if any(r.outcome == INCONCLUSIVE for r in rows) else 0


def write(root: Path, name: str, rows, columns: tuple[str, ...],
          at: datetime | None = None) -> Path:
    """Persist one run's rows as JSONL under the data root, so a suite has a batch and the
    report task has a source. Retention is a bucket lifecycle rule, not a stage."""
    for r in rows:
        flat = r.flat()
        assert tuple(flat) == columns, f"{name} row columns {tuple(flat)} != declared {columns}"
        bad = {k: v for k, v in flat.items() if not isinstance(v, VALUE)}
        assert not bad, f"{name} row carries non-scalar values {bad}"
    stamp = (at or datetime.now(timezone.utc)).strftime("%Y%m%dT%H%M%SZ")
    out = root / "checks" / f"check={name}" / f"run={stamp}.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("".join(json.dumps(r.flat()) + "\n" for r in rows))
    return out
