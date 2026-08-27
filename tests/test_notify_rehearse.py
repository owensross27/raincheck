"""Notify ticket 12: the end-to-end rehearsal's own pins.

The rehearsal is `make notify-rehearse` (`python -m raincheck.notify_rehearse`); it is a
check harness, so what these tests pin is that its rows PASS, that the rows CAN fail
(canaries — an absence scan that cannot fail proves nothing), and that neither the module
nor this file is itself the grep hit that fails `make release-check` row 5: the retired
claim's needle is built at runtime and proved against `release_check.RETIRED`.

Module names are spelled in full: `raincheck.notify_render` and `raincheck.notify_replay`
both read as `nr`, and this ticket touches both.

The real-root half replays 2023-09-29 and the roll event through the detector's own walk
and compares every chain to the committed `research/notify-11-replay.json` row. It skips
only where the universe is absent (the resolved data root holds no part files) — the skip
is keyed on the universe, never on the env var, so the main checkout runs it for real.
"""
import ast
import re
from datetime import timezone
from pathlib import Path

import pytest

from raincheck import flood_detect as fd
from raincheck import notify_decide as nd
from raincheck import notify_rehearse
from raincheck import notify_render
from raincheck import notify_replay
from raincheck import notify_store as ns
from raincheck import release_check
from raincheck.paths import data_root

SRC = Path(notify_rehearse.__file__).read_text()
SELF = Path(__file__).read_text()
UTC = timezone.utc


@pytest.fixture(scope="module")
def checks() -> list[tuple[bool, str, str]]:
    """The synthetic rehearsal, run once: real `fd.cycle` payloads, no data root."""
    return notify_rehearse.synthetic()


# ---- the synthetic half passes, and covers the measured branch list ----------------------

def test_every_synthetic_row_passes(checks):
    bad = [(row, ev) for ok, row, ev in checks if not ok]
    assert bad == [], bad


def test_the_coverage_is_the_measured_branch_list(checks):
    """One row per branch the spec's list names. The list is notify 11's MEASURED one:
    every state here is reachable (or, for WINDOW_CAPPED, measured unreachable and
    therefore synthetic) — a rehearsal missing a row is rehearsing a different notifier."""
    rows = "\n".join(r for _, r, _ in checks)
    for needed in ("watch ENTRY", "watch HOLD", "tier ENTRY", "tier HOLD",
                   "ELEVATED sends with the opt-in", "HIGH notifies without any opt-in",
                   "quiet hours DROP", "never a deferral",
                   "HIGH is never suppressed by quiet hours", "suppress EVERYTHING",
                   "DUSK sends", "version skew is silent",
                   "insufficient_data is silent", "window_capped is silent",
                   "winter_gate is silent", "per-handle cap clips a TIER-branch escalation",
                   "drain the store to zero", "deployment facts are still unset",
                   # the string rows — notify 09's list, present, conditional and absent
                   "frozen operating-truth string rides verbatim",
                   "estimand and its note", "within_cell and cutpoint_basis",
                   "Window block is the detector's", "all three gate panel strings",
                   "four stamps and the asset id", "names the real handler",
                   "no-skill claim rides on exactly the messages that carry it",
                   "provisional-cutpoints note appears only where a tier is claimed",
                   "needle really is the retired claim",
                   "retired claim appears nowhere", "word None appears in no",
                   "audit field cutpoints_confirmed_by", "second-scale urgency",
                   "barred water list is written around the frozen string",
                   "no observed water", "List-Unsubscribe-Post",
                   "handle's own store token"):
        assert needed in rows, needed


def test_window_capped_is_named_as_the_one_synthetic_only_state(checks):
    """0 of 4,326 real cycles reach it (flood 12 and notify 11 both measured zero), so it
    is the one hand-edited payload and the rehearsal says so in its own evidence."""
    ev = next(e for ok, r, e in checks if "window_capped" in r)
    assert "synthetic-only" in ev and "4,326" in ev


def test_the_absence_rows_scan_messages_that_exist(checks):
    """An absence row over zero messages passes on nothing; the string rows must report
    the number of messages they scanned."""
    ev = next(e for ok, r, e in checks if r == "the word None appears in no rendered message")
    assert re.search(r"all [1-9]\d* messages", ev)


# ---- the needle: built at runtime, proved against the gate's own regex -------------------

def test_the_needle_really_is_the_retired_claim():
    assert re.search(release_check.RETIRED, notify_rehearse._needle())


def test_the_needle_is_built_at_runtime_so_neither_file_is_a_grep_hit():
    assert notify_rehearse._needle() not in SRC
    assert notify_rehearse._needle() not in SELF
    assert release_check.RETIRED not in SRC.replace("release_check.RETIRED", "")
    assert release_check.RETIRED not in SELF.replace("release_check.RETIRED", "")


# ---- the barred lists can fail, and are written around the frozen string -----------------

def test_the_barred_lists_would_catch_a_message_that_broke_them():
    assert any(x in "bus:400070 is flooded right now" for x in notify_rehearse.WATER_BARRED)
    assert any(x in "arrives in 1-2 min" for x in notify_rehearse.URGENCY_BARRED)


def test_the_water_list_does_not_ban_the_honesty_string():
    """notify 01's frozen sentence contains 'an observation of water'; a list that matched
    it would fail every honest message."""
    frozen = release_check.frozen_string()
    assert frozen and "an observation of water" in frozen
    assert not any(x in frozen.lower() for x in notify_rehearse.WATER_BARRED)


