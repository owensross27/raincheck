#!/usr/bin/env python3
"""Score cause-anchored matcher output against independent hand labels.

Scoring grain: station complex_id, not alias string — "E 143 St" and
"E 143 St-St Mary's St" are the same station. A truth substring resolves
through the same alias index (route-filtered). An unresolvable truth string is
skipped when a resolvable truth string of the same row is contained in it (name
variant of the same station); otherwise it counts as a false negative.

Usage: python3 compare.py labels.json sample_full.json
"""
import json
import pathlib
import sys

from matcher import build_pattern, load_stations, norm, parse_routes

DIR = pathlib.Path(__file__).parent


def resolve(name: str, affected, by_alias, pat) -> frozenset:
    """Truth substring -> complex_id set via the alias index (route-filtered)."""
    n = norm(name)
    m = pat.fullmatch(n) or pat.search(n)
    if not m or m.group(0) != n and m.group(0) not in n:
        return frozenset()
    cands = by_alias.get(m.group(0), [])
    routes = parse_routes(affected)
    picked = [c for c in cands if routes & parse_routes(c.get("daytime_routes", ""))] or cands
    return frozenset(c["complex_id"] for c in picked)


def main(labels_file: str, sample_file: str) -> None:
    by_alias = load_stations()
    pat = build_pattern(by_alias)
    truth = {r["i"]: r for r in json.load(open(DIR / labels_file))}
    sample = json.load(open(DIR / sample_file))

    tp = fp = fn = 0
    fps, fns = [], []
    for i, row in enumerate(sample):
        lab = truth[i]
        resolved, unresolved = set(), []
        for name in lab["flood_stations"]:
            cids = resolve(name, row["affected"], by_alias, pat)
            if cids:
                resolved.add(cids)
            else:
                unresolved.append(name)
        # drop unresolved variants of an already-resolved name
        unresolved = [
            u for u in unresolved
            if not any(norm(r_) in norm(u) for r_ in lab["flood_stations"]
                       if resolve(r_, row["affected"], by_alias, pat) and norm(r_) != norm(u))
        ]
        pred = []
        for m in row["matches"]:
            if m["cause"] and frozenset(m["complex_ids"]) not in pred:
                pred.append(frozenset(m["complex_ids"]))
        # greedy match: predicted set counts as TP if it intersects a truth set
        t_left = list(resolved)
        for p in pred:
            hit = next((t for t in t_left if t & p), None)
            if hit is not None:
                tp += 1
                t_left.remove(hit)
            else:
                fp += 1
                fps.append((i, sorted(p)[:2], row["text"][:95]))
        fn += len(t_left) + len(unresolved)
        for t in t_left:
            fns.append((i, sorted(t)[:2], row["text"][:95]))
        for u in unresolved:
            fns.append((i, u, row["text"][:95]))

    prec = tp / (tp + fp) if tp + fp else 0.0
    rec = tp / (tp + fn) if tp + fn else 0.0
    print(f"complex-grain cause: TP {tp} FP {fp} FN {fn}  "
          f"precision {prec:.3f}  recall {rec:.3f}")
    print(" FPs:")
    for i, x, t in fps[:12]:
        print(f"  [{i}] {x} :: {t}")
    print(" FNs:")
    for i, x, t in fns[:12]:
        print(f"  [{i}] {x} :: {t}")

    for flag in ("system_wide", "footer_only", "planned_work"):
        agree = sum(1 for i, row in enumerate(sample)
                    if row["flags"][flag] == bool(truth[i].get(flag)))
        print(f"flag {flag}: agree {agree}/{len(sample)}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "labels.json",
         sys.argv[2] if len(sys.argv) > 2 else "sample_full.json")
