"""Prove the climate-Zarr rail: read NOAA AORC 1km hourly precipitation straight
from S3 (anonymous) and reproduce Hurricane Ida's record NYC rainfall.

Central Park measured ~80 mm (3.15 in) in the hour ending 2021-09-02 00:51 UTC.
A 1km reanalysis cell will not match a gauge exactly; >= 25 mm/h qualifies as
"found the event". Run: python -m raincheck.zarr_probe
"""
import xarray as xr

STORE = "s3://noaa-nws-aorc-v1-1-1km/2021.zarr"
CENTRAL_PARK = (40.782, -73.965)
WINDOW = slice("2021-09-01T12:00", "2021-09-02T12:00")


def ida_peak() -> tuple[str, float]:
    ds = xr.open_zarr(STORE, storage_options={"anon": True}, consolidated=True)
    lat, lon = CENTRAL_PARK
    lons = ds["longitude"]
    if float(lons.max()) > 180:  # 0-360 domain
        lon = 360 + lon
    cell = ds["APCP_surface"].sel(latitude=lat, longitude=lon, method="nearest")
    series = cell.sel(time=WINDOW).compute()
    peak = series.idxmax("time").values
    return str(peak), float(series.max())


def main() -> None:
    peak_time, peak_mm = ida_peak()
    print(f"AORC {STORE}")
    print(f"Ida peak at Central Park cell: {peak_mm:.1f} mm/h at {peak_time}")
    assert peak_mm >= 25, f"expected a record-rain signal, got {peak_mm:.1f} mm/h"
    print("PASS: Zarr rail verified against a known storm")


if __name__ == "__main__":
    main()
