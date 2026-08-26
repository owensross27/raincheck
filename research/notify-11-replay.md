# notify 11 — what a real storm would have sent

The SAME `notify_decide.decide` the live loop calls, replayed over flood 12's replayable subset. Evidence for a human; the volume numbers are not assertions.

**BRANCH EXERCISED: `watch`** — read at replay time from `notify_decide.branch(flood_detect.constants())`, never typed. Selected by research/flood-11-detector.json cutpoints.provisional is True. The `tier` branch is replayed beside it as a labelled counterfactual: a rank-only run and a tier run are not comparable volumes, and which one v1 ships is the open [YOU] decision flood 12 measured and recommended on — so the branch the artifact selects is THE run and the other is published beside it, labelled.

- detector `01197991471f` · score `dda793c2c8c7` · table stamp `dda793c2c8c7` · skew `ok`
- subset READ from `research/flood-12-replay.json`: **133 events** of 195 AORC-era (62 walk-only), **4,326 hourly cycles** (76 INSUFFICIENT_DATA, 4,250 OK), 1 event with no OK cycle. **133 events replayed here over 15.33 years**.
- policy in force: watch cut `{'bus_stop': 25, 'complex': 5}` · per-cycle fuse **25** · per-handle cap **10** · quiet hours [22, 7] America/New_York · own-Cell gate 2.0 mm.
- **the fuse and the ingress trigger are the same number (25): `True`.**

## The lists

- **`post_ingress`** — 60 subscriptions over 6 handles (10 each, cap 10), {'bus_stop': 50, 'complex': 10}; past the ingress trigger: **True**. Published `worst_case` **60** against a reachable max of **60** per cycle. Assets: the most-flooded Units in gold/flood_matrix (ties on asset_id) — what a person subscribes to, and orthogonal to what the live rank ranks.
- **`top_scored`** — 60 subscriptions over 6 handles (10 each, cap 10), {'bus_stop': 50, 'complex': 10}; past the ingress trigger: **True**. Published `worst_case` **60** against a reachable max of **60** per cycle. Assets: the highest static score_index in gold/flood_exposure (ties on asset_id) — the adversarial list, the Units the live rank is most likely to put on top.
- **`v1_list`** — 25 subscriptions over 5 handles (5 each, cap 10), {'bus_stop': 21, 'complex': 4}; past the ingress trigger: **False**. Published `worst_case` **50** against a reachable max of **25** per cycle. Assets: the most-flooded Units in gold/flood_matrix (ties on asset_id) — what a person subscribes to, and orthogonal to what the live rank ranks.

## Volume

| chain | events that sent | messages | by kind | by tier | drops | dropped |
| --- | ---: | ---: | --- | --- | ---: | --- |
| `post_ingress/tier` | 68/133 | 836 | {'bus_stop': 712, 'complex': 124} | {'ELEVATED': 272, 'HIGH': 564} | 241 | {'quiet_hours': 241} |
| `post_ingress/watch` **(live)** | 34/133 | 100 | {'bus_stop': 72, 'complex': 28} | {'None': 100} | 46 | {'quiet_hours': 46} |
| `top_scored/tier` | 70/133 | 1,712 | {'bus_stop': 1269, 'complex': 443} | {'ELEVATED': 185, 'HIGH': 1527} | 748 | {'cycle_fuse': 566, 'handle_cap': 69, 'quiet_hours': 113} |
| `top_scored/watch` **(live)** | 56/133 | 749 | {'bus_stop': 495, 'complex': 254} | {'None': 749} | 620 | {'cycle_fuse': 2, 'quiet_hours': 618} |
| `v1_list/tier` | 56/133 | 406 | {'bus_stop': 349, 'complex': 57} | {'ELEVATED': 112, 'HIGH': 294} | 82 | {'quiet_hours': 82} |
| `v1_list/watch` **(live)** | 23/133 | 61 | {'bus_stop': 51, 'complex': 10} | {'None': 61} | 31 | {'quiet_hours': 31} |

