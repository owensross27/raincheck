"""SEAM S (notify ticket 07): the subscription store, its schema, and the unsubscribe
handler, asserted by reading the store back with SQL.

Prior art: tests/test_cloud_scripts.py (a script asserted without standing up the
infrastructure behind it) and tests/test_flood_labels.py's registry fixture — the same
real `ref/assets` cut (3,112 rows: complexes, stations, entrances, bus stops and Cells)
is copied into a temp data root, so the resolve rules run against real asset ids and real
parent links rather than a hand-made shape.

No Spark, no network, no clock read: consent timestamps are pinned on a fixed epoch
(`fixture-clock-equals-wall-clock`).
"""
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest

from raincheck import notify_store as ns

FIXTURES = Path(__file__).parent / "fixtures"
NOW = datetime(2026, 8, 24, 15, 30, tzinfo=timezone.utc)   # fixed epoch, never wall clock
HANDLE = "ross@example.com"
BUS = "bus:100020"          # a real bus_stop Unit
CX = "stn:293"              # Van Cortlandt Park-242 St, a real complex Unit
STA = "sta:101"             # its station Carrier -> must land as stn:293
ENT = "ent:103:40.720000:-73.993546"   # an entrance Carrier -> stn:103
CELL = "cell:882a100029fffff"          # a scored Cell: still never subscribable


@pytest.fixture(scope="module")
def root(tmp_path_factory):
    r = tmp_path_factory.mktemp("notify07")
    (r / "ref" / "assets").mkdir(parents=True)
    shutil.copy(FIXTURES / "flood_labels_assets.parquet",
                r / "ref" / "assets" / "part-00000.parquet")
    return r


@pytest.fixture
def con(root, tmp_path):
    c = ns.connect(tmp_path / "subs.db")
    yield c
    c.close()


def rows(con):
    """Read the store back with SQL, never through the module's own accessor."""
    return con.execute("SELECT handle, asset_id, asset_kind, elevated_optin, consent_ts, "
                       "unsubscribe_token, state FROM subscriptions "
                       "ORDER BY handle, asset_id").fetchall()


def test_schema_carries_no_column_outside_the_permitted_set(con):
    """The privacy stance is enforced by the schema, not by review: no location history,
    no IP, no analytics identifier can be stored because there is nowhere to put one."""
    cols = tuple(r[1] for r in con.execute("PRAGMA table_info(subscriptions)"))
    assert cols == ns.COLUMNS
    assert set(cols) == {"handle", "asset_id", "asset_kind", "elevated_optin",
                         "consent_ts", "unsubscribe_token", "state"}
    banned = ("ip", "addr", "location", "lat", "lon", "cell", "analytics", "user_agent",
              "device", "session", "referrer", "last_seen")
    assert not [c for c in cols if any(b in c for b in banned)]
    tables = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")]
    assert tables == ["subscriptions"]


def test_round_trip_add_decision_sees_it_unsubscribe_rows_gone(con, root):
    r = ns.add(con, HANDLE, BUS, root=root, now=NOW)
    assert (r["asset_id"], r["asset_kind"], r["state"]) == (BUS, "bus_stop", "active")
    assert r["consent_ts"] == "2026-08-24T15:30:00+00:00"   # the injected clock, not now()

    seen = ns.subscriptions(con)          # what the notify decision (ticket 08) reads
    assert [(s["handle"], s["asset_id"], s["elevated_optin"]) for s in seen] == \
           [(HANDLE, BUS, 0)]

    assert ns.unsubscribe(con, r["unsubscribe_token"]) == 1
    assert rows(con) == []                # asserted with SQL, not with subscriptions()


def test_one_token_per_handle_removes_every_row_that_handle_has(con, root):
    a = ns.add(con, HANDLE, BUS, root=root, now=NOW)
    b = ns.add(con, HANDLE, CX, root=root, elevated=True, now=NOW)
    other = ns.add(con, "someone@else.org", BUS, root=root, now=NOW)
    assert a["unsubscribe_token"] == b["unsubscribe_token"]
    assert other["unsubscribe_token"] != a["unsubscribe_token"]

    assert ns.unsubscribe(con, a["unsubscribe_token"]) == 2
    assert [r["handle"] for r in rows(con)] == ["someone@else.org"]


