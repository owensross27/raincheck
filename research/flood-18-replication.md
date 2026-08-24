# flood-18 — the 311-threshold and label-radius outer replication

Read against the frozen primary: `fits_version` **8050dfa41fc1** over
`matrix_version` **8bc1e8912b1b** — point CSI **0.0310**,
cell CSI **0.1591**, location-blocked and out of fold.
Estimand: **flooded_reported**.

Two knobs decide which (Unit, event) pairs are POSITIVE and both sit UPSTREAM of
`gold/flood_matrix`, so neither can be swept in fold — moving either redefines the event
universe, which is why ticket 09 routed both here. Each alternate universe is a full rebuild
of 04 -> 05 -> 06 -> 08 -> 09 through the same jobs, parameterized, onto its own data root.
The primary's bytes and its three chained identities are hashed before and after
(receipt below); the alternates' stamps are ASSERTED distinct rather than assumed.

## THE DELTA TABLE — location_blocked, out of fold

| universe | knob | setting | point CSI | vs primary | cell CSI | vs primary | gate |
|---|---|---|---|---|---|---|---|
| **primary** | - | 311 q0.99 = 97/85 | 0.0310 | - | 0.1591 | - | MODEL |
| **q9750** | 311_threshold | 311 q0.975 = 59/45 | 0.0300 | -0.0010 | 0.1523 | -0.0068 | MODEL |
| **q9950** | 311_threshold | 311 q0.995 = 126/153 | 0.0312 | +0.0002 | 0.1633 | +0.0041 | MODEL |
| **r050** | label_radius | radius 50 m | 0.0237 | -0.0073 | 0.1591 | +0.0000 | MODEL |
| **r200** | label_radius | radius 200 m | 0.0667 | +0.0357 | 0.1591 | +0.0000 | MODEL |

The same table at the primary reporting split, `event_grouped`, published beside it
because a number quoted only under `location_blocked` has been read at the split where the
unit-climatology baseline cannot compete — every held-out Unit's whole history sits in the
held-out fold, so B2 degenerates to the base rate BY CONSTRUCTION (flood 09's measurement,
and its trap):

| universe | point CSI | vs primary | cell CSI | vs primary |
|---|---|---|---|---|
| **primary** | 0.0286 | - | 0.1516 | - |
| **q9750** | 0.0286 | +0.0000 | 0.1487 | -0.0029 |
| **q9950** | 0.0301 | +0.0015 | 0.1597 | +0.0081 |
| **r050** | 0.0234 | -0.0052 | 0.1516 | +0.0000 |
| **r200** | 0.0605 | +0.0318 | 0.1516 | +0.0000 |

## WHAT MOVED UNDER THE CSI — base rates and realized alert rates

**A CSI difference across these rows is partly a difference of base rates.** CSI and POD are
monotone in alert rate at a base rate this low, and every knob here moves the base rate BY
CONSTRUCTION — lowering the 311 cut mints events (and therefore negatives), widening the
radius mints positives. That is not a caveat about this table; it is what the table is FOR,
and it is why the base rate and the realized alert rate print on every line rather than the
CSI alone.

| universe | role | rows | positives | base rate | vs primary | alert rate | POD | FAR | PR-AUC | CSI 95% CI |
|---|---|---|---|---|---|---|---|---|---|---|
| **primary** | point | 783,351 | 4,008 | 0.00512 | - | 0.01108 | 0.095 | 0.956 | 0.0231 | 0.017-0.038 |
|  | cell | 179,683 | 6,554 | 0.03648 | - | 0.05664 | 0.350 | 0.774 | 0.2030 | 0.117-0.203 |
| **q9750** | point | 994,786 | 5,022 | 0.00505 | -0.00007 | 0.01350 | 0.107 | 0.960 | 0.0210 | 0.018-0.036 |
|  | cell | 225,617 | 8,547 | 0.03788 | +0.00141 | 0.05320 | 0.318 | 0.774 | 0.1963 | 0.117-0.188 |
| **q9950** | point | 731,222 | 3,612 | 0.00494 | -0.00018 | 0.01370 | 0.114 | 0.959 | 0.0241 | 0.020-0.040 |
|  | cell | 168,875 | 5,824 | 0.03449 | -0.00199 | 0.04609 | 0.328 | 0.755 | 0.2111 | 0.115-0.205 |
| **r050** | point | 783,351 | 1,668 | 0.00213 | -0.00299 | 0.00399 | 0.067 | 0.964 | 0.0102 | 0.010-0.035 |
|  | cell | 179,683 | 6,554 | 0.03648 | +0.00000 | 0.05664 | 0.350 | 0.774 | 0.2030 | 0.117-0.203 |
| **r200** | point | 783,351 | 11,818 | 0.01509 | +0.00997 | 0.04664 | 0.256 | 0.917 | 0.0642 | 0.031-0.083 |
|  | cell | 179,683 | 6,554 | 0.03648 | +0.00000 | 0.05664 | 0.350 | 0.774 | 0.2030 | 0.117-0.203 |