def test_the_string_rows_can_fail_on_a_corpus_that_breaks_the_rules(monkeypatch):
    """The harness's own canary: an absence scan that cannot fail proves nothing, so a
    corpus with the barred words injected must turn rows red. The message is
    hand-constructed (rendering is honest, so a violating corpus cannot come out of
    `notify_render.render`) and the injection rides `_open`'s seam."""
    from datetime import datetime
    m = nd.Message(handle="a@replay.invalid", asset_id="bus:1", asset_kind="bus_stop",
                   branch=nd.WATCH, tier=None, rank=1.0, top_n=25, window_id="w|s|d",
                   anchor="2021-09-01T21:00:00-04:00",
                   now=datetime(2021, 9, 1, 16, tzinfo=UTC),
                   unsubscribe_token="tok", score_version="s", detector_version="d")
    det, s = fd.constants(), notify_render.strings()
    frozen = release_check.frozen_string()
    clean = notify_rehearse.string_rows([("canary", m)], det, s, frozen)
    real_open = notify_rehearse._open

    def poisoned(msg):
        w, b, p = real_open(msg)
        bad = " None immediately, the stop is flooded, " + notify_rehearse._needle()
        return w + bad, b + bad, p

    monkeypatch.setattr(notify_rehearse, "_open", poisoned)
    red = notify_rehearse.string_rows([("canary", m)], det, s, frozen)
    flipped = [r for (ok0, r, _), (ok1, _, _) in zip(clean, red) if ok0 and not ok1]
    assert len(flipped) >= 4, flipped  # None, retired claim, urgency, observed water


# ---- fixtures are the store's shape; nothing sends; nothing is aliased nr ----------------

def test_the_subscription_fixture_is_the_stores_shape():
    rows = notify_replay.subscribers([("bus:1", "bus_stop")], 1)
    assert tuple(rows[0]) == ns.COLUMNS
    assert tuple(dict(rows[0], elevated_optin=0)) == ns.COLUMNS  # the opt-out copy too


def test_nothing_here_sends():
    """The bound imports, walked from the AST — a substring scan cannot see an unused
    import and prose poisons it [TRAPS]. Transport is a HITL step that does not exist."""
    tree = ast.parse(SRC)
    bound = {a.asname or a.name for n in ast.walk(tree)
             if isinstance(n, (ast.Import, ast.ImportFrom))
             for a in n.names} | {n.module for n in ast.walk(tree)
                                  if isinstance(n, ast.ImportFrom) and n.module}
    assert not bound & {"smtplib", "socket", "subprocess", "requests"}


def test_neither_nr_module_is_ever_aliased():
    """`notify_render` and `notify_replay` both read as `nr`; the rehearsal files spell
    them in full, every time."""
    for text in (SRC, SELF):
        assert not re.search(r"import\s+notify_(?:render|replay)\s+as\s", text)


def test_the_rehearsal_leaves_the_deployment_facts_unset(checks):
    """`checks` has already rendered messages; the tree's tripwire constants must still
    be None — the rehearsal passes explicit keyword arguments and sets nothing."""
    assert notify_render.PANEL_URL is None and notify_render.UNSUBSCRIBE_TO is None


def test_the_policies_come_from_the_artifact_and_no_branch_is_typed():
    """Both branches are selected by flipping `cutpoints.provisional` on a COPY of the
    artifact and asking `nd.policy` again — never a `Policy(branch=...)`. The flip idiom
    appears in the source; a constructed Policy does not."""
    assert "provisional=True" in SRC and "provisional=False" in SRC
    assert "Policy(branch" not in SRC
    det = fd.constants()
    assert nd.policy(dict(det, cutpoints=dict(det["cutpoints"], provisional=False))).branch \
        == nd.TIER


# ---- the real half: the detector's own walk, against the committed rows ------------------

def _root_or_skip(*parts):
    root = data_root()
    if not any(Path(str(root)).joinpath(*parts).rglob("*.parquet")):
        pytest.skip(f"no {'/'.join(parts)} part files under {root}")
    return root


@pytest.fixture(scope="module")
def real_checks() -> list[tuple[bool, str, str]]:
    _root_or_skip("gold", "flood_matrix")
    _root_or_skip("gold", "flood_exposure")
    _root_or_skip("silver", "flood_events")
    return notify_rehearse.real()


def test_every_real_row_passes(real_checks):
    bad = [(row, ev) for ok, row, ev in real_checks if not ok]
    assert bad == [], bad


def test_the_real_half_proves_parity_roll_and_the_fuse(real_checks):
    """The named event and the roll event both reproduce their committed notify-11 rows
    chain for chain, the roll is a real mid-storm Window roll (never a score_version
    swap), and the fuse clip rides the top_scored cohort — the measured branch list."""
    rows = "\n".join(r for _, r, _ in real_checks)
    assert f"{notify_rehearse.NAMED_EVENT}: every chain reproduces the committed" in rows
    assert rows.count("every chain reproduces the committed") == 2
    assert rows.count("message-keeping walk IS the replay's walk") == 2
    assert "the per-cycle fuse CLIPS on the top_scored cohort" in rows
    assert "Window ROLLED mid-event" in rows
    assert "real over-expectation event" in rows


def test_the_roll_event_is_read_off_the_committed_asset():
    """The pick is derived from `research/notify-11-replay.json`'s own over-expectation
    rows (windows > 1), not typed — and it is never the named event."""
    import json
    oracle = json.loads(notify_replay.OUT.read_text())
    ids = {o["event_id"] for o in oracle["over_expectation"]
           if o["rule"] == notify_replay.PER_SUB and o["windows"] > 1}
    assert ids, "history holds real mid-storm rolls"
    assert max(ids) != notify_rehearse.NAMED_EVENT
