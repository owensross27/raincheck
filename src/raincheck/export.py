"""`make export` (ticket 13 / spec L): the insight files, written by one DuckDB script.

Runs `web/export.sql` - one text, also importable by a notebook - and writes its three
marked outputs to `web/files/`:

  cells.geojson   one Feature per footprint Cell, geometry from ref/cells at 5 dp,
                  wide properties per window and per storm hour, ABSENT (never null)
                  when unpublishable
  headline.json   every number on the panel with its literal estimand, its 95% interval,
                  the median-Cell companion, n_legs / n_cells / n_cells_hidden and the
                  chord band as a numeric pair
  zones.geojson   the 263 TLC taxi zones, simplified: the ground layer
  index.json      the static read API's discovery document (frontend 06): every family
                  with its keys, content types, schema pointers, cadence and cache
                  semantics, plus the `contract` integer a consumer refuses on. Rendered
                  by raincheck.contract, not by the SQL, and staged with the other three
                  so it never lands alone naming payloads that are not there.

`--geo` (frontend2 03) runs the SIBLING script `web/geo.sql` through the same machinery
into `web/files/geo/`, the TREE family flood-build 19 opened:

  routes.geojson  one Feature per (shape_id, Cell crossing) from silver/shapes x
                  ref/cells, carrying the SAME per-window estimand names cells.geojson
                  carries, restricted to that route's rows in that Cell

Two scripts, ONE exporter: the marker grammar, the two SET VARIABLEs, the all-or-none
staging and the byte-identity are the same code for both, so a second output family
cannot quietly grow a second set of rules. `make geo` runs the stormwater extents
(flood-build 19) and then this.

The SQL is the contract; this module only supplies the two variables (data root, the
swept interval-width gate), splits the text on its `-- @@out <file>` markers and writes
what each final SELECT returns. Re-export is byte-identical (every aggregate ordered,
every number explicitly rounded), so the files diff cleanly as evidence artifacts.

The same RUN also writes the static history surface - `files/history/`, a manifest of
every asset with a flood record and one file per listed asset [notify 05]. It is rendered
by `raincheck.history` over SEAM Q and not by this SQL, so it hangs off main() as its own
all-or-none unit rather than off run(): the two are different publish families on
different cadences, and a history tree that could not be built must not withhold an
insight build that could. This is the BATCH path and the only path - nothing here ever
runs on the 30 s live tick.

Run: make export            (python -m raincheck.export)
     make export GATE=0.5   (sweep the interval-width gate)
     make geo                (python -m raincheck.export --geo, after the extents)
"""
import argparse
import json
from pathlib import Path

from raincheck import contract, duck, history
from raincheck.paths import REPO, data_root

SQL = REPO / "web" / "export.sql"
GEO_SQL = REPO / "web" / "geo.sql"          # frontend2 03's sibling script
OUT = REPO / "web" / "files"
GEO_OUT = OUT / "geo"                       # the `geo` publish family's tree
MARKER = "\n-- @@out "  # at line start only: the header comment names the marker inline
GATE_WIDTH = 0.30  # spec L's default, swept; the gate is interval width, never bare n


def split(text: str) -> tuple[str, list[tuple[str, str]]]:
    """(prelude, [(filename, query)]) from the `-- @@out <file>` markers."""
    head, *rest = text.split(MARKER)
    out = []
    for chunk in rest:
        name, _, body = chunk.partition("\n")
        out.append((name.strip(), body))
    return head, out


def render(sql: Path, root: Path, gate_width: float = GATE_WIDTH):
    """(connection, [(filename, text)]) - one connection, one prelude, every marked query.

    The connection comes back so a caller can render something else off the SAME universe
    the SQL just read (index.json's version stamps do exactly that) without opening a
    second one and resolving the stamps twice.
    """
    prelude, queries = split(sql.read_text())
    con = duck.connect()
    con.execute("LOAD spatial")
    con.execute("SET VARIABLE root = ?", [str(root)])
    con.execute("SET VARIABLE gate_width = ?", [gate_width])
    con.execute(prelude)
    return con, [(name, con.execute(query).fetchone()[0]) for name, query in queries]


def stage(texts, out_dir: Path) -> dict[str, Path]:
    """Write every output or none. A run that died on the last query would otherwise leave
    the directory holding fresh files beside stale ones, and the page would render two
    layers from different builds with nothing to show for it. Each file is written to
    `<name>.tmp` first and every rename happens after every write."""
    out_dir.mkdir(parents=True, exist_ok=True)
    staged = []
    for name, text in texts:
        tmp = out_dir / (name + ".tmp")
        tmp.write_text(text)
        staged.append((name, tmp))
    return {name: tmp.replace(out_dir / name) for name, tmp in staged}


