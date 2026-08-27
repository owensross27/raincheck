"""Notify ticket 07 (spec section 9; SEAM S): the subscription store, the operator
command, and the unsubscribe handler.

One SQLite table beside the notifier holding the minimum about a subscriber: contact
handle, asset id, asset kind, ELEVATED opt-in, consent timestamp, unsubscribe token,
state. The permitted column set is frozen in COLUMNS and asserted by test — no location
history, no IP, no analytics identifier ever enters this schema.

Subscriptions are asset_id grain, Unit kinds ONLY: `bus_stop` and `complex`. A station or
an entrance resolves to its complex before storage (Carriers are located and aggregated,
never scored on their own [CONTEXT.md]); Cells are not subscribable in v1 — nobody
subscribes to a hexagon.

There is NO HTTP write path in v1 (spec section 9: the ingress is DEFERRED, and cloud
ticket 07's NetworkPolicy exception stays undrawn). The list is maintained through this
module's command. `unsubscribe()` is a plain function that verifies an opaque token and
deletes that handle's rows — it is what an HTTP endpoint would call if one is ever built,
so deferring the ingress costs no redesign. DEFERRAL_TRIGGER below names what reopens it.

Run: python -m raincheck.notify_store list        (add / list / remove / unsubscribe)
"""
import argparse
import re
import secrets
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

import pyarrow.parquet as pq

from .paths import as_root, data_root

DB_NAME = "subscriptions.db"

# The permitted set, frozen. A column outside it is a privacy defect, not a feature.
COLUMNS = ("handle", "asset_id", "asset_kind", "elevated_optin", "consent_ts",
           "unsubscribe_token", "state")

KINDS = ("bus_stop", "complex")   # Unit kinds a subscription may name; Cell is excluded
STATES = ("active", "paused")     # only `active` rows are handed to the notify decision

# Spec section 9: "a stated maximum subscriptions per handle, so the per-cycle fuse in
# section 6 has a bounded worst case." Ticket 08's fuse may assume this ceiling.
MAX_PER_HANDLE = 10

# The deferral's named expiry, recorded where the operator command lives (ticket 07).
DEFERRAL_TRIGGER = (
    "The public ingress is DEFERRED: v1 has no HTTP write path. Any ONE of these reopens "
    "it as its own ticket (email-verified handles, no accounts, one minimal endpoint, "
    "caps and abuse guard) and draws cloud ticket 07's reserved NetworkPolicy exception: "
    "(1) the first person who is neither Ross nor an invited tester asks to subscribe; "
    "(2) the managed list passes 25 entries; "
    "(3) the map page is publicly announced."
)
INGRESS_TRIGGER_ENTRIES = 25

SCHEMA = f"""
CREATE TABLE IF NOT EXISTS subscriptions (
    handle            TEXT NOT NULL,
    asset_id          TEXT NOT NULL,
    asset_kind        TEXT NOT NULL CHECK (asset_kind IN {KINDS}),
    elevated_optin    INTEGER NOT NULL CHECK (elevated_optin IN (0, 1)),
    consent_ts        TEXT NOT NULL,
    unsubscribe_token TEXT NOT NULL,
    state             TEXT NOT NULL DEFAULT 'active' CHECK (state IN {STATES}),
    PRIMARY KEY (handle, asset_id)
) WITHOUT ROWID
"""  # WITHOUT ROWID: not even a surrogate identifier is kept


class Refused(Exception):
    """A typed refusal — `.name` is the error name a caller (or a future endpoint)
    branches on, never a bare traceback [spec section 5]."""

    def __init__(self, name: str, detail: str = ""):
        super().__init__(f"{name}: {detail}" if detail else name)
        self.name = name
        self.detail = detail


def db_path(root: Path | None = None) -> Path:
    """Beside the notifier: the export loop's data root, live/."""
    return (as_root(root) if root else data_root()) / "live" / DB_NAME


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    con.execute(SCHEMA)
    con.commit()
    return con


def clean_handle(handle: str) -> str:
    """The trust boundary: email is the only channel in v1, and the handle is the identity
    the cap counts — so it is normalised before anything else looks at it (otherwise
    A@B and a@b are two handles and the cap is bypassed by shifting case)."""
    h = handle.strip().lower()
    if len(h) > 254 or not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", h):
        raise Refused("bad_handle", handle)
    return h


def resolve_unit(root: Path, asset_id: str) -> tuple[str, str]:
    """(asset_id, kind) at subscribable grain: a station or entrance resolves to its
    complex, a Cell is refused, an id absent from ref/assets is refused."""
    t = pq.read_table(as_root(root) / "ref" / "assets",
                      columns=["asset_id", "kind", "parent_asset_id"])
    by_id = {a: (k, p) for a, k, p in zip(t.column("asset_id").to_pylist(),
                                          t.column("kind").to_pylist(),
                                          t.column("parent_asset_id").to_pylist())}
    hit = by_id.get(asset_id)
    if hit is None:
        raise Refused("unknown_asset", asset_id)
    kind, parent = hit
    if kind in KINDS:
        return asset_id, kind
    if parent and by_id.get(parent, (None,))[0] == "complex":
        return parent, "complex"   # Carrier -> its Unit, before storage
    raise Refused("not_subscribable", f"{asset_id} is a {kind}")