| chain | peak event | peak cycle sent | peak cycle wanted | worst_case | events over the fuse | events the fuse clipped | multi-Window events | per subscription per year |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `post_ingress/tier` | 43 | 25 | 26 | 60 | 2 | 0 | 0 | {'bus_stop': 0.929, 'complex': 0.809} |
| `post_ingress/watch` | 8 | 7 | 7 | 60 | 0 | 0 | 0 | {'bus_stop': 0.094, 'complex': 0.183} |
| `top_scored/tier` | 60 | 25 | 60 | 60 | 29 | 29 | 19 | {'bus_stop': 1.656, 'complex': 2.89} |
| `top_scored/watch` | 51 | 25 | 28 | 60 | 5 | 1 | 0 | {'bus_stop': 0.646, 'complex': 1.657} |
| `v1_list/tier` | 20 | 12 | 12 | 50 | 0 | 0 | 0 | {'bus_stop': 1.084, 'complex': 0.93} |
| `v1_list/watch` | 6 | 5 | 5 | 50 | 0 | 0 | 0 | {'bus_stop': 0.158, 'complex': 0.163} |

on the watch branch `Message.tier` is None, so no message is HIGH and the quiet-hours rule applies to EVERY one of them; `elevated_optin` is read on the tier branch only.

## Silent cycles, and why

| chain | version_skew | winter_gate | insufficient_data | window_capped |
| --- | ---: | ---: | ---: | ---: |
| `post_ingress/tier` | 0 | 267 | 76 | 0 |
| `post_ingress/watch` | 0 | 267 | 76 | 0 |
| `top_scored/tier` | 0 | 267 | 76 | 0 |
| `top_scored/watch` | 0 | 267 | 76 | 0 |
| `v1_list/tier` | 0 | 267 | 76 | 0 |
| `v1_list/watch` | 0 | 267 | 76 | 0 |

## Over expectation — never silently absorbed

- **cycle_owed_more_than_the_fuse_allows** — a cycle OWES at most per_cycle_fuse = 25 messages. Breaking it means: more subscriptions landed on entering Units in one cycle than the deferred-ingress list is allowed to hold. Read `fuse_dropped` on the row: nonzero is the fuse clipping, zero is a cycle whose volume the quiet-hours or per-handle rule shed before the fuse was consulted.
- **more_than_one_message_per_subscription** — an event owes at most one message per subscription. Breaking it means: read the row's `windows`: >1 is a Window that ROLLED mid-event (the city dried and the storm came back) and ==1 on the tier branch is an ESCALATION, a Unit that entered at ELEVATED and came back at HIGH. Neither is a duplicate, and only the first can happen on the watch branch — a rank has no tiers to escalate through.

**55 rows.**

