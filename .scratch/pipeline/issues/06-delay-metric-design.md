# 06 Delay metric design

Type: grilling
Status: open
Blocked by: 01

## Question

Define "late" precisely. delay_seconds = TU arrival.time minus scheduled arrival from
the static GTFS in effect on that service date (settled). Open: which arrival.time
snapshot counts (last prediction before actual arrival vs prediction at fixed horizon,
prediction churn is itself signal); how actual arrival is inferred from VP stop_id
transitions vs trusting TU; headway-based lateness for high-frequency routes where
schedule adherence is meaningless (bunching); and the service-date boundary (MTA
service days run past midnight, trips reference the prior service date via the
EN_/EX_ trip_id prefix conventions). Ross picks the metric family, evidence from a
week of archived data.
