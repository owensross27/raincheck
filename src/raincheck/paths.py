"""The data root (spec A): RAINCHECK_ARCHIVE_ROOT, default the repo's data/ (the external SSD
in practice). Every dataset root hangs off it: archive/ (Bronze), ref/, silver/, gold/,
live/, checkpoints/, checks/, .staging/. Unset or empty means the default."""
import os
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def data_root() -> Path:
    return Path(os.environ.get("RAINCHECK_ARCHIVE_ROOT") or REPO / "data")
