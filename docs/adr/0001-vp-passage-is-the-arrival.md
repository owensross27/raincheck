# The arrival is the VehiclePosition passage, not the TripUpdate prediction

MTA TripUpdates carry only predicted arrival epochs (never `delay`), and the
2017-2024 nycbuspositions archive holds no stop-level TripUpdate rows at all, so
a TripUpdate-based arrival would make history and live two different metrics.
We measured that VehiclePosition `stop_id` is the next stop (94.9% of pings sit
between the previous stop and it) and that a stop_id flip brackets the passage of
the stop within one poll interval, agreeing with the last TripUpdate prediction
to within 60 s on 88% of events. So the arrival is the flip midpoint per
(vehicle, trip, service date), on both the archive and the live feed; TripUpdates
are stored as a prediction stream (churn features, flagged fallback), never as
the arrival. Decided 2026-08-16 in wayfinder ticket 06.

Status: accepted
