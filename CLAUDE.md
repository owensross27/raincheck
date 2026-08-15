# raincheck

NYC bus GTFS-RT x rain: Kafka -> Spark/Sedona -> GeoParquet. Plan lives on the
wayfinder map at `.scratch/pipeline/map.md`; feed facts in
`~/vault/nyc-mta-bus-feeds-reference.md`. Wayfinder is plan-only: build work goes
through `/to-spec` -> `/to-tickets` -> `/implement` in their own sessions.

## Agent skills

### Issue tracker

Local markdown under `.scratch/<effort>/`, no remote. See `docs/agents/issue-tracker.md`.

### Triage labels

Default five-role vocabulary, label strings equal to role names. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: `CONTEXT.md` at root plus `docs/adr/`, created lazily. See `docs/agents/domain.md`.
