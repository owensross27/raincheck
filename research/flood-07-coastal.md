# flood-07 coastal rule layer — surge_margin_ft

Stage frozen once: `nws_minor`. Margin = elevation(NAVD88 ft) - the assigned gauge's minor stage(NAVD88 ft).

| gauge | station | minor, ft STND | NAVD88 offset, ft | minor, ft NAVD88 |
|---|---|---|---|---|
| 8518750 | The Battery | 10.49 | 6.06 | **4.43** |
| 8516945 | Kings Point | 22.89 | 17.09 | **5.8** |
| 8531680 | Sandy Hook | 9.21 | 5.33 | **3.88** |

## Datum sanity

Entrances below the Battery's minor stage: **3** under NAVD88 discipline, **103** if the published STND number is compared straight against a NAVD88 elevation.

## Units by assigned gauge

| gauge | complex | bus_stop | cell | negative margin | no elevation |
|---|---|---|---|---|---|
| The Battery | 312 | 8062 | 632 | 8 | 138 |
| Kings Point | 112 | 4440 | 536 | 21 | 189 |
| Sandy Hook | 21 | 868 | 183 | 5 | 77 |

Units with no margin at all: 0 complex, 60 bus_stop, 344 cell — Cells with no point child inside them (scored via a taxi Zone, not an asset) and the bus stops whose 2017 sample and 15 m ring are both NoData. Ticket 10 prices these as NULL surge_margin_ft; they are not zeros.

## The ten lowest margins

| unit | name | kind | gauge | elev, ft NAVD88 | surge_margin_ft | support |
|---|---|---|---|---|---|---|
| `cell:882a107289fffff` | - | cell | The Battery | -34.08 | **-38.515** | 153 |
| `stn:328` | WTC Cortlandt | complex | The Battery | -34.08 | **-38.515** | 9 |
| `bus:801205` | gowanus expwy/woodhull st | bus_stop | The Battery | -4.23 | **-8.66** | 1 |
| `cell:882a107297fffff` | - | cell | The Battery | -4.23 | **-8.66** | 12 |
| `bus:307975` | STILLWELL AV/NEPTUNE AV | bus_stop | Sandy Hook | -1.94 | **-5.816** | 1 |
| `cell:882a107439fffff` | - | cell | Sandy Hook | -1.94 | **-5.816** | 7 |
| `bus:903254` | EAST TREMONT AV/E 177 ST | bus_stop | Kings Point | 1.78 | **-4.016** | 1 |
| `cell:882a100ad9fffff` | - | cell | Kings Point | 1.78 | **-4.016** | 31 |
| `bus:104003` | EAST TREMONT AV/E 177 ST | bus_stop | Kings Point | 2.45 | **-3.346** | 1 |
| `bus:552158` | VERNON BLVD/31 AV | bus_stop | The Battery | 1.26 | **-3.17** | 1 |

The deepest row is a KNOWN DEM ARTIFACT, not a doorway: WTC Cortlandt (`stn:328`) was an open construction pit when the 2017 raster was flown and the station did not reopen until 2018, so its 15 m ring is inside the pit too and the QC fallback cannot rescue it. `grade_ok` already marks those entrances false — this layer publishes the raw consequence rather than repairing it silently, and any consumer that ranks on the margin should filter on `grade_ok` the same way the fits do.

## Sandy inundation against the margin (descriptive)

| surge_margin_ft | units | inside the Sandy polygon | share |
|---|---|---|---|
| < 0 | 34 | 24 | 0.7059 |
| [0, 5) | 1107 | 959 | 0.8663 |
| [5, 10) | 1454 | 405 | 0.2785 |
| [10, 20) | 2191 | 6 | 0.0027 |
| [20, 1e+09) | 9976 | 5 | 0.0005 |

