"""Marker-gated, remote-verified prune of one backfill chunk's Bronze parts.

Deletes a local Bronze file only when ALL of these hold:
  1. its day is inside [lo, hi]        - live capture is never in a backfill range
  2. its hour-dir holds a _gapfill marker - the marker is touched only after the whole
     day succeeded, so it proves the part is complete and not mid-write
  3. it is NOT in the pending list     - pending = "sync would still upload this", i.e.
     not yet proven present remotely at matching size

Usage: prune.py <lo> <hi> <pending_file> <archive_root>
"""
import sys
from pathlib import Path

KINDS = ("vp", "tu", "alerts")


def prune(root: Path, lo: str, hi: str, pending: set[str]) -> tuple[int, int, int]:
    freed = pruned = stuck = 0
    for kind in KINDS:
        for d in sorted((root / kind).glob("date=*")):
            if not (lo <= d.name.split("=", 1)[1] <= hi):
                continue
            for hour in sorted(d.glob("hour=*")):
                marker = hour / "_gapfill"
                if not marker.exists():
                    continue                      # in-flight, no marker yet
                held = 0
                for f in sorted(hour.iterdir()):
                    if not f.is_file() or f.name == "_gapfill":
                        continue
                    if str(f.relative_to(root)) in pending:
                        stuck += 1                # not yet remote, keep for next pass
                        held += 1
                        continue
                    try:
                        sz = f.stat().st_size
                        f.unlink()
                    except FileNotFoundError:
                        continue                  # a concurrent pass won the race
                    freed += sz
                    pruned += 1
                # Invariant: a completion marker living inside the directory a sweep
                # iterates MUST be excluded from that sweep, or it eventually deletes its
                # own gate. The original swept every non-pending file in a marked hour,
                # and _gapfill is a file that is never in `pending` - so any pass with a
                # part still uploading unlinked the marker, and the next pass's gate then
                # skipped the hour forever, stranding that part locally for good.
                # Here the marker outlives every part it gates: it goes only once the
                # hour holds nothing else, which is exactly when its job is done.
                #
                # It must ALSO be proven remote before it goes, exactly like a part. The
                # marker is written when its day completes, which can land after this
                # pass's pending snapshot was taken; deleting it then would destroy the
                # only record that the hour was ever filled, since local is pruned and R2
                # never received it. That is how tu 2026-04-17 ended up in R2 with 22
                # parts and no markers. If it is still pending, keep it - the next pass
                # uploads it and then it can go.
                if held == 0 and str(marker.relative_to(root)) not in pending:
                    marker.unlink(missing_ok=True)
                elif held == 0:
                    stuck += 1
    # Tidy only inside the chunk range: walking the whole archive can rmdir an hour-dir
    # the live archiver just created and is about to write into.
    for kind in KINDS:
        for d in sorted((root / kind).glob("date=*"), reverse=True):
            if not (lo <= d.name.split("=", 1)[1] <= hi):
                continue
            for sub in sorted(d.glob("hour=*"), reverse=True):
                if not any(sub.iterdir()):
                    sub.rmdir()
            if not any(d.iterdir()):
                d.rmdir()
    return pruned, freed, stuck


def demo() -> None:
    """Self-check: the three gates each have to actually hold a file back."""
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)

        def part(kind, day, hour, marker=True, name="part-gapfill-x.parquet"):
            h = root / kind / f"date={day}" / f"hour={hour}"
            h.mkdir(parents=True, exist_ok=True)
            (h / name).write_bytes(b"x" * 100)
            if marker:
                (h / "_gapfill").touch()
            return h / name

        in_range = part("tu", "2026-04-10", "00")                  # prunable
        no_marker = part("tu", "2026-04-11", "00", marker=False)   # gate 2 holds it
        out_range = part("tu", "2026-05-02", "00")                 # gate 1 holds it
        live = part("vp", "2026-08-23", "12", marker=False)        # live capture
        pend = part("alerts", "2026-04-12", "00")                  # gate 3 holds it
        # an hour with one verified and one still-pending part
        mixed_ok = part("tu", "2026-04-13", "00", name="part-a.parquet")
        mixed_pend = part("tu", "2026-04-13", "00", name="part-b.parquet")

        pending = {str(pend.relative_to(root)), str(mixed_pend.relative_to(root))}
        pruned, freed, stuck = prune(root, "2026-04-01", "2026-04-30", pending)

        assert not in_range.exists(), "marker+verified file should have been pruned"
        assert no_marker.exists(), "GATE 2 FAILED: pruned an unmarked (mid-write) part"
        assert out_range.exists(), "GATE 1 FAILED: pruned outside the chunk date range"
        assert live.exists(), "GATE 1 FAILED: pruned a live-capture part"
        assert pend.exists(), "GATE 3 FAILED: pruned a part not yet proven remote"
        assert pruned == 2 and freed == 200 and stuck == 2, (pruned, freed, stuck)

        # A fully drained hour lets its marker go, so the dir disappears like March's did.
        assert not in_range.parent.exists(), "drained hour-dir should be gone"
        # But an hour still holding a pending part MUST keep its marker, or the next
        # pass's gate would skip the hour and strand that part forever.
        assert not mixed_ok.exists(), "verified part in a mixed hour should be pruned"
        assert mixed_pend.exists(), "pending part must survive"
        assert (mixed_pend.parent / "_gapfill").exists(), \
            "STRAND BUG: marker dropped while a part is still pending"

        # An hour whose parts are all verified but whose MARKER is not yet uploaded must
        # keep the marker: deleting it would erase the only record the hour was filled,
        # because local is about to be pruned and R2 never got it.
        late = part("tu", "2026-04-14", "00")
        late_marker = str((late.parent / "_gapfill").relative_to(root))
        still_pending = {late_marker, str(mixed_pend.relative_to(root)),
                         str(pend.relative_to(root))}
        n3, _, _ = prune(root, "2026-04-01", "2026-04-30", still_pending)
        assert n3 == 1, n3
        assert not late.exists(), "verified part should be pruned"
        assert (late.parent / "_gapfill").exists(), \
            "MARKER-LOSS BUG: deleted a marker that was never uploaded"

        # final pass, everything now uploaded: stragglers prune and both dirs go
        pruned2, _, stuck2 = prune(root, "2026-04-01", "2026-04-30", set())
        assert not mixed_pend.exists(), "STRAND BUG: straggler unprunable on next pass"
        assert not mixed_pend.parent.exists(), "hour should be gone after full drain"
        assert not late.parent.exists(), "hour should be gone once its marker uploaded"
        assert pruned2 == 2 and stuck2 == 0, (pruned2, stuck2)
        print("prune self-check OK: gates hold, no strand, no marker loss, dirs removed")


if __name__ == "__main__":
    if len(sys.argv) == 2 and sys.argv[1] == "demo":
        demo()
        raise SystemExit(0)
    lo, hi, pending_path, root = sys.argv[1], sys.argv[2], sys.argv[3], Path(sys.argv[4])
    pend = {l.strip() for l in open(pending_path) if l.strip()}
    n, freed, stuck = prune(root, lo, hi, pend)
    print(f"  pruned {n} files ({freed/1e9:.2f} GB); {stuck} not-yet-remote kept")
