"""`make release-check`: THE RELEASE CHECKLIST for the flood chain (flood-build 09's,
owed since 2026-08-24, slid through tickets 10 and 11, landed here by ticket 15).

WHAT IT IS FOR. Two published artifacts decide what the panel is allowed to SAY:
`research/flood-09-fits.json` holds the metrics tables and `research/flood-10-
coefficients.json` holds the coefficients, the shipped model ids and the pre-selected
panel strings. A release is only honest while the strings on the page are the ones the
GATE selects from those tables — and a gate verdict is the kind of thing that gets typed
into a report once and then quietly diverges from the numbers under it.

So nothing here re-types a verdict. `flood_fits.gate(summary)` is a PURE function of the
published summary; this runs it and compares. Every row is one assertion with its
evidence printed, and a failing row names the file to look at.

    rc 0  every row PASS
    rc 1  a row FAILED — do not release

`make release-check` is a target so it can run anywhere `make` runs; it opens no socket
and needs no data root, because everything it reads is committed to the repo.

Run: make release-check          (or: python -m raincheck.release_check)
"""
import json
import re
import subprocess
from pathlib import Path

from raincheck import contract, flood_fits, flood_panel, publish
from raincheck.paths import REPO

# The claim notify 01 RETIRED because a notifier falsifies it. It is named as a REGEX
# rather than quoted whole, so that this file — whose job is to keep it retired — is not
# itself a hit (the trap notify 01 recorded: a doc ordering a retirement must not quote
# the string, or the zero-hits gate can never pass).
RETIRED = r"a page you open during a storm"
SEARCH = ("src", "web", "docs", "tests", ".scratch", "research")


