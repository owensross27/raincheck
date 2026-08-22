# 10-T4: gold/cell_hour_speed vs MTA published speeds (report-only)

Built 2026-08-22 against the loaded slice at `/Users/ross/raincheck/data`.

Known biases, named up front (spec I): our chord distance runs 7-15% short of
the path (a chord ratio overstates a slowdown); terminal handling differs (~+3%);
MTA operating time may include layover; August 2021 covers only the 16th onward
(W1 starts mid-month); SBS route ids differ ('M15+' here vs 'M15' + trip_type
SBS there) so SBS rows join only in the cudb trip_type mapping, not by raw id.

## A. W2 route x day-of-week x hour vs 58t6-89vi

- n=43769  mean=0.853  p10=0.735  p25=0.807  p50=0.864  p75=0.906  p90=0.941
- Spearman rank agreement across 340 routes (>= 20 matched hours): 0.952

## B. route x month x day_type vs cudb-vcni (both windows)

- n=2914  mean=0.858  p10=0.778  p25=0.825  p50=0.871  p75=0.902  p90=0.925
- Spearman rank agreement across 333 routes: 0.969

No gate is set on this run (calibration, spec I): a candidate future gate is a
ratio band [0.75, 1.15] plus rank agreement, decided after this first month.