| event | chain | rule | detail |
| --- | --- | --- | --- |
| 2021-09-24 | `post_ingress/tier` | cycle_owed_more_than_the_fuse_allows | {'allowed': 25, 'fuse_dropped': 0, 'wanted': 26} |
| 2023-01-26 | `post_ingress/tier` | cycle_owed_more_than_the_fuse_allows | {'allowed': 25, 'fuse_dropped': 0, 'wanted': 26} |
| 2020-03-04 | `top_scored/tier` | cycle_owed_more_than_the_fuse_allows | {'allowed': 25, 'fuse_dropped': 33, 'wanted': 59} |
| 2020-07-10 | `top_scored/tier` | cycle_owed_more_than_the_fuse_allows | {'allowed': 25, 'fuse_dropped': 12, 'wanted': 37} |
| 2020-11-30 | `top_scored/tier` | cycle_owed_more_than_the_fuse_allows | {'allowed': 25, 'fuse_dropped': 25, 'wanted': 50} |
| 2020-11-30 | `top_scored/tier` | more_than_one_message_per_subscription | {'owed': 62, 'subscriptions': 60, 'windows': 1} |
| 2021-06-04 | `top_scored/tier` | cycle_owed_more_than_the_fuse_allows | {'allowed': 25, 'fuse_dropped': 33, 'wanted': 59} |
| 2021-06-08 | `top_scored/tier` | cycle_owed_more_than_the_fuse_allows | {'allowed': 25, 'fuse_dropped': 26, 'wanted': 51} |
| 2021-07-02 | `top_scored/tier` | cycle_owed_more_than_the_fuse_allows | {'allowed': 25, 'fuse_dropped': 33, 'wanted': 59} |
| 2021-07-08 | `top_scored/tier` | cycle_owed_more_than_the_fuse_allows | {'allowed': 25, 'fuse_dropped': 3, 'wanted': 28} |
| 2021-07-08 | `top_scored/tier` | more_than_one_message_per_subscription | {'owed': 74, 'subscriptions': 60, 'windows': 1} |
| 2021-07-12 | `top_scored/tier` | cycle_owed_more_than_the_fuse_allows | {'allowed': 25, 'fuse_dropped': 11, 'wanted': 37} |
| 2021-08-21 | `top_scored/tier` | cycle_owed_more_than_the_fuse_allows | {'allowed': 25, 'fuse_dropped': 15, 'wanted': 40} |
| 2021-08-21 | `top_scored/tier` | more_than_one_message_per_subscription | {'owed': 97, 'subscriptions': 60, 'windows': 2} |
| 2021-08-27 | `top_scored/tier` | cycle_owed_more_than_the_fuse_allows | {'allowed': 25, 'fuse_dropped': 7, 'wanted': 34} |
| 2021-08-27 | `top_scored/tier` | more_than_one_message_per_subscription | {'owed': 67, 'subscriptions': 60, 'windows': 1} |
| 2021-09-01 | `top_scored/tier` | cycle_owed_more_than_the_fuse_allows | {'allowed': 25, 'fuse_dropped': 16, 'wanted': 41} |
| 2021-09-24 | `top_scored/tier` | cycle_owed_more_than_the_fuse_allows | {'allowed': 25, 'fuse_dropped': 32, 'wanted': 59} |
| 2021-10-26 | `top_scored/tier` | cycle_owed_more_than_the_fuse_allows | {'allowed': 25, 'fuse_dropped': 13, 'wanted': 38} |
| 2022-09-13 | `top_scored/tier` | cycle_owed_more_than_the_fuse_allows | {'allowed': 25, 'fuse_dropped': 1, 'wanted': 28} |
| 2022-09-13 | `top_scored/tier` | more_than_one_message_per_subscription | {'owed': 63, 'subscriptions': 60, 'windows': 2} |
| 2023-01-26 | `top_scored/tier` | cycle_owed_more_than_the_fuse_allows | {'allowed': 25, 'fuse_dropped': 34, 'wanted': 60} |
| 2023-01-26 | `top_scored/tier` | more_than_one_message_per_subscription | {'owed': 61, 'subscriptions': 60, 'windows': 2} |
| 2023-04-30 | `top_scored/tier` | cycle_owed_more_than_the_fuse_allows | {'allowed': 25, 'fuse_dropped': 35, 'wanted': 60} |
| 2023-07-16 | `top_scored/tier` | cycle_owed_more_than_the_fuse_allows | {'allowed': 25, 'fuse_dropped': 24, 'wanted': 57} |
| 2023-07-16 | `top_scored/tier` | more_than_one_message_per_subscription | {'owed': 71, 'subscriptions': 60, 'windows': 1} |
| 2023-09-11 | `top_scored/tier` | cycle_owed_more_than_the_fuse_allows | {'allowed': 25, 'fuse_dropped': 34, 'wanted': 60} |
| 2023-09-11 | `top_scored/tier` | more_than_one_message_per_subscription | {'owed': 61, 'subscriptions': 60, 'windows': 1} |
| 2023-09-18 | `top_scored/tier` | cycle_owed_more_than_the_fuse_allows | {'allowed': 25, 'fuse_dropped': 14, 'wanted': 39} |
| 2023-09-18 | `top_scored/tier` | more_than_one_message_per_subscription | {'owed': 62, 'subscriptions': 60, 'windows': 1} |
| 2023-09-29 | `top_scored/tier` | cycle_owed_more_than_the_fuse_allows | {'allowed': 25, 'fuse_dropped': 21, 'wanted': 48} |
| 2023-09-29 | `top_scored/tier` | more_than_one_message_per_subscription | {'owed': 71, 'subscriptions': 60, 'windows': 1} |
| 2023-12-02 | `top_scored/tier` | cycle_owed_more_than_the_fuse_allows | {'allowed': 25, 'fuse_dropped': 34, 'wanted': 60} |
| 2024-03-06 | `top_scored/tier` | cycle_owed_more_than_the_fuse_allows | {'allowed': 25, 'fuse_dropped': 12, 'wanted': 37} |
| 2024-03-06 | `top_scored/tier` | more_than_one_message_per_subscription | {'owed': 62, 'subscriptions': 60, 'windows': 1} |
| 2024-03-23 | `top_scored/tier` | cycle_owed_more_than_the_fuse_allows | {'allowed': 25, 'fuse_dropped': 9, 'wanted': 32} |
| 2024-03-23 | `top_scored/tier` | more_than_one_message_per_subscription | {'owed': 61, 'subscriptions': 60, 'windows': 2} |
| 2024-08-06 | `top_scored/tier` | more_than_one_message_per_subscription | {'owed': 73, 'subscriptions': 60, 'windows': 1} |
| 2024-08-19 | `top_scored/tier` | cycle_owed_more_than_the_fuse_allows | {'allowed': 25, 'fuse_dropped': 9, 'wanted': 56} |
| 2024-08-19 | `top_scored/tier` | more_than_one_message_per_subscription | {'owed': 69, 'subscriptions': 60, 'windows': 1} |
| 2025-07-08 | `top_scored/tier` | cycle_owed_more_than_the_fuse_allows | {'allowed': 25, 'fuse_dropped': 8, 'wanted': 31} |
| 2025-07-14 | `top_scored/tier` | more_than_one_message_per_subscription | {'owed': 83, 'subscriptions': 60, 'windows': 2} |
| 2025-07-31 | `top_scored/tier` | cycle_owed_more_than_the_fuse_allows | {'allowed': 25, 'fuse_dropped': 7, 'wanted': 32} |
| 2025-07-31 | `top_scored/tier` | more_than_one_message_per_subscription | {'owed': 72, 'subscriptions': 60, 'windows': 1} |
| 2025-08-13 | `top_scored/tier` | cycle_owed_more_than_the_fuse_allows | {'allowed': 25, 'fuse_dropped': 27, 'wanted': 52} |
| 2025-08-13 | `top_scored/tier` | more_than_one_message_per_subscription | {'owed': 68, 'subscriptions': 60, 'windows': 1} |
| 2025-10-30 | `top_scored/tier` | cycle_owed_more_than_the_fuse_allows | {'allowed': 25, 'fuse_dropped': 29, 'wanted': 55} |
| 2025-10-30 | `top_scored/tier` | more_than_one_message_per_subscription | {'owed': 62, 'subscriptions': 60, 'windows': 1} |
| 2025-12-19 | `top_scored/tier` | cycle_owed_more_than_the_fuse_allows | {'allowed': 25, 'fuse_dropped': 9, 'wanted': 34} |
| 2025-12-19 | `top_scored/tier` | more_than_one_message_per_subscription | {'owed': 61, 'subscriptions': 60, 'windows': 2} |
| 2020-03-04 | `top_scored/watch` | cycle_owed_more_than_the_fuse_allows | {'allowed': 25, 'fuse_dropped': 0, 'wanted': 28} |
| 2020-11-30 | `top_scored/watch` | cycle_owed_more_than_the_fuse_allows | {'allowed': 25, 'fuse_dropped': 2, 'wanted': 27} |
| 2023-01-26 | `top_scored/watch` | cycle_owed_more_than_the_fuse_allows | {'allowed': 25, 'fuse_dropped': 0, 'wanted': 26} |
| 2023-09-18 | `top_scored/watch` | cycle_owed_more_than_the_fuse_allows | {'allowed': 25, 'fuse_dropped': 0, 'wanted': 26} |
| 2023-12-02 | `top_scored/watch` | cycle_owed_more_than_the_fuse_allows | {'allowed': 25, 'fuse_dropped': 0, 'wanted': 27} |

## What this is measured against — flood 12's flag volume

A FLAG is not a message. The watch branch notifies the top N of a kind per Window; ELEVATED+ is ~15% of the Units present. These are the numbers the cut is measured against, on the same per-Unit-per-year scale.

| kind | ELEVATED+ flags | HIGH flags | units | per unit per year |
| --- | ---: | ---: | ---: | ---: |
| bus_stop | 76,165 | 14,521 | 13,310 | 0.373 |
| cell | 23,342 | 5,159 | 1,351 | 1.127 |
| complex | 5,214 | 956 | 445 | 0.764 |

## The verdict this harness does NOT record

**does notify 08's fuse sizing survive a real event** — notify 10 sizes the live fuse; this harness measures.