def add(con: sqlite3.Connection, handle: str, asset_id: str, root: Path | None = None,
        elevated: bool = False, now: datetime | None = None) -> dict:
    """Add one subscription at Unit grain and return the stored row. Refuses at the cap,
    so the per-cycle fuse's worst case stays bounded."""
    handle = clean_handle(handle)
    asset_id, kind = resolve_unit(data_root() if root is None else root, asset_id)
    rows = con.execute("SELECT asset_id, unsubscribe_token FROM subscriptions "
                       "WHERE handle = ? AND state = 'active'", (handle,)).fetchall()
    if any(r["asset_id"] == asset_id for r in rows):
        raise Refused("already_subscribed", f"{handle} {asset_id}")
    if len(rows) >= MAX_PER_HANDLE:
        raise Refused("too_many_subscriptions", f"{handle} is at the cap of {MAX_PER_HANDLE}")
    token = rows[0]["unsubscribe_token"] if rows else secrets.token_urlsafe(32)
    ts = (now or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat()
    con.execute("INSERT INTO subscriptions VALUES (?, ?, ?, ?, ?, ?, 'active')",
                (handle, asset_id, kind, int(elevated), ts, token))
    con.commit()
    return dict(con.execute("SELECT * FROM subscriptions WHERE handle = ? AND asset_id = ?",
                            (handle, asset_id)).fetchone())


def subscriptions(con: sqlite3.Connection, handle: str | None = None) -> list[dict]:
    """The active rows, in a stable order — what the notify decision (ticket 08) reads."""
    sql = "SELECT * FROM subscriptions WHERE state = 'active'"
    args: tuple = ()
    if handle is not None:
        sql, args = sql + " AND handle = ?", (clean_handle(handle),)
    return [dict(r) for r in con.execute(sql + " ORDER BY handle, asset_id", args)]


def remove(con: sqlite3.Connection, handle: str, asset_id: str | None = None) -> int:
    """Operator removal by handle (all rows) or by (handle, asset_id). Returns rows gone."""
    handle = clean_handle(handle)
    if asset_id is None:
        cur = con.execute("DELETE FROM subscriptions WHERE handle = ?", (handle,))
    else:
        cur = con.execute("DELETE FROM subscriptions WHERE handle = ? AND asset_id = ?",
                          (handle, asset_id))
    con.commit()
    return cur.rowcount


def unsubscribe(con: sqlite3.Connection, token: str) -> int:
    """THE handler: verify an opaque token and delete that handle's rows. A bad or already
    used token changes nothing and raises the typed refusal. An HTTP endpoint, if one is
    ever built, calls exactly this."""
    if not token or not con.execute("SELECT 1 FROM subscriptions WHERE unsubscribe_token = ?",
                                    (token,)).fetchone():
        raise Refused("unknown_token", "no subscription matches that token")
    cur = con.execute("DELETE FROM subscriptions WHERE unsubscribe_token = ?", (token,))
    con.commit()
    return cur.rowcount


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m raincheck.notify_store",
                                 description=__doc__.split("\n\n")[0],
                                 epilog=DEFERRAL_TRIGGER,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", type=Path, default=None)
    ap.add_argument("--root", type=Path, default=None, help="data root holding ref/assets")
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("add")
    a.add_argument("handle")
    a.add_argument("asset_id", help="bus:<id>, stn:<complex>, or a sta:/ent: that resolves")
    a.add_argument("--elevated", action="store_true", help="also notify on ELEVATED")
    ls = sub.add_parser("list")
    ls.add_argument("handle", nargs="?")
    rm = sub.add_parser("remove")
    rm.add_argument("handle")
    rm.add_argument("asset_id", nargs="?")
    sub.add_parser("unsubscribe").add_argument("token")
    # secrets.token_urlsafe opens with "-" about 3% of the time, and argparse reads a
    # dash-leading positional as an option (rc 2 - the one token its owner has cannot
    # unsubscribe them). The token is always the final positional, so shield it.
    argv = list(sys.argv[1:] if argv is None else argv)
    i = argv.index("unsubscribe") + 1 if "unsubscribe" in argv else len(argv)
    if i < len(argv) and argv[i].startswith("-") and argv[i] not in ("-h", "--help"):
        argv.insert(i, "--")
    args = ap.parse_args(argv)

    root = args.root or data_root()
    con = connect(args.db or db_path(root))
    try:
        if args.cmd == "add":
            r = add(con, args.handle, args.asset_id, root=root, elevated=args.elevated)
            print(f"added {r['handle']} -> {r['asset_id']} ({r['asset_kind']}, "
                  f"elevated={bool(r['elevated_optin'])}) consent {r['consent_ts']}")
            print(f"unsubscribe token: {r['unsubscribe_token']}")
        elif args.cmd == "list":
            rows = subscriptions(con, args.handle)
            for r in rows:
                print(f"{r['handle']}\t{r['asset_id']}\t{r['asset_kind']}\t"
                      f"elevated={bool(r['elevated_optin'])}\t{r['consent_ts']}\t{r['state']}")
            print(f"{len(rows)} active subscriptions (cap {MAX_PER_HANDLE} per handle)")
            if len(rows) >= INGRESS_TRIGGER_ENTRIES:
                print(f"INGRESS TRIGGER FIRED: {len(rows)} >= {INGRESS_TRIGGER_ENTRIES} "
                      f"entries. {DEFERRAL_TRIGGER}", file=sys.stderr, flush=True)
        elif args.cmd == "remove":
            print(f"removed {remove(con, args.handle, args.asset_id)} rows")
        else:
            print(f"unsubscribed {unsubscribe(con, args.token)} rows")
    except Refused as e:
        print(f"refused: {e}", file=sys.stderr, flush=True)
        return 1
    finally:
        con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
