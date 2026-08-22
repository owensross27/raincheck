"""Pure DataFrame helpers shared by batch jobs, the streaming job and tests (spec A).
DataFrame API only, no temp views, no I/O. Grows with tickets 05+."""
from pyspark.sql import Column, functions as F


def ceil_hour(ts: Column) -> Column:
    """Hour-ending label of an instant: exactly on the hour stays in that Hour, one
    microsecond after rolls forward (08-T5). Joins precip on (src, cell, hour_end_utc)."""
    trunc = F.date_trunc("hour", ts)
    return F.when(trunc == ts, ts).otherwise(trunc + F.expr("INTERVAL 1 HOUR"))