def test_a_bad_or_reused_token_changes_nothing_and_returns_the_typed_refusal(con, root):
    r = ns.add(con, HANDLE, BUS, root=root, now=NOW)
    for bad in ("", "not-a-token", r["unsubscribe_token"][:-1]):
        with pytest.raises(ns.Refused) as e:
            ns.unsubscribe(con, bad)
        assert e.value.name == "unknown_token"
    assert len(rows(con)) == 1            # nothing changed

    ns.unsubscribe(con, r["unsubscribe_token"])
    with pytest.raises(ns.Refused) as e:  # the same token, a second time
        ns.unsubscribe(con, r["unsubscribe_token"])
    assert e.value.name == "unknown_token"
    assert rows(con) == []


def test_a_handle_past_the_maximum_is_refused_at_add_time(con, root):
    ids = [r["asset_id"] for r in
           _bus_ids(root)[:ns.MAX_PER_HANDLE + 1]]
    for i in ids[:ns.MAX_PER_HANDLE]:
        ns.add(con, HANDLE, i, root=root, now=NOW)
    with pytest.raises(ns.Refused) as e:
        ns.add(con, HANDLE, ids[ns.MAX_PER_HANDLE], root=root, now=NOW)
    assert e.value.name == "too_many_subscriptions"
    assert str(ns.MAX_PER_HANDLE) in e.value.detail
    assert len(rows(con)) == ns.MAX_PER_HANDLE          # the cap bounds the fuse
    ns.add(con, "second@example.com", ids[0], root=root, now=NOW)   # per handle, not global
    assert len(rows(con)) == ns.MAX_PER_HANDLE + 1


def test_the_cap_counts_the_same_handle_written_differently(con, root):
    ids = [r["asset_id"] for r in _bus_ids(root)[:ns.MAX_PER_HANDLE]]
    for i in ids:
        ns.add(con, HANDLE.upper() if len(i) % 2 else f"  {HANDLE} ", i, root=root, now=NOW)
    assert {r["handle"] for r in rows(con)} == {HANDLE}
    with pytest.raises(ns.Refused) as e:
        ns.add(con, HANDLE.title(), BUS, root=root, now=NOW)
    assert e.value.name in ("too_many_subscriptions", "already_subscribed")


@pytest.mark.parametrize("bad", ["", "   ", "nobody", "a@b", "two@at@signs.com",
                                 "has space@example.com", "x" * 250 + "@example.com"])
def test_a_handle_that_is_not_an_email_is_refused(con, root, bad):
    with pytest.raises(ns.Refused) as e:
        ns.add(con, bad, BUS, root=root, now=NOW)
    assert e.value.name == "bad_handle"


def test_carriers_resolve_to_their_complex_before_storage(con, root):
    for carrier, unit in ((STA, "stn:293"), (ENT, "stn:103")):
        r = ns.add(con, HANDLE, carrier, root=root, now=NOW)
        assert (r["asset_id"], r["asset_kind"]) == (unit, "complex")
    stored = {r["asset_id"] for r in rows(con)}
    assert stored == {"stn:293", "stn:103"} and STA not in stored and ENT not in stored


def test_a_station_and_its_complex_are_one_subscription(con, root):
    ns.add(con, HANDLE, CX, root=root, now=NOW)
    with pytest.raises(ns.Refused) as e:
        ns.add(con, HANDLE, STA, root=root, now=NOW)   # sta:101 IS stn:293
    assert e.value.name == "already_subscribed"
    assert len(rows(con)) == 1


def test_cells_are_never_subscribable_and_unknown_ids_are_refused(con, root):
    with pytest.raises(ns.Refused) as e:
        ns.add(con, HANDLE, CELL, root=root, now=NOW)
    assert e.value.name == "not_subscribable" and "cell" in e.value.detail
    with pytest.raises(ns.Refused) as e:
        ns.add(con, HANDLE, "bus:no-such-stop", root=root, now=NOW)
    assert e.value.name == "unknown_asset"
    assert rows(con) == []