def run(root: Path, out_dir: Path, gate_width: float = GATE_WIDTH) -> dict[str, Path]:
    con, texts = render(SQL, root, gate_width)
    # index.json rides the same all-or-none staging: it NAMES the three files beside it
    # and carries the stamps of the universe that answered, so a run that published it
    # alone would hand a consumer a fresh contract over stale payloads.
    texts.append((contract.NAME, contract.text(con, root)))
    return stage(texts, out_dir)


def run_geo(root: Path, out_dir: Path, gate_width: float = GATE_WIDTH) -> dict[str, Path]:
    """`web/geo.sql` -> web/files/geo/. No index.json here: `geo` is a TREE family, so its
    file set is DERIVED at publish time and the discovery document names the PREFIX."""
    _, texts = render(GEO_SQL, root, gate_width)
    return stage(texts, out_dir)


def report(written: dict[str, Path]) -> None:
    """Print what the honesty gates hid. Spec L: the hidden set is storm-correlated, so a
    gate that empties the map must be visible here, never quietly loosened."""
    for name, path in written.items():
        print(f"  {name}: {path.stat().st_size / 1024:.0f} KB")
    idx = json.loads(written[contract.NAME].read_text())
    print(f"{contract.NAME}: contract {idx['contract']}, {len(idx['families'])} families, "
          f"versions {idx.get('versions') or idx['versions_unresolved']}")
    cells = json.loads(written["cells.geojson"].read_text())
    print(f"cells.geojson: {len(cells['features'])} footprint Cells")
    head = json.loads(written["headline.json"].read_text())
    print(f"publish gate: 95% interval width < {head['gate_width']}")
    for row in head["rows"]:
        shown, hidden = row["n_cells"], row["n_cells_hidden"]
        share = shown / (shown + hidden) if shown + hidden else 0
        flag = "  <-- most of the map is hidden" if share < 0.5 else ""
        print(f"  {row['label']:<22} citywide {row['value']:.3f} "
              f"[{row['lo']:.3f}, {row['hi']:.3f}]  band {row['band']}  "
              f"median Cell {row['median_cell']}  {shown} shown / {hidden} hidden{flag}")


def report_geo(written: dict[str, Path]) -> None:
    """Size and feature count, said with the number. A route layer is a TOGGLE, so what it
    costs a reader who ticks it is the fact that decides whether it may exist at all - the
    same disclosure flood-build 19 made for the extents."""
    for name, path in written.items():
        doc = json.loads(path.read_text())
        raw = path.stat().st_size
        if "features" not in doc:                       # the scenario manifest
            served = [s["key"] for s in doc["scenarios"]]
            print(f"  {name}: {raw:,} raw bytes, {len(served)} current-horizon "
                  f"scenario(s): {', '.join(served) or 'none'}")
            continue
        n = len(doc["features"])
        print(f"  {name}: {n:,} features, {raw:,} raw bytes ({raw / 1048576:.2f} MiB)")
        keyed = sum(1 for f in doc["features"]
                    if any(k.endswith("_ratio") for k in f["properties"]))
        print(f"    {keyed:,} carry a published ratio; {n - keyed:,} paint grey "
              f"(interval too wide, or no dry baseline for that route in that Cell)")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--gate", type=float, default=GATE_WIDTH,
                    help=f"interval-width publish gate (default {GATE_WIDTH})")
    ap.add_argument("--geo", action="store_true",
                    help="run web/geo.sql into web/files/geo (the `geo` family) instead")
    ap.add_argument("--out", type=Path, default=None,
                    help=f"output directory (default {OUT}, or {GEO_OUT} with --geo)")
    args = ap.parse_args()
    root = data_root()
    out = args.out or (GEO_OUT if args.geo else OUT)
    which = "geo" if args.geo else "export"
    print(f"{which}: root={root} gate={args.gate} -> {out}", flush=True)
    if args.geo:
        report_geo(run_geo(root, out, args.gate))
    else:
        report(run(root, out, args.gate))
        # notify 05, on this same batch run: its own connection, its own staged tree, and
        # its own refusal - a root with no flood universe leaves the tree unwritten and
        # says so rather than failing the export that just succeeded.
        history.report(history.build(duck.connect(), root, out / history.DIR))


if __name__ == "__main__":
    main()
