# 03 Zarr to Spark/Sedona bridge

Type: research
Status: claimed

## Question

Sedona 1.9.1 does not (believed, confirm) read Zarr natively. What is the practical
bridge on Spark 3.5.3 local mode: xarray-select-to-DataFrame vector join, hourly COG
GeoTIFF + RS_ZonalStats, kerchunk/VirtualiZarr, or something else? Also: which raster
capabilities are OSS Sedona vs WherobotsDB-only (portfolio-relevant), and the robust
Structured Streaming pattern for enriching a Kafka point stream with a slowly-changing
hourly precip grid (broadcast lookup vs stream-static join).
