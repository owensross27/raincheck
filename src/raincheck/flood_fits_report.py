"""The markdown build asset for flood-build ticket 09 — a pure rendering of the JSON.

Split from `flood_fits` on purpose: the JSON is the artifact ticket 10 loads and a release
checklist re-evaluates the gate from, so the prose cannot disagree with the numbers — every
number below reads a field of that JSON, including the ones flood 08 measured and stamped
into the matrix's own metadata (they arrive here as `matrix_census` / `matrix_gates` and are
labelled as inherited where they print). Nothing is recomputed from the data here.
"""
from collections.abc import Mapping, Sequence

from raincheck.flood_fits import (BASELINES, FIM_BAND, GATE_SPLIT, PRIMARY_SPLIT, SPLITS,
                                  gate)

LABEL = {"model": "**L2 logistic (this ticket's fit)**", "B0_base_rate": "B0 base rate",
         "B1_precip_only": "B1 precip-only", "B2_unit_climatology": "B2 unit climatology",
         "B3_density_only": "B3 density-only"}


def _table(head: Sequence[str], rows: Sequence[Sequence]) -> str:
    out = ["| " + " | ".join(head) + " |", "|" + "|".join(["---"] * len(head)) + "|"]
    out += ["| " + " | ".join("" if c is None else str(c) for c in r) + " |" for r in rows]
    return "\n".join(out) + "\n"


def _f(x, n=4):
    return "-" if x is None else f"{x:.{n}f}"


def _ci(m):
    lo, hi = m["ci"]["csi"]
    return f"{_f(lo, 3)}-{_f(hi, 3)}"


def _skill_rows(models: Mapping, split: str) -> list[list]:
    order = ["model", *BASELINES]
    return [[LABEL[k], _f(models[k][split]["csi"]), _ci(models[k][split]),
             _f(models[k][split]["pod"], 3), _f(models[k][split]["far"], 3),
             _f(models[k][split]["pr_auc"]), models[k][split]["tp"],
             models[k][split]["fp"], models[k][split]["fn"],
             _f(models[k][split]["alert_rate"], 4)] for k in order]


SKILL_HEAD = ("model", "CSI", "CSI 95% CI", "POD", "FAR", "PR-AUC", "TP", "FP", "FN",
              "alert rate")


