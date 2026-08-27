# The MTA realtime redistribution gate is open: the terms authorize the non-MTA-server shape

`publish.LIVE_TERMS_VERIFIED` was `None` because nobody had read MTA's actual terms
(cloud 09: "The spec does not assert what they say"). On 2026-08-27, at Ross's direction,
the MTA Developer Agreement for Access to Data Feeds
(mta.info/developers/terms-and-conditions — the URL MTA's own `nymta/gtfs-documentation`
repo names canonical) was read in full from an archived capture, cross-checked against two
independent captures. The operative clauses:

- **The grant is redistribution-shaped, and it is mandatory, not merely permitted:**
  "This agreement authorizes the developer to download and host the data on the
  developer's or a third party's server and to make the data available to others who will
  access the server provided by the developer." and "you will provide that the MTA data
  feed is available to others only from a non-MTA server." Serving derived views from our
  own bucket is the compliant shape; proxying MTA's servers is the prohibited one.
- **Realtime is covered by the same grant**, with one extra duty: "When using MTA
  Real-Time data feeds, if there is a lag time of more than 1 minute ... you will also
  indicate the information provided by your app to the end-user may not be real time."
  The page already satisfies this structurally: every payload's age is reader-dated from
  response headers and displayed, with STALE at 120 s for the live pair.
- **Conditions, all already enforced here:** no implied MTA endorsement (we state data is
  "derived from" MTA feeds, served from our server); no accuracy/timeliness claims
  (`strings.caveats` everywhere); no modification/deletion misrepresented as MTA data (a
  subset/derived view is expressly allowed: "You may, however, create an App that uses
  some but not all of the data"); no MTA logos, roundels or line colours (frozen rule in
  the read-API contract). Nothing conditions the grant on non-commercial use.
- MTA reserves at-will termination and provides the data as-is — accepted; the gate
  constant makes the surface revocable in one line if MTA ever objects.

The three structural constraints from cloud 09 hold unchanged either way: current
snapshot only (literal keys, no versioning), no bulk/protobuf endpoint (suffix
allowlist), attribution on the page. Full captured text:
`~/vault/raincheck-runbook/mta-terms-2026-08-27.txt`.

Status: accepted
