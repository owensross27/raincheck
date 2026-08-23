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

The SQL is the contract; this module only supplies the two variables (data root, the
swept interval-width gate), splits the text on its `-- @@out <file>` markers and writes
what each final SELECT returns. Re-export is byte-identical (every aggregate ordered,
every number explicitly rounded), so the files diff cleanly as evidence artifacts.

Run: make export            (python -m raincheck.export)
     make export GATE=0.5   (sweep the interval-width gate)
"""
import argparse
import json
from pathlib import Path

from raincheck import duck
from raincheck.paths import REPO, data_root

SQL = REPO / "web" / "export.sql"
OUT = REPO / "web" / "files"
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


def run(root: Path, out_dir: Path, gate_width: float = GATE_WIDTH) -> dict[str, Path]:
    prelude, queries = split(SQL.read_text())
    con = duck.connect()
    con.execute("LOAD spatial")
    con.execute("SET VARIABLE root = ?", [str(root)])
    con.execute("SET VARIABLE gate_width = ?", [gate_width])
    con.execute(prelude)
    out_dir.mkdir(parents=True, exist_ok=True)
    written = {}
    for name, query in queries:
        (text,) = con.execute(query).fetchone()
        path = out_dir / name
        path.write_text(text)
        written[name] = path
    return written


def report(written: dict[str, Path]) -> None:
    """Print what the honesty gates hid. Spec L: the hidden set is storm-correlated, so a
    gate that empties the map must be visible here, never quietly loosened."""
    for name, path in written.items():
        print(f"  {name}: {path.stat().st_size / 1024:.0f} KB")
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


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--gate", type=float, default=GATE_WIDTH,
                    help=f"interval-width publish gate (default {GATE_WIDTH})")
    ap.add_argument("--out", type=Path, default=OUT, help=f"output directory (default {OUT})")
    args = ap.parse_args()
    root = data_root()
    print(f"export: root={root} gate={args.gate} -> {args.out}", flush=True)
    report(run(root, args.out, args.gate))


if __name__ == "__main__":
    main()