def render(r: Mapping) -> str:
    g = r["gate"]
    cov, cen = r["coverage"], r["census"]
    out = [f"""# flood-09 — fits, baselines, validation, and the headline gate

`fits_version` **{r['fits_version'][:12]}** over `matrix_version` **{(r['matrix_version'] or '')[:12]}**.
Estimand: **{r['estimand']}** — where flooding was REPORTED, not where water necessarily stood.

Two L2 logistic fits (point, cell), unweighted, lambda by inner CV; four baselines; two
deterministic sha1 group splits; every published number is OUT OF FOLD. The operating point
is chosen IN FOLD — the CSI-maximising cut on that fold's training rows — and what transfers
to the held-out rows is its ALERT BUDGET, applied as a quantile of the held-out scores (no
held-out label is read). Transferring the raw probability instead is published as a sweep
row; it moves nothing here, and it is what stops a constant-scored baseline from reading
CSI 0.0 for a reason that is about its score's scale rather than about the baseline.

## HEADLINE GATE — {GATE_SPLIT}: **{g['branch']}**

{_table(("role", "model CSI", "B2 CSI", "B3 CSI", "beats B2", "beats B3", "SHIPPED"),
        [[role, _f(v['model_csi']), _f(v['b2_csi']), _f(v['b3_csi']),
          "yes" if v['beats_b2'] else "**no**", "yes" if v['beats_b3'] else "**no**",
          f"`{g['shipped'][role]}`"] for role, v in sorted(g['roles'].items())])}
The gate is a pure function of the table above (`flood_fits.gate`), re-evaluable from the
published JSON — so whichever branch fired is CHECKABLE rather than remembered. The checking
itself is owed downstream: ticket 10 builds the release artifacts and is where the assertion
lands. Nothing in this repo asserts it today. The branch also SELECTS THE STRINGS, which is the spec's
if-the-baseline-wins-ship-the-baseline clause carried through to the panel: headline
"{g['panel_strings']['headline']}", caveat "{g['panel_strings']['caveat']}", release
"{g['panel_strings']['release']}" (`gate.panel_strings` in the JSON; ticket 15 and notify 09
render them, and `flood_fits.PANEL_STRINGS` holds the alternates the other branches select).

**Read B2 under this split with its degeneracy in mind:** location blocking puts every
held-out Unit's entire history inside the held-out fold, so B2 has no in-fold history for
any Unit it scores and falls back to the training prior — under this split B2 IS the base
rate. That is what the split is for, and it is why the event-grouped column below (where
B2 keeps its history and is a real competitor) is published beside it.
"""]

    for role in sorted(cen):
        c = cen[role]
        out.append(f"""
## {role} model

{c['rows']:,} rows · {c['positives']:,} positives · base rate {c['base_rate']*100:.3f}% ·
{c['events']} events · {c['units']:,} Units · {c['cells']:,} Cells.
By kind: {', '.join(f"{k} {v['rows']:,}/{v['positives']:,} pos" for k, v in sorted(c['by_kind'].items()))}.

### {PRIMARY_SPLIT} (primary)

{_table(SKILL_HEAD, _skill_rows(r['summary'][role], PRIMARY_SPLIT))}
### {GATE_SPLIT} (the gate's split)

{_table(SKILL_HEAD, _skill_rows(r['summary'][role], GATE_SPLIT))}
CSI reference band: published FIM systems run **{FIM_BAND[0]}-{FIM_BAND[1]}**. The
comparison is ORDER-OF-MAGNITUDE ONLY — those systems predict inundation extent from
hydraulics against a different estimand (water present), on a different support, at a
different positive rate. It is a sanity band, never a target and never a claim of parity.
""")

    cx = r["complex_validation"]
    out.append(f"""
## Complex grain — the independent validation set

A complex is never fitted. Its score is the max over its child entrances' out-of-fold
scores and it alarms when any child alarms at that child's own in-fold operating point, so
the alert-sourced complex-event pairs never touch training.

{_table(("split", "pairs", "positives", "events", "CSI", "CSI 95% CI", "POD", "FAR",
         "PR-AUC", "pairs without children"),
        [[s, f"{cx[s]['rows']:,}", cx[s]['positives'], cx[s]['events'], _f(cx[s]['csi']),
          _ci(cx[s]), _f(cx[s]['pod'], 3), _f(cx[s]['far'], 3), _f(cx[s]['pr_auc']),
          cx[s]['pairs_without_child_entrances']] for s in SPLITS])}
At a matched ALERT BUDGET instead of the union rule — alarm the top
{cx[GATE_SPLIT]['rate_transfer']['budget']*100:.2f}% of complex-event pairs by max score, the
same in-fold budget the row-grain metrics use — the same set reads CSI
{_f(cx[GATE_SPLIT]['rate_transfer']['csi'])} (POD {_f(cx[GATE_SPLIT]['rate_transfer']['pod'], 3)},
TP {cx[GATE_SPLIT]['rate_transfer']['tp']} of {cx[GATE_SPLIT]['positives']}). The best single
cut anyone could have chosen ON this set reaches {_f(cx[GATE_SPLIT]['best_single_cut_csi_selected_here'])} —
printed for scale, not a result, and not an upper bound on the union rule (which cuts per
fold and can beat any one global cut).

The measured complex label count is **{cx[GATE_SPLIT]['positives']}** pluvial fit-era pairs
— the drafted 155 was superseded by flood 08's measurement against the landed labels.

**Read this set as the ticket intended it — as the independent check, and as the weakest
number here.** The point model was fitted on 311/FloodNet/HWM-derived labels at doorway
grain; these pairs are MTA-alert-derived at complex grain, and nothing about them entered
training. The result is a PR-AUC of {_f(cx[GATE_SPLIT]['pr_auc'])} against a base rate of
{cx[GATE_SPLIT]['positives'] / cx[GATE_SPLIT]['rows']:.4f} — a lift, but a small one, and the
operating point that works at row grain barely alarms here. Whatever ships, a complex-grain
number is not a validated claim on this evidence.
""")

    out.append("""
## Per-event POD and raw false-positive count

Per-event CSI is NOT published: the positives per event are too thin for it to mean
anything. Measured on this matrix — """)
    for role in sorted(r["per_event"]):
        pe = [e for e in r["per_event"][role] if e["positives"]]
        single = sum(1 for e in pe if e["positives"] == 1)
        out.append(f"{role}: {single} of {len(pe)} events with a positive have exactly one"
                   + ("; " if role != sorted(r["per_event"])[-1] else ". "))
    cxg = r["complex_validation"][GATE_SPLIT]
    out.append(f"""complex: {cxg['single_positive_events']} of
{cxg['events_with_a_positive']} — the grain where the drafted "61% of events are
single-positive" was closest to true, and still not what it said. All three counts are
measured here and superseded it. The full per-event table is in the JSON; the ten events
with the most positives:

""")
    for role in sorted(r["per_event"]):
        top = sorted(r["per_event"][role], key=lambda e: -e["positives"])[:10]
        out.append(f"\n**{role}** ({GATE_SPLIT})\n\n" + _table(
            ("event", "positives", "TP", "raw FP", "POD"),
            [[f"`{e['event_id']}`", e["positives"], e["tp"], e["fp"], _f(e["pod"], 3)]
             for e in top]))

    out.append("\n## Contrasts\n")
    for role, con in sorted(r["contrasts"].items()):
        if "history_covariate" in con:
            h = con["history_covariate"]
            out.append(f"""
### History covariate, {role} ({h['split']})

CSI **{_f(h['with'])}** with the own-source 311 trailing density, **{_f(h['without'])}**
without it (delta {h['with'] - h['without']:+.4f}). The contrast reports under the
location-blocked split by design: it is the split that asks whether the history term
generalises to neighbourhoods the fit never saw, rather than whether it memorises the ones
it did.
""")
        if "bus_stop_churn" in con:
            b = con["bus_stop_churn"]
            cen = r["matrix_census"]
            dropped = r["matrix_gates"].get("positives_dropped_unpairable", 0)
            kept = r["census"]["point"]["by_kind"]["bus_stop"]["positives"]
            # the denominator is arithmetic on the matrix's own census, not a typed number:
            # candidates - negatives = the positives that survived, + the ones pairable cut
            before = cen.get("candidates", 0) - cen.get("negatives", 0) + dropped
            out.append(f"""
### Bus-stop churn delta, {role} ({b['split']})

{_table(("cut", "CSI", "realized alert rate"),
        [["pooled fit, all point rows", _f(b['pooled_all_rows']), _f(b['rate_all'], 4)],
         ["pooled fit, scored on entrance rows only", _f(b['pooled_on_entrance_rows']),
          _f(b['rate_entrance'], 4)],
         ["pooled fit, scored on bus rows only", _f(b['pooled_on_bus_rows']),
          _f(b['rate_bus'], 4)],
         ["fit WITHOUT any bus row, scored on entrance rows",
          _f(b['entrance_only_fit_on_entrance_rows']), _f(b['rate_entrance_only'], 4)]])}
**Every subset row here is CUT ON THE ROWS IT SCORES** — each fold spends its declared
in-fold budget within the subset, which is why the realized rates in the last column sit
close together. That is deliberate: with one cut spread over the whole point population the
two arms of the churn delta landed at 0.43% and 1.26%, and CSI is monotone in alert rate at
a 0.5% base rate, so the delta would have been measuring the budget. The top row (all point
rows) is the operational read — one deployed cut over everything — and the rate column is
what lets the two readings be told apart.
{b['bus_rows']:,} bus rows, {b['bus_positives']:,} positives, {b['bus_events']} events.
{b['method_note']}

**The symmetry any bus-stop sentence has to carry:** running the positives through
`flood_labels.pairable()` dropped **{dropped:,} of {before:,}** pluvial fit-era positives,
against **{kept:,}** bus-stop positives KEPT. All three are read off the matrix's own
metadata rather than typed here: `matrix_gates.positives_dropped_unpairable`,
`matrix_census.candidates - matrix_census.negatives + that drop`, and
`census.point.by_kind.bus_stop.positives`. The one number this asset cannot re-derive —
**4,068** of the drop being pre-2020 bus stops — is flood 08's measurement, quoted here as
inherited, not as measured by this run. The same era rule already deletes
those rows' negatives, so this is a symmetry rather than a loss; but every base rate and
every bus-stop number above is computed on the kept side of it.
""")
        p = con["pre_post_2014"]
        out.append(f"""
### Pre/post-2014, {role} ({p['split']})

{_table(("era", "rows", "positives", "events", "CSI", "POD", "FAR", "realized alert rate"),
        [[k, f"{p[k]['rows']:,}", p[k]['positives'], p[k]['events'], _f(p[k]['csi']),
          _f(p[k]['pod'], 3), _f(p[k]['far'], 3), _f(p[k]['alert_rate'], 4)]
         for k in ("pre_2014", "post_2014")])}
Same caveat as any masked row here: one budget is spent over the whole population, so the
two eras alarm at different realized rates and the CSI gap carries that as well as the
confound below.
CONFOUND, stamped on the split: {p['confound']}
""")

    out.append("\n## Sensitivity sweeps — one at a time around the frozen primary\n\n")
    for role in sorted(r["sweeps"]):
        out.append(f"\n**{role}** ({GATE_SPLIT}, lambda held at the modal CV choice)\n\n"
                   + _table(("config", "CSI", "delta CSI", "POD", "FAR", "PR-AUC"),
                            [[s["config"], _f(s["csi"]),
                              "-" if s["delta_csi"] is None else f"{s['delta_csi']:+.4f}",
                              _f(s["pod"], 3), _f(s["far"], 3), _f(s["pr_auc"])]
                             for s in r["sweeps"][role]]))
    said = []
    for role in sorted(r["sweeps"]):
        rows = [x for x in r["sweeps"][role] if x["config"].startswith("lambda")]
        shipped = r["final"][role]["lambda"]
        mine = f"lambda={shipped:g}"
        best, worst = max(rows, key=lambda x: x["csi"]), min(rows, key=lambda x: x["csi"])
        spread = max(x["pr_auc"] for x in rows) - min(x["pr_auc"] for x in rows)
        where = ("which IS the shipped rung" if best["config"].startswith(mine)
                 else "the WORST of the rungs" if worst["config"].startswith(mine)
                 else "not the shipped rung")
        said.append(
            f"- **{role}**: shipped lambda {shipped:g} (the modal inner-CV choice across the "
            f"outer folds). On the GATE metric the best rung is `{best['config']}` at CSI "
            f"{_f(best['csi'])} — the shipped one is {where}. PR-AUC, the metric lambda is "
            f"actually selected on, moves by {spread:.4f} across the whole grid including "
            f"the rung beyond its top.\n")
    out.append("\nRead the lambda rows before trusting the shipped penalty:\n\n"
               + "".join(said)
               + "\nA CSI ordering that flips while the selection metric moves in the "
                 "fourth decimal is noise rather than a preference — the honest reading in "
                 "both directions, including where the shipped rung is the lowest-CSI one.\n")
    out.append("""
**Deferred, with the reason — not run here and not silently dropped:** the label radius
sweep {50, 100, 200} m and the p99-union 311 threshold sweep both REDEFINE THE EVENT
UNIVERSE. The radius lives inside ticket 05's Sedona `ST_DWithin` label join and the
threshold inside ticket 04's spine derivation, both upstream of `gold/flood_matrix`, which
this ticket reads and never rebuilds. They run as ticket 18's outer replication, whose
shape is exactly "re-derive the universe, rebuild 05/06/08, re-run 09's fits, publish the
delta beside the frozen primary".
""")

    out.append(_honest(r))

    rep = r["era_replication"]
    out.append(f"""
## MRMS-era out-of-sample replication — {rep['status']}

{rep['reason']}. Events by era in the landed spine: {rep['events_by_era']}.
Band caveat, stamped for when it does run: {rep['caveat']}.

## Coverage honesty (recomputed, not inherited)

The landed spine `silver/flood_events` carries **{cov['events']} events over
{cov['event_days']} event-days**, {cov['first']}..{cov['last']} — by class
{cov['by_class']}. The pluvial fit-era universe these fits read is **{cov['pluvial_fit_era']}
events over {cov['pluvial_fit_era_days']} event-days**. {cov['superseded'].capitalize()} is
SUPERSEDED; any coverage fraction quoted downstream is against {cov['event_days']}
event-days, never 115.

## What the fits publish for ticket 10

`research/flood-09-fits.json` carries, per role: the shipped model id, the CV-selected
lambda, coefficients on BOTH the standardised and the raw feature scale (with the
standardisation constants), the feature list and the stormwater base level, and the fit-era
precip percentiles in log1p AND raw mm — the columns are stored already-log1p'd, so a
consumer that transforms again ships a silent bug.
""")
    assert gate(r["summary"])["branch"] == g["branch"]   # the prose cannot drift from it
    return "".join(out)