def test_only_active_rows_reach_the_decision(con, root):
    ns.add(con, HANDLE, BUS, root=root, now=NOW)
    ns.add(con, HANDLE, CX, root=root, now=NOW)
    con.execute("UPDATE subscriptions SET state = 'paused' WHERE asset_id = ?", (CX,))
    con.commit()
    assert [s["asset_id"] for s in ns.subscriptions(con)] == [BUS]
    assert len(rows(con)) == 2
    with pytest.raises(sqlite3.IntegrityError):   # the schema, not the caller, owns states
        con.execute("UPDATE subscriptions SET state = 'zombie' WHERE asset_id = ?", (BUS,))
    with pytest.raises(sqlite3.IntegrityError):   # and the subscribable kinds
        con.execute("INSERT INTO subscriptions VALUES ('a@b.co', 'cell:x', 'cell', 0, "
                    "'2026-01-01T00:00:00+00:00', 'tok', 'active')")


def test_operator_remove_takes_one_row_or_the_whole_handle(con, root):
    ns.add(con, HANDLE, BUS, root=root, now=NOW)
    ns.add(con, HANDLE, CX, root=root, now=NOW)
    assert ns.remove(con, HANDLE, BUS) == 1
    assert [r["asset_id"] for r in rows(con)] == [CX]
    assert ns.remove(con, HANDLE) == 1
    assert rows(con) == []
    assert ns.remove(con, HANDLE) == 0        # removing nothing is not an error


def test_the_deferral_trigger_is_recorded_where_the_command_lives(capsys):
    with pytest.raises(SystemExit):
        ns.main(["--help"])
    helptext = capsys.readouterr().out
    for phrase in ("neither Ross nor an invited tester", "25 entries", "publicly announced"):
        assert phrase in helptext
    assert "NetworkPolicy exception" in ns.DEFERRAL_TRIGGER
    assert ns.INGRESS_TRIGGER_ENTRIES == 25


def test_the_command_adds_lists_and_removes(tmp_path, root, capsys):
    db = tmp_path / "cli.db"
    argv = ["--db", str(db), "--root", str(root)]
    assert ns.main(argv + ["add", HANDLE, STA, "--elevated"]) == 0
    out = capsys.readouterr().out
    assert "stn:293 (complex, elevated=True)" in out
    token = out.split("unsubscribe token: ")[1].strip()

    assert ns.main(argv + ["list"]) == 0
    assert "1 active subscriptions" in capsys.readouterr().out

    assert ns.main(argv + ["add", HANDLE, CELL]) == 1        # typed refusal, rc 1
    assert "refused: not_subscribable" in capsys.readouterr().err

    assert ns.main(argv + ["unsubscribe", token]) == 0
    assert "unsubscribed 1 rows" in capsys.readouterr().out
    with sqlite3.connect(db) as c:
        assert c.execute("SELECT count(*) FROM subscriptions").fetchone()[0] == 0
    assert ns.main(argv + ["unsubscribe", token]) == 1
    assert "refused: unknown_token" in capsys.readouterr().err


def test_a_dash_leading_unsubscribe_token_still_parses(tmp_path, root, capsys, monkeypatch):
    """secrets.token_urlsafe can open with "-", and argparse reads that as an option -
    caught live 2026-08-27 when the suite's random token opened with "-" and the CLI
    rc-2'd the one token its owner holds. The command must accept it positionally."""
    monkeypatch.setattr(ns.secrets, "token_urlsafe", lambda n: "-RIEw3Exx-pinned")
    db = tmp_path / "cli.db"
    argv = ["--db", str(db), "--root", str(root)]
    assert ns.main(argv + ["add", HANDLE, STA]) == 0
    token = capsys.readouterr().out.split("unsubscribe token: ")[1].strip()
    assert token.startswith("-")
    assert ns.main(argv + ["unsubscribe", token]) == 0
    assert "unsubscribed 1 rows" in capsys.readouterr().out


def test_no_http_ingress_ships_in_this_ticket():
    """v1 has no public write path of any kind: the module opens no socket and serves
    nothing. The handler above is the seam an endpoint would call instead."""
    src = Path(ns.__file__).read_text()
    for banned in ("http.server", "socket", "flask", "fastapi", "uvicorn", "urllib.request",
                   "bind(", "listen("):
        assert banned not in src


def _bus_ids(root):
    import pyarrow.parquet as pq
    t = pq.read_table(root / "ref" / "assets", columns=["asset_id", "kind"])
    return [{"asset_id": a} for a, k in zip(t.column("asset_id").to_pylist(),
                                            t.column("kind").to_pylist()) if k == "bus_stop"]