def rows() -> list[tuple[bool, str, str]]:
    """(ok, row, evidence). Ordered so an early failure explains the later ones."""
    fits = json.loads((REPO / "research" / "flood-09-fits.json").read_text())
    art = json.loads((REPO / "research" / "flood-10-coefficients.json").read_text())
    det = json.loads((REPO / "research" / "flood-11-detector.json").read_text())
    out = []

    # 1-2. THE GATE, re-evaluated. The artifact's stored branch is a claim about tables
    # that sit beside it; this is the only thing that makes it a fact.
    g = flood_fits.gate(fits["summary"])
    out.append((g["branch"] == art["gate"]["branch"],
                "the headline gate re-evaluates to the branch the artifact stores",
                f"flood_fits.gate(summary) -> {g['branch']}, "
                f"artifact -> {art['gate']['branch']}"))
    out.append((g["shipped"] == art["gate"]["shipped"],
                "the shipped model ids are the ones the gate selects",
                f"{g['shipped']} vs {art['gate']['shipped']}"))
    out.append((g["panel_strings"] == art["gate"]["panel_strings"],
                "the panel strings are the branch's, never chosen",
                f"{sorted(g['panel_strings'])} == artifact's"))

    # 3. The panel renders THOSE strings, read from the artifact rather than re-typed.
    got = flood_panel.strings(det, art)
    out.append((got["panel"] == art["gate"]["panel_strings"]
                and got["gate_branch"] == art["gate"]["branch"],
                "the panel renders the gate branch's strings",
                f"branch {got['gate_branch']}, headline "
                f"{got['panel'].get('headline')!r}"))

    # 4. The frozen operating-truth string, verbatim, on BOTH gate sides - compared
    # against notify 01's OWN record of what it froze, never against the exporter's copy
    # of it. `x in json.dumps(payload_rendered_from_x)` is a mirror-pin: both sides move
    # together and the row passes whatever the string becomes (TRAPS: derive it, and the
    # budget pins that compared the artifact to the module it was built from).
    frozen = frozen_string()
    docs = _sample_payloads()
    out.append((frozen is not None and all(
        frozen in json.dumps(docs[n], default=str)
        for n in ("flood.json", "flood-mta.json")),
        "the frozen operating-truth string rides on both payloads, verbatim",
        f"{len(frozen or '')} chars, read from {FROZEN_BY}"))

    # 5. The retired claim, at zero hits.
    hits = _grep(RETIRED)
    out.append((not hits, "the retired storm-page claim has zero hits in the tree",
                f"{len(hits)} hit(s)" + (f": {hits[:3]}" if hits else "")))

    # 6. PROVISIONAL is read at render time, so recording flood 12's verdict reaches the
    # panel without a redeploy. While it is true the panel says so.
    prov = bool(det["cutpoints"]["provisional"])
    out.append((docs["flood.json"]["provisional"] == prov,
                "the payload's `provisional` is the artifact's, read at render time",
                f"cutpoints.provisional={prov}; "
                f"{'the panel says provisional' if prov else 'confirmed by flood 12'}"))

    # 7. The human-facing value is the RANK. A raw eta on a panel reads as a broken number
    # and printing one would be the calibration claim the honesty strings exist to prevent.
    blob = json.dumps(docs, default=str)
    out.append(('"eta"' not in blob and '"probability"' not in blob,
                "no raw eta and no probability crosses the serving boundary",
                "rank / score_index only"))

    # 8. LINEAGE. Nothing MTA-derived may appear on the open side, and the subwaydata.nyc
    # impact numbers (no published licence) never leave the host at all.
    open_side = json.dumps({k: docs[k] for k in ("flood.json", "flood-meta.json")},
                           default=str).lower()
    out.append((not any(w in open_side for w in ("mta_alert", "alert_id", "complex_id",
                                                 "subwaydata")),
                "the ungated payloads carry nothing MTA-derived",
                "no alert row, no complex id, no subwaydata number"))
    # anchored on the IMPORT and on the loaded module, never on the string: the exporter's
    # own docstring says WHY the subway numbers stay local, and a substring check would
    # read that sentence as the violation (TRAPS: anchor on the key, not on the prose).
    src = (REPO / "src" / "raincheck" / "flood_panel.py").read_text()
    imported = re.search(r"^\s*(?:from\s+raincheck\s+import|import)\s+.*flood_impact",
                         src, re.M)
    out.append((imported is None and not hasattr(flood_panel, "flood_impact"),
                "the exporter never imports flood_impact (subway numbers stay LOCAL)",
                "no import of the subwaydata reader, and the name is not bound"))

    # 9. The publisher's own view of this ticket's files: both families complete, the MTA
    # side gated, meta LAST, and the addition additive under the contract integer.
    for fam, gated in ((flood_panel.UNGATED, False), (flood_panel.GATED, True)):
        f = publish.FAMILIES[fam]
        out.append((f.files == flood_panel.FILES[fam] and f.gated is gated
                    and f.files[-1].endswith("-meta.json"),
                    f"family `{fam}` is {'gated' if gated else 'open'}, "
                    "its keys frozen, meta LAST",
                    f"{list(f.files)} gated={f.gated}"))
    out.append((not (contract.PROMISE[contract.CONTRACT] - contract.surface()),
                "adding these families did not break the promised read surface",
                f"contract {contract.CONTRACT}, still a subset"))

    # 10. The budgets the page renders a VERDICT from are derived, not typed.
    out.append((flood_panel.BUDGETS_S == {
        "precip_fresh": det["staleness_budgets"]["precip_fresh_min"] * 60,
        "precip_stale": det["staleness_budgets"]["precip_stale_min"] * 60,
        "floodnet": det["staleness_budgets"]["floodnet_min"] * 60,
        "coops": det["staleness_budgets"]["coops_min"] * 60,
        "nws_alerts": det["staleness_budgets"]["nws_alerts_min"] * 60,
        "nws_knyc_obs": det["staleness_budgets"]["nws_knyc_obs_min"] * 60},
        "every staleness budget agrees with the detector artifact",
        f"{flood_panel.BUDGETS_S}"))

    # 11. The MTA redistribution gate itself. This is a [YOU] item, not a defect: the row
    # reports which side of it a release is on so nobody ships assuming the other.
    out.append((True, "the MTA terms gate is reported, not asserted",
                f"publish.LIVE_TERMS_VERIFIED = {publish.LIVE_TERMS_VERIFIED!r} -> "
                f"{'OPEN' if publish.LIVE_TERMS_VERIFIED else 'CLOSED: live.geojson and '
                   'files/flood-mta.json stay local'}"))
    return out


# Where notify 01 recorded the string it froze on 2026-08-23, as a blockquote. It is the
# independent side of the comparison above; the exporter's constant is the side under test.
FROZEN_BY = ".scratch/notify/issues/01-lift-no-alerting-rule.md"


def frozen_string() -> str | None:
    """notify 01's frozen operating-truth string, read out of its own ticket file."""
    for line in (REPO / FROZEN_BY).read_text().splitlines():
        line = line.strip()          # the blockquote is indented inside a list item
        if line.startswith("> raincheck ranks where a flood REPORT"):
            return line[1:].strip()
    return None


def _sample_payloads() -> dict:
    """The four documents, rendered from the committed artifacts over an empty read.

    A checklist that could only run against a live root would run nowhere; the strings,
    the lineage and the absent-eta rules are properties of the WRITER, and this is the
    smallest input that exercises it.
    """
    import raincheck.flood_detect as fd

    det, art = fd.constants(), json.loads(
        (REPO / "research" / "flood-10-coefficients.json").read_text())
    read = {"detector_version": det["detector_version"],
            "score_version": art["score_version"],
            "skew": {"model_tier": "refused", "reason": "no table read in the checklist"},
            "staleness": {"state": "DOWN"}, "window": {"state": "INSUFFICIENT_DATA"},
            "units": [], "features": None, "dim": {}, "winter": {}, "revisions": [],
            "cell_totals": {}}
    uni = {"units": [], "static": {}, "where": {}, "table_score_version": None}
    truth = {"floodnet": {"source": "floodnet", "status": "error", "citation": "",
                          "caveats": [], "rule": "", "window_min": 60, "asof": "",
                          "sensors": []},
             "mta": {"source": "mta_alerts", "status": "error", "vocabulary": "",
                     "hours": 6, "asof": "", "chips": []}}
    from datetime import datetime, timezone
    return flood_panel.payloads(read, uni, truth, None, None, det, art,
                                datetime(2026, 1, 1, tzinfo=timezone.utc))


def _grep(pattern: str) -> list[str]:
    """git grep over the tracked tree: it honours .gitignore, so `web/vendor/` and other
    untracked bulk cannot manufacture a hit."""
    r = subprocess.run(["git", "grep", "-l", "-E", pattern, "--", *SEARCH],
                       cwd=REPO, capture_output=True, text=True)
    if r.returncode not in (0, 1):
        raise RuntimeError(f"git grep failed: {r.stderr.strip()}")
    return [l for l in r.stdout.splitlines()
            if l and not l.endswith("src/raincheck/release_check.py")]


def main() -> None:
    checks = rows()
    for ok, row, evidence in checks:
        print(f"[{'PASS' if ok else 'FAIL'}] {row}\n         {evidence}")
    bad = [r for ok, r, _ in checks if not ok]
    print(f"release-check: {len(checks) - len(bad)}/{len(checks)} rows pass")
    if bad:
        print("REFUSED — do not release:\n  " + "\n  ".join(bad))
        raise SystemExit(1)


if __name__ == "__main__":
    main()
