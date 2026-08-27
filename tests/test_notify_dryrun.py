"""Notify ticket 10: the dry-run seam, on REAL detector payloads.

The read under every test is `fd.cycle`'s own output over flood 11's Ida fixture (the
test_notify_decide recipe), never a hand-shaped stub, and the store rows go through
ticket 07's own `connect()` schema — a stub in the wrong shape is how a green suite
hides a real defect [TRAPS]. `now` is pinned on fixed epochs inside Ida; NOON
(16:00 UTC = 12:00 New York) is outside the quiet window and NIGHT (06:00 UTC = 02:00
New York) is inside it.

What is deliberately NOT re-tested here: the decision's own rules (quiet hours, caps,
fuse, branches — test_notify_decide) and the renderer's wording (test_notify_render).
This seam's claims are wiring claims: chained state, the loop's clock, drops never
rendered, refusals as fields, and no send path existing at all.
"""
import ast
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from raincheck import flood_detect as fd
from raincheck import flood_exposure as fe
from raincheck import notify_dryrun
from raincheck import notify_render as nr
from raincheck import notify_store as ns

FIX = Path(__file__).parent / "fixtures" / "flood_detect_ida.json"
SRC = Path(notify_dryrun.__file__).read_text()

NOON = datetime(2021, 9, 1, 16, tzinfo=timezone.utc)
NIGHT = datetime(2021, 9, 2, 6, tzinfo=timezone.utc)

SUB = ("a@example.com", "bus:400070", "bus_stop", 0, "2021-09-01T00:00:00+00:00", "tok-a")


@pytest.fixture(scope="module")
def det() -> dict:
    return fd.constants()


@pytest.fixture(scope="module")
def read(det) -> dict:
    """One REAL detector read with a real gated HIGH in it (the Ida fixture at its peak),
    exactly as `flood_panel._tick` would hand it to this seam via state["read"]."""
    f = json.loads(FIX.read_text())
    dt = datetime.fromisoformat
    hours = [{"cell": c["cell"], "hour_end_utc": dt(h), "mm_1h": mm}
             for c in f["cells"] for h, mm in c["hourly"].items()]
    wet = {dt(k): v for k, v in f["wet_counts"].items()}
    units = [dict(p) for p in f["points"]]
    cell = f["cells"][0]["cell"]
    for c in f["cells"]:
        units.append({"asset_id": f"cell:{c['cell']:x}", "kind": "cell", "cell": c["cell"]}
                     | {k: c["matrix"][k] for k in ("share_deep", "share_nuisance",
                                                    "share_not_analyzed", "density_311_3y")})
    units.append({"asset_id": f["complex_asset_id"], "kind": "complex",
                  "complex_id": f["complex_id"], "cell": cell})
    art = fe.coefficients()
    out = fd.cycle(None, dt(f["peak_hour_utc"]), hours, units, art, det,
                   temp_c=22.0, table_score_version=art["score_version"],
                   wet_by_hour=wet)
    assert out["window"]["state"] == fd.OK and out["latched"], "degenerate fixture"
    return out


@pytest.fixture
def flood(read, det) -> dict:
    """The slice of flood 15's tick state this seam reads."""
    return {"skipped": False, "error": None, "read": read, "det": det}


@pytest.fixture
def root(tmp_path) -> Path:
    """A data root whose store holds one active subscription to a Unit the fixture
    ranks into the watch top-N — inserted through the store's own schema."""
    con = ns.connect(ns.db_path(tmp_path))
    con.execute("INSERT INTO subscriptions VALUES (?, ?, ?, ?, ?, ?, 'active')", SUB)
    con.commit()
    con.close()
    return tmp_path


def test_the_subscription_row_is_the_stores_own_shape(root):
    """The planted row, read back through the store's own schema, is exactly COLUMNS."""
    con = ns.connect(ns.db_path(root))
    row = dict(con.execute("SELECT * FROM subscriptions").fetchone())
    con.close()
    assert tuple(row) == ns.COLUMNS
    assert row["asset_kind"] in ns.KINDS and row["state"] == ns.STATES[0]


def test_a_fresh_read_is_decided_and_the_tree_refusal_is_the_recorded_outcome(root, flood):
    """The dry-run decides, and today every rendered message REFUSES: `nr.PANEL_URL` and
    `nr.UNSUBSCRIBE_TO` are unset deployment facts, so the correct state on this tree is
    rendered=0 with the refusal recorded — not a placeholder URL."""
    s = notify_dryrun.dryrun(root, None, flood, NOON)
    assert s["decided"] is True and s["error"] is None
    assert s["summary"]["messages"] == 1 and s["summary"]["branch"] == "watch"
    assert s["rendered"] == 0 and s["unrendered"] == 1
    assert "PANEL_URL" in s["unrendered_reason"]
    assert s["d"].messages[0].now == NOON, "the seam hands decide() the loop's own clock"


def test_render_renders_once_the_deployment_facts_exist(root, flood, monkeypatch):
    """Same seam, facts provided the tripwire-safe way (test-locally, tree untouched):
    the message renders and the state says so."""
    monkeypatch.setattr(nr, "PANEL_URL", "https://panel.invalid/")
    monkeypatch.setattr(nr, "UNSUBSCRIBE_TO", "ops@example.invalid")
    s = notify_dryrun.dryrun(root, None, flood, NOON)
    assert s["rendered"] == 1 and s["unrendered"] == 0 and s["unrendered_reason"] is None