## READ THE LIFT, NOT THE RAW CSI — the sweep's actual finding

Divide each universe's model CSI by its OWN B0 and the ranking above **reverses**:

| universe | setting | point CSI | point lift over B0 | cell CSI | cell lift over B0 |
|---|---|---|---|---|---|
| **primary** | 311 q0.99 = 97/85 | 0.0310 | 6.05x | 0.1591 | 4.36x |
| **q9750** | 311 q0.975 = 59/45 | 0.0300 | 5.94x | 0.1523 | 4.02x |
| **q9950** | 311 q0.995 = 126/153 | 0.0312 | 6.31x | 0.1633 | 4.73x |
| **r050** | radius 50 m | 0.0237 | 11.13x | 0.1591 | 4.36x |
| **r200** | radius 200 m | 0.0667 | 4.42x | 0.1591 | 4.36x |

**The widest radius has the HIGHEST raw point CSI and the LOWEST skill.** Reading the raw
column alone says "widen the label radius and the point model gets twice as good"; the lift
column says the opposite, and the lift column is the one that is not measuring the base
rate. 200 m nearly triples the point base rate (0.00512 -> 0.01509) because a 200 m circle
around a doorway catches 311 reports from the next street; 50 m starves it (4,008 positives
-> 1,668) and the surviving positives are the ones sitting almost on top of a report, which
is why its lift is highest and its raw CSI lowest. **The knob is moving what "flooded" MEANS
at point grain, not how well the model finds it** — the honest reading of both columns
together, and the reason the primary's 100 m is not re-litigated by this table.

The 311 threshold is the mild knob by comparison: +-2.5 percentiles of the daily-count
distribution moves the point lift 5.94x-6.31x against the primary's 6.05x, and the raw point
CSI by at most 0.0010. **The headline is robust to the threshold and sensitive to the
radius**, which is the sentence this replication existed to be able to say.

## THE RADIUS IS STRUCTURALLY INERT AT CELL GRAIN — and the numbers prove the rebuild was real

Both radius universes reproduce the primary's cell CSI to four decimals (0.1591) and its cell
base rate exactly. That is not a copied number: `flood_labels`' cell branch attaches on
`a.cell = oe.cell`, with no distance predicate, so moving `RADIUS_M` cannot touch a Cell
label — and the `fit_cell` rows of both alternate matrices are BYTE-IDENTICAL to the
primary's (same 179,683 rows, same sha256 over the sorted rows minus the stamp column), while
their `fit_point` positives move 4,008 -> 1,668 (50 m) and -> 11,818 (200 m). The fits were
re-run independently, off a differently-stamped matrix, and landed on the same cell numbers.
An invariance that holds through a full independent rebuild is evidence the rebuild is real;
had the cell numbers MOVED, the sweep would have been reporting noise.

## THE COMPLEX-GRAIN VALIDATION SET

A complex is never fitted: it is alert-only by construction, and its score is the max over
its child entrances' out-of-fold scores. So the two knobs reach it differently, and the
numbers say which — the label RADIUS cannot move a complex positive at all (an alert
attaches by the source-id grammar, not by distance), while the 311 threshold moves the event
set under it. Published because flood 09 publishes it, and read as validation, never as a
skill claim about complexes.

| universe | setting | pairs | positives | CSI | POD | FAR | alert rate |
|---|---|---|---|---|---|---|---|
| **primary** | 311 q0.99 = 97/85 | 43,089 | 118 | 0.0025 | 0.008 | 0.996 | 0.00652 |
| **q9750** | 311 q0.975 = 59/45 | 52,870 | 118 | 0.0060 | 0.034 | 0.993 | 0.01054 |
| **q9950** | 311 q0.995 = 126/153 | 40,869 | 118 | 0.0045 | 0.017 | 0.994 | 0.00815 |
| **r050** | radius 50 m | 43,089 | 118 | 0.0034 | 0.008 | 0.994 | 0.00404 |
| **r200** | radius 200 m | 43,089 | 118 | 0.0104 | 0.093 | 0.988 | 0.02214 |

## THE EVENT UNIVERSES