def _overlap(a: Mapping, b: Mapping) -> bool:
    (lo, hi), (blo, bhi) = a["ci"]["csi"], b["ci"]["csi"]
    return lo <= bhi and blo <= hi


def _honest(r: Mapping) -> str:
    """The paragraph the gate does not write for you: every place a published number is
    weaker than the branch it fired. Read out of the same fields, so it cannot drift."""
    out = ["\n## Honest strings — where these numbers are weaker than the gate\n"]
    for role in sorted(r["summary"]):
        s = r["summary"][role]
        for split in SPLITS:
            m, b2, b3 = s["model"][split], s["B2_unit_climatology"][split], s["B3_density_only"][split]
            lost = [n for n, b in (("B2 unit climatology", b2), ("B3 density-only", b3))
                    if m["csi"] <= b["csi"]]
            over = [n for n, b in (("B2", b2), ("B3", b3)) if _overlap(m, b)]
            if lost or over:
                out.append(
                    f"\n- **{role} / {split}**: model CSI {_f(m['csi'])} "
                    + (f"is BEATEN by {', '.join(lost)}, and " if lost else "wins outright, but ")
                    + (f"its 95% CI {_ci(m)} OVERLAPS {', '.join(over)}"
                       if over else "on a separated interval") + ".")
        m = s["model"][GATE_SPLIT]
        if m.get("in_fold_csi_mean"):
            out.append(
                f"\n- **{role} optimism, measured**: the same cut scored CSI "
                f"{_f(m['in_fold_csi_mean'])} on the rows its fold was FITTED on against "
                f"{_f(m['csi'])} out of fold. A small gap says the fit is not memorising "
                f"its training rows — with this few features under a heavy ridge it is not "
                f"free to. It says nothing about whether the score is USEFUL; the baselines "
                f"and the independent set above are what answer that.")
        out.append(
            f"\n- **{role} operating point**: {m['fp']:,} false alarms against {m['tp']:,} "
            f"hits at a {m['alert_rate']*100:.2f}% alert budget over {m['rows']:,} rows — "
            f"FAR {_f(m['far'], 3)}, POD {_f(m['pod'], 3)}. The tier cutpoints ticket 11 "
            f"provisionally ships (top 10% / top 2%) are far LOOSER than this budget, so "
            f"ticket 12's replay is where per-event flag volume gets decided, not here.")
    cx = r["complex_validation"][GATE_SPLIT]
    out.append(
        f"\n- **the independent set is the weak one**: {cx['tp']} of {cx['positives']} "
        f"complex-event positives caught under the union rule, CSI {_f(cx['csi'])}. "
        f"Everything above it is measured on the grain the model was FITTED on.\n")
    return "".join(out)