def test_the_decision_state_chains_so_an_entry_fires_once(root, flood):
    """The Decision is its own `previous`. Run the SAME read twice through the real seam:
    the watched ledger carries, so the second cycle owes nothing — a broken chain would
    re-message every cycle, which is the one-resend-per-Window property lost."""
    first = notify_dryrun.dryrun(root, None, flood, NOON)
    second = notify_dryrun.dryrun(root, first, flood, NOON)
    assert first["summary"]["messages"] == 1
    assert second["summary"]["messages"] == 0 and second["summary"]["drops"] == 0
    assert second["error"] is None and second["decided"] is True


def test_a_night_cycle_that_drops_everything_is_correct_and_renders_nothing(root, flood,
                                                                            monkeypatch):
    """notify 11, measured: on watch nothing is urgent, so quiet hours suppress EVERY
    message — the largest drop reason on every chain. A dry-run at night that drops
    everything is the policy working. And a DROP is never rendered: the render seam is
    not even consulted."""
    calls = []
    monkeypatch.setattr(nr, "render", lambda m, **kw: calls.append(m) or b"")
    s = notify_dryrun.dryrun(root, None, flood, NIGHT)
    assert s["summary"]["messages"] == 0
    assert s["summary"]["dropped"] == {"quiet_hours": 1}
    assert calls == [], "d.messages only; a drop is a ledger row, never a queue"


def test_a_decide_refusal_is_a_field_on_state_and_the_ledger_survives(root, flood,
                                                                      monkeypatch):
    """`nd.decide` raises on an inconsistent store row BY DESIGN; this seam is the catch
    its docstring says that raise belongs inside. The store's own schema and
    `subscriptions()`'s active-only filter make such a row unreachable through SQL here,
    so the read seam is stubbed to hand decide() one — the refusal itself is the REAL
    one. The previous Decision is carried, so a poisoned store costs cycles, not the
    Window's ledger."""
    good = notify_dryrun.dryrun(root, None, flood, NOON)
    bad = dict(zip(ns.COLUMNS, SUB + ("paused",)))
    monkeypatch.setattr(ns, "subscriptions", lambda con: [bad])
    s = notify_dryrun.dryrun(root, good, flood, NOON)
    assert s["error"] is not None and "ValueError" in s["error"]
    assert s["decided"] is False
    assert s["d"] is good["d"], "the chained Decision is carried through the failure"


def test_skipped_errored_and_readless_flood_cycles_carry_without_touching_the_store(
        tmp_path, read, det):
    """No fresh read, no decision — and no store read either: the subscriptions.db that
    `ns.connect` would create never appears."""
    cases = [({"skipped": True, "read": read, "det": det}, "flood_skipped"),
             ({"skipped": False, "error": "Boom", "read": read, "det": det}, "flood_error"),
             ({"skipped": False, "error": None, "read": None, "det": det}, "no_read"),
             (None, "no_read")]
    prev = {"d": "carried", "summary": {"messages": 9}}
    for flood, why in cases:
        s = notify_dryrun.dryrun(tmp_path, prev, flood, NOON)
        assert s["decided"] is False and s["why"] == why, (flood, why)
        assert s["d"] == "carried" and s["summary"] == {"messages": 9}
    assert not (tmp_path / "live" / "subscriptions.db").exists()


def test_the_log_line_prints_on_change_only_and_names_no_handle(root, flood, capsys):
    """One line when the summary MOVES, silence while it holds — 2,880 identical lines a
    day bury the cycle that mattered [the loop's own gated-publish rule]. Counts only:
    no handle, no token, and the line says nothing was sent."""
    s = notify_dryrun.dryrun(root, None, flood, NOON)
    s = notify_dryrun.dryrun(root, s, flood, NOON)
    notify_dryrun.dryrun(root, s, flood, NOON)
    out = capsys.readouterr().out
    lines = [ln for ln in out.splitlines() if ln.startswith("notify-dryrun:")]
    assert len(lines) == 2, "entry, then the settle to zero - the third, held cycle is silent"
    assert "NOT SENT" in lines[0]
    assert "a@example.com" not in out and "tok-a" not in out


def test_the_store_connection_is_opened_once_and_carried(root, flood, monkeypatch):
    opened = []
    real = ns.connect
    monkeypatch.setattr(ns, "connect", lambda p: opened.append(p) or real(p))
    s = notify_dryrun.dryrun(root, None, flood, NOON)
    notify_dryrun.dryrun(root, s, flood, NOON)
    assert len(opened) == 1, "the loop's warm-connection idiom: open once, carry on state"


def test_this_module_has_no_send_path_and_no_credential_path():
    """Email is the only channel and v1 does not send: nothing here may import a mail,
    socket or HTTP client, or read the environment for a credential. Pinned on the names
    the imports BIND (an unused import is invisible to an identifier scan [TRAPS])."""
    tree = ast.parse(SRC)
    bound = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            bound |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            bound |= {(node.module or "").split(".")[0]}
            bound |= {a.asname or a.name for a in node.names}
    barred = {"smtplib", "socket", "ssl", "http", "urllib", "requests", "boto3",
              "botocore", "os", "subprocess"}
    assert not bound & barred, bound & barred
    calls = {n.func.attr for n in ast.walk(tree)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
    assert not calls & {"send", "sendmail", "send_message", "post", "put"}, calls