| universe | setting | events | pluvial fit-era | label positives | matrix rows | AORC Cell-months | months this run built |
|---|---|---|---|---|---|---|---|
| **primary** | 311 q0.99 = 97/85 | 206 | 133 | 24,542 | 1,006,123 | 124 | 0 |
| **q9750** | 311 q0.975 = 59/45 | 243 | 167 | 29,598 | 1,273,273 | 140 | 16 |
| **q9950** | 311 q0.995 = 126/153 | 196 | 125 | 22,217 | 940,966 | 120 | 0 |
| **r050** | radius 50 m | 206 | 133 | 17,410 | 1,006,123 | 124 | 0 |
| **r200** | radius 200 m | 206 | 133 | 47,837 | 1,006,123 | 124 | 0 |

Ticket 06's coverage check ran on every universe's OWN Windows — the month list is derived by
`precip_flood_era.window_months`, never typed, and `assert_window_coverage` is what let the
loosened universe run at all: it needs AORC Cell-months the primary never built, and those
had to land in the ALTERNATE root. Writing them under the primary would change
`precip_identity()` — the SET of built Cell-month partitions — and stop
`matrix_version 8bc1e8912b1b` from ever reproducing, without moving one byte of
the frozen table.

## THE STAMPS ARE DISTINCT — asserted, not assumed

| stamp | primary | q9750 | q9950 | r050 | r200 |
|---|---|---|---|---|---|
| `matrix_version` | 8bc1e8912b1b | f7876c48a920 | 56b1b4abf618 | 444d22395e31 | 0fdafeefee4b |
| `fits_version` | 8050dfa41fc1 | 71e16bbe7f4d | 64843960b241 | 34584debc418 | d37619ebe9c4 |
| `label_version` | 46bbfd665b78 | 9e86c0388dae | fbee9687c7cd | 7bd02f3088ba | 3ceea34b6dbd |
| `spine_version` | e7fcdf563d3e | 583ebe26131d | e493092cc9a4 | e7fcdf563d3e | e7fcdf563d3e |

`matrix_version` chains label + features + precip identities and `label_version` chains the
spine, so an alternate universe stamps differently by construction — this is the check that
the construction held, and it fails the build rather than publishing the primary back to
itself. `spine_version` is EXEMPT and collides on purpose for the radius universes: the
event list did not move there, and re-deriving it would inject a difference the sweep is not
measuring.

## THE PRIMARY IS UNTOUCHED — the receipt

| checked | value |
|---|---|
| artifact files hashed (sha256), before and after | 6 |
| files whose bytes moved | **none** |
| `assets_version` | `d3c7b0f371a4` |
| `features_version` | `6b6f61e0231d` |
| `label_version` | `46bbfd665b78` |
| `label_version_recomputed` | `46bbfd665b78` |
| `matrix_version` | `8bc1e8912b1b` |
| `matrix_version_recomputed` | `8bc1e8912b1b` |
| `precip_identity` | `2fddec3aa780` |
| `spine_version` | `e7fcdf563d3e` |

Hashing the artifacts alone would not have been enough. What the primary's stamps consume is
`assets_version`, `features_version` and `precip_identity`, and a new AORC month under the
primary root moves the third without touching an artifact byte — so the receipt recomputes
all three, and re-derives `label_version` and `matrix_version` from them.

## LIMITS

- `precip_identity()` names the built AORC Cell-month partition SET, not the pixel bytes: a
  month silently rewritten under the same name does not move the stamp. Recorded by flood
  08, restated here, NOT fixed — it is one hole in the receipt above.
- **The same shape, one level up, and MEASURED here: `spine_version` hashes the THRESHOLDS
  AND THE RULES, never the derived event list.** An early staging of this ticket linked the
  inputs it thought a universe needed and missed `archive/subway_alerts`; the alternate
  spine lost an alert-triggered event and `spine_version`, `label_version` and
  `matrix_version` were all IDENTICAL to the corrected run's. A stamp in this chain names
  what the build declared, not what it read — so it cannot catch an input tree that went
  missing, and the defence is the staging walk (discover the inputs, never enumerate them),
  not the digest.
- The thresholds are asked for as QUANTILES and returned by `flood_spine.remeasure_311`;
  no count is typed by hand. A hand-typed cut is a cut somebody chose, and the point of an
  outer replication is that nobody chose it.
- Every universe rebuilds the spine, labels, coverage check and matrix from the same
  snapshots as the primary (`asof 2026-08-23`), so nothing here is measuring source drift.
- These are OUT-OF-FOLD numbers under a re-derived universe, not held-out replication of the
  primary's fit: each universe picks its own lambda and its own in-fold operating point, as
  the primary did.
