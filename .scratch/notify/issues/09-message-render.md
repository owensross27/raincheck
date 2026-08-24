# 09 — Message render and the fixed strings

**What to build:** A decided Message becomes an email a person can read, act on and leave —
one that states the hour-grain evidence behind it and claims nothing the panel does not
claim. Spec: section 7 (message content, claim strings); SEAM N.

**Blocked by:** 01, 08 — externally on flood-build 15 (the fixed-string list and constants
artifact).

**Status:** ready-for-agent

- [ ] rendering a Message produces: the Unit's name and kind, the tier entered, the Window, the hour-grain evidence sentence, the estimand sentence, a link to the panel, and the unsubscribe instruction
- [ ] F15's fixed strings are reused verbatim — the reporting-propensity sentence, the estimand name `flooded_reported`, the Window in the tier label, the degraded-state strings, and the B2-branch alternates selected by the shipped model id; the message gets no vocabulary of its own
- [ ] ticket 01's replacement string is used where the retired one would have gone, and the retired string appears NOWHERE in the rendered corpus (asserted by absence)
- [ ] the message states its evidence window in hours and never implies second-scale urgency; the ~1-2 min end-to-end figure belongs to the bus live chain and appears nowhere
- [ ] the message never claims water was observed — it ranks where a flood REPORT is likely
- [ ] every message carries the subscriber's opaque unsubscribe token in a `List-Unsubscribe` mailto header AND in the body, and states the processing expectation honestly rather than implying instant one-click removal
- [ ] render is a pure function of the Message: same Message, same bytes
