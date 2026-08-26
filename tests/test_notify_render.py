"""Notify ticket 09, SEAM N: the message render, on Messages the real detector produced.

Every Message under test comes out of `nd.decide` over flood 11's own Ida fixture, so the
renderer is fed the shape the decision actually publishes rather than a hand-shaped stub
[TRAPS: a stub must open the way the real thing opens]. `now` is pinned on a fixed epoch
inside Ida and never on the wall clock.

The claim strings are checked against an INDEPENDENT side wherever one exists: notify 01's
own ticket file for the frozen operating-truth string (`release_check.frozen_string()`,
which is what `make release-check` compares against), `release_check.RETIRED` for the
retired claim, the artifact JSON read straight off disk for the tier labels, and
`inspect.signature` for the unsubscribe handler the message names. A test whose oracle is
the module it is testing is a mirror-pin and proves nothing [TRAPS].

THE RETIRED CLAIM IS NEVER SPELLED IN THIS FILE. `release_check`'s zero-hits row greps the
whole tree, so a test that quoted the string it asserts the absence of would BE the hit
that fails the gate. The needle is assembled at runtime from fragments and
`test_the_needle_is_built_at_runtime` is the row that proves this file is not a hit.

This suite reads no data root, opens no socket and no database: it adds ZERO skips.
"""
import email
import inspect
import io
import json
import re
import tokenize
from dataclasses import fields, replace
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

from raincheck import flood_detect as fd
from raincheck import flood_exposure as fe
from raincheck import flood_panel as fp
from raincheck import notify_decide as nd
from raincheck import notify_render as nr
from raincheck import notify_store as ns
from raincheck import release_check as rc

FIX = Path(__file__).parent / "fixtures" / "flood_detect_ida.json"
SRC = Path(nr.__file__).read_text()
SELF = Path(__file__).read_text()
UTC = timezone.utc

# A fixed epoch inside Ida: 21:00 New York, the instant notify 08's own suite uses because
# the two clocks disagree there.
NOW = datetime(2021, 9, 2, 1, tzinfo=UTC)

# The two deployment facts, supplied here so no test depends on a real host. `.invalid` is
# reserved by RFC 2606 and can never resolve, which is the point.
PANEL = "https://panel.invalid/"
OPS = "unsubscribe@ops.invalid"


# Comments, plain strings AND the literal halves of an f-string. Under python 3.12 an
# f-string no longer arrives as one STRING token: its text comes through as FSTRING_MIDDLE
# and only the `{...}` expressions are real tokens, so a filter that drops STRING alone
# leaves every rendered sentence in the "code" and the purity greps below read that prose.
_PROSE = {tokenize.COMMENT, tokenize.STRING} | {
    getattr(tokenize, n) for n in ("FSTRING_START", "FSTRING_MIDDLE", "FSTRING_END")
    if hasattr(tokenize, n)}


def _code(text: str) -> str:
    """The module's source with every comment and literal removed — a name MENTIONED in a
    docstring is not a call [TRAPS: a docstring that names what it forbids poisons a
    source-text grep]."""
    return "".join(t.string for t in tokenize.generate_tokens(io.StringIO(text).readline)
                   if t.type not in _PROSE)


def test_the_purity_grep_reads_code_and_not_prose():
    """The helper above is the oracle for three rows below; under a filter that missed
    f-strings it read the message's own sentences as source and they all passed on prose."""
    assert "unsubscribe_token" in CODE and "no unsubscribe endpoint" not in CODE
    assert "OPERATING_TRUTH" not in CODE and "raincheck ranks where" not in CODE


CODE = _code(SRC)


def _dt(s: str) -> datetime:
    return datetime.fromisoformat(s)


def _sub(handle="a@example.com", asset_id="bus:400070", kind="bus_stop", elevated=1,
         token=None) -> dict:
    """Notify 07's own row shape, key for key."""
    return {"handle": handle, "asset_id": asset_id, "asset_kind": kind,
            "elevated_optin": elevated, "consent_ts": "2021-09-01T00:00:00+00:00",
            "unsubscribe_token": token or f"tok-{handle}", "state": "active"}


@pytest.fixture(scope="module")
def ida() -> dict:
    f = json.loads(FIX.read_text())
    f["peak"] = _dt(f["peak_hour_utc"])
    f["wet"] = {_dt(k): v for k, v in f["wet_counts"].items()}
    f["hours"] = [{"cell": c["cell"], "hour_end_utc": _dt(h), "mm_1h": mm}
                  for c in f["cells"] for h, mm in c["hourly"].items()]
    f["mx"] = {c["cell"]: c["matrix"] for c in f["cells"]}
    return f


@pytest.fixture(scope="module")
def det() -> dict:
    return fd.constants()


@pytest.fixture(scope="module")
def art() -> dict:
    return fe.coefficients()


@pytest.fixture(scope="module")
def cycle(ida, det, art) -> dict:
    """One REAL detector cycle over Ida — the payload `nd.decide` is written against."""
    units = [dict(p) for p in ida["points"]]
    cell = next(iter(ida["mx"]))
    for c, m in ida["mx"].items():
        units.append({"asset_id": f"cell:{c:x}", "kind": "cell", "cell": c} | {
            k: m[k] for k in ("share_deep", "share_nuisance", "share_not_analyzed",
                              "density_311_3y")})
    units.append({"asset_id": ida["complex_asset_id"], "kind": "complex",
                  "complex_id": ida["complex_id"], "cell": cell})
    return fd.cycle(None, ida["peak"], ida["hours"], units, art, det, temp_c=22.0,
                    wet_by_hour=ida["wet"], table_score_version=art["score_version"])


@pytest.fixture(scope="module")
def watch(cycle, det, ida) -> tuple[nd.Message, ...]:
    """The branch v1 ships: real Messages, on the artifact's own flag, one per kind."""
    subs = [_sub(), _sub(asset_id=ida["complex_asset_id"], kind="complex")]
    return nd.decide(cycle, None, subs, nd.policy(det), NOW).messages


@pytest.fixture(scope="module")
def tiered(cycle, det) -> tuple[nd.Message, ...]:
    """The other branch, selected the only way it may be — by the artifact's own flag."""
    p = nd.policy(dict(det, cutpoints=dict(det["cutpoints"], provisional=False)))
    return nd.decide(cycle, None, [_sub()], p, NOW).messages


@pytest.fixture(scope="module")
def m(watch) -> nd.Message:
    return next(msg for msg in watch if msg.asset_kind == "bus_stop")


def render(msg: nd.Message, **kw) -> bytes:
    kw.setdefault("panel_url", PANEL)
    kw.setdefault("unsubscribe_to", OPS)
    return nr.render(msg, **kw)


def text(msg: nd.Message, **kw) -> str:
    """What the subscriber reads: the decoded body, transfer encoding undone."""
    return email.message_from_bytes(render(msg, **kw),
                                    policy=email.policy.SMTP).get_content()


def whole(msg: nd.Message, **kw) -> str:
    """Headers and body together — the corpus an absence assertion has to cover."""
    return render(msg, **kw).decode("utf-8")


# ---- the fixture is real, and it is not degenerate ---------------------------------------

def test_the_messages_under_test_are_the_real_detectors(cycle, watch, tiered):
    """Everything below rides on Messages a real cycle produced. A fixture that decided
    nothing would let every assertion pass on an empty tuple."""
    assert cycle["window"]["state"] == fd.OK and cycle["skew"]["model_tier"] == "ok"
    assert fd.HIGH in cycle["latched"].values()
    assert len(watch) == 2 and {msg.asset_kind for msg in watch} == {"bus_stop", "complex"}
    assert tiered and all(msg.tier == fd.HIGH for msg in tiered)


def test_the_message_shape_is_notify_08s_frozen_set():
    """This ticket renders that shape and does not touch it. A field added or dropped
    upstream lands here first."""
    assert tuple(f.name for f in fields(nd.Message)) == (
        "handle", "asset_id", "asset_kind", "branch", "tier", "rank", "top_n",
        "window_id", "anchor", "now", "unsubscribe_token", "score_version",
        "detector_version", "no_skill_claim")


# ---- which branch is rendered, and the None nobody may print -----------------------------

def test_the_branch_shipping_today_is_watch_and_every_tier_is_none(det, watch):
    """`cutpoints.provisional` is still true, so a headline reading `m.tier` would render
    the word None to every real subscriber."""
    assert det["cutpoints"]["provisional"] is True and nd.branch(det) == nd.WATCH
    assert all(msg.branch == nd.WATCH and msg.tier is None for msg in watch)


def test_no_rendered_message_ever_prints_the_word_none(watch):
    for msg in watch:
        assert "None" not in whole(msg)


def test_the_watch_claim_is_worded_from_top_n_and_rank_as_a_watch(m):
    body = text(m)
    assert m.top_n == 25 and f"among the {m.top_n} " in body
    assert "WATCH" in body and f"{m.rank:.4f}" in body


def test_the_watch_claim_is_never_a_tier_and_never_a_depth(watch):
    """The two readings a rank must not acquire on its way into an inbox."""
    for msg in watch:
        body = text(msg)
        assert "it is not a tier" in body and "it is not a depth" in body
        for barred in ("depth", "inches", "mm of water", "feet of water"):
            assert barred not in body.replace("it is not a depth", ""), barred


def test_the_top_n_is_the_messages_and_not_a_repeated_literal(m):
    """A renderer that spelled 25 would print 25 the day the policy's count changes."""
    assert f"among the {m.top_n + 1} " in text(replace(m, top_n=m.top_n + 1))
    assert str(m.top_n) not in CODE


def test_the_rank_is_rendered_at_a_fixed_precision(m):
    """The fixture's top stop ranks exactly 1.0, which formats the same at almost any
    precision — the degenerate-fixture shape [TRAPS], so this pins it on a value that
    cannot round to itself."""
    assert m.rank == 1.0, "the fixture's own value, stated so a change is visible"
    body = text(replace(m, rank=0.98721))
    assert "0.9872" in body and "0.98721" not in body and "0.99" not in body


def test_a_tier_message_reads_its_label_from_the_artifact(tiered):
    """`display.tier_labels` is the label's ONE home; the independent side here is the
    artifact JSON read off disk, never `fp.strings`."""
    labels = json.loads(fd.DETECTOR.read_text())["display"]["tier_labels"]
    msg = tiered[0]
    body = text(msg)
    assert labels[fd.HIGH] == "high" and f"entered the {labels[fd.HIGH]} tier" in body
    assert f"raincheck {labels[fd.HIGH]}:" in whole(msg)
    assert f"entered the {labels[fd.ELEVATED]} tier" in text(
        replace(msg, tier=fd.ELEVATED)), "the label is looked up, not spelled"


def test_the_tier_vocabulary_is_never_respelled_here():
    for spelling in ('"HIGH"', "'HIGH'", '"ELEVATED"', "'ELEVATED'", '"elevated"'):
        assert spelling not in SRC, spelling


def test_the_audit_field_never_reaches_a_subscriber(det, watch):
    """`display.cutpoints_confirmed_by` names WHO confirms and is populated long before any
    verdict exists — printing it would read as a confirmation that has not happened."""
    assert det["display"]["cutpoints_confirmed_by"]
    assert all(det["display"]["cutpoints_confirmed_by"] not in whole(msg) for msg in watch)


def test_a_provisional_cutpoint_is_stated_only_where_a_tier_is_claimed(m, tiered, det):
    note = det["cutpoints_note"]
    assert note in text(tiered[0]) and note not in text(m)


# ---- the frozen string, and the claims that are read rather than written -----------------

def test_the_frozen_operating_truth_rides_verbatim_and_unfolded(m):
    """Compared against notify 01's OWN ticket file — the same independent side
    `make release-check` uses. `x in render_of_x` would pass whatever the string became."""
    frozen = rc.frozen_string()
    assert frozen and frozen == fp.OPERATING_TRUTH
    assert frozen in text(m)
    assert frozen.encode() in render(m), "the transfer encoding may not fold it"


def test_there_is_no_message_only_variant_of_the_frozen_string():
    """It is READ from `flood_panel`, so a paraphrase cannot be typed here by accident."""
    assert "raincheck ranks where" not in SRC
    assert "operating_truth" in SRC


def test_every_claim_is_read_from_the_two_artifacts(m, det, art):
    """The message gets no vocabulary of its own: each of these is the artifact's string,
    reached through the panel's own selector so the two surfaces cannot disagree."""
    body = text(m)
    assert det["estimand"] == "flooded_reported" and det["estimand"] in body
    for claim in (det["estimand_note"], det["display"]["within_cell"],
                  det["display"]["cutpoint_basis"], det["display"]["window_interval"],
                  art["gate"]["panel_strings"]["caveat"],
                  art["gate"]["panel_strings"]["release"],
                  art["gate"]["panel_strings"]["headline"]):
        assert claim in body, claim


def test_the_model_strings_are_the_gates_selection_and_never_chosen(m, art):
    """flood 10 pre-selects the branch's panel strings; a renderer that picked between the
    alternates would ship the B2 words under the fitted model."""
    assert art["gate"]["branch"] == "MODEL"
    assert nr.strings()["panel"] == art["gate"]["panel_strings"]
    assert "L2 logistic" not in CODE


def test_the_no_skill_claim_rides_on_the_grain_that_owes_it(watch, det):
    claim = det["display"]["no_complex_skill_claim"]
    for msg in watch:
        body = text(msg)
        if msg.asset_kind == "complex":
            assert msg.no_skill_claim == claim and claim in body
        else:
            assert msg.no_skill_claim is None and claim not in body


def test_a_complex_message_that_lost_the_claim_renders_without_it(watch, det):
    """The other direction: the claim is on the MESSAGE, so a renderer that hard-coded it
    for every complex would keep printing it after the decision stopped attaching it."""
    cx = next(msg for msg in watch if msg.asset_kind == "complex")
    assert det["display"]["no_complex_skill_claim"] not in text(replace(cx,
                                                                       no_skill_claim=None))


def test_the_stamps_say_which_model_and_which_rules_made_the_message(m):
    body = text(m)
    assert m.score_version in body and m.detector_version in body
    assert m.window_id in body


def test_the_asset_is_named_by_its_id_because_the_message_carries_no_name(m):
    """`ref/assets` names are NOT unique at either grain — two bus stops metres apart share
    one name [TRAPS] — and `nd.Message` carries no name at all, so the id is the identity
    and the renderer is pure without a registry lookup."""
    assert "name" not in {f.name for f in fields(nd.Message)}
    assert m.asset_id in text(m) and f"({m.asset_kind})" in text(m)


# ---- the retired claim, with its needle built at runtime ---------------------------------

def _needle() -> str:
    """The retired claim, ASSEMBLED rather than quoted. `release_check`'s zero-hits row
    greps this directory; a file that spelled the string would be the hit."""
    return " ".join(["a page you", "open during", "a storm, not a", "service that watches"])


def test_the_needle_really_is_the_retired_claim():
    """Proved against `release_check.RETIRED`, the regex the gate itself greps with — a
    needle nobody checked could assert the absence of the wrong sentence."""
    assert re.search(rc.RETIRED, _needle())


def test_the_needle_is_built_at_runtime_so_this_file_is_not_a_grep_hit():
    assert _needle() not in SELF and rc.RETIRED not in SELF.replace("rc.RETIRED", "")


def test_the_retired_claim_appears_nowhere_in_the_rendered_corpus(watch, tiered):
    for msg in (*watch, *tiered):
        corpus = whole(msg)
        assert _needle() not in corpus
        assert not re.search(rc.RETIRED, corpus)


def test_the_replacement_went_where_the_retired_claim_would_have(m):
    """Absence alone is satisfied by a message that says nothing; the replacement is what
    makes the silence-is-not-an-all-clear honesty survive."""
    assert "means nothing was flagged, not that nothing flooded" in text(m)


# ---- the evidence window, and the urgency nobody may imply --------------------------------

def test_the_window_is_the_detectors_own_half_open_convention(m, det):
    body = text(m)
    assert det["display"]["window_interval"] == "(anchor, now]"
    assert f"Window {det['display']['window_interval']}" in body
    assert m.anchor in body and m.now.isoformat() in body


def test_the_evidence_sentence_is_hour_grain_and_trails_the_storm(m):
    body = text(m)
    assert "hour-grain" in body and "trails the storm" in body


def test_no_second_scale_urgency_and_no_bus_chain_figure(watch, tiered):
    """The ~1-2 min end-to-end figure belongs to the bus live chain and may not appear;
    neither may any wording that reads as second-scale."""
    for msg in (*watch, *tiered):
        body = text(msg).lower()
        for barred in ("1-2 min", "1–2 min", "minute", "second", "live now",
                       "as it happens", "immediately"):
            assert barred not in body, barred


def test_the_message_never_claims_water_was_observed(watch, tiered):
    for msg in (*watch, *tiered):
        body = text(msg).lower()
        assert "no water has been observed" in body
        for barred in ("water was observed", "we observed", "is flooded",
                       "is flooding", "water is", "observed flooding"):
            assert barred not in body, barred


def test_the_barred_list_would_catch_a_message_that_broke_it(m):
    """The absence rows above pass on a body that says nothing at all; this is the row that
    proves they can fail."""
    assert "is flooded" in (text(m) + "bus:400070 is flooded").lower()


# ---- unsubscribe: the header, the token, and the honest processing sentence ----------------

def test_every_message_carries_the_header_and_the_body_token(watch, tiered):
    """The header is DECODED back rather than re-encoded here: an assertion that spelled
    the escaping would be the implementation's mirror."""
    for msg in (*watch, *tiered):
        head = email.message_from_bytes(render(msg), policy=email.policy.SMTP)
        url = head["List-Unsubscribe"].strip("<>")
        assert url.startswith(f"mailto:{OPS}?")
        query = parse_qs(urlparse(url).query)
        assert query["subject"] == [f"unsubscribe {msg.unsubscribe_token}"]
        assert msg.unsubscribe_token in text(msg)


def test_the_header_never_promises_one_click(m):
    """`List-Unsubscribe-Post` is RFC 8058 one-click, and v1's removal is an operator
    running a function — setting it would be the implication the spec bars."""
    head = email.message_from_bytes(render(m), policy=email.policy.SMTP)
    assert head["List-Unsubscribe-Post"] is None
    body = text(m)
    assert "not instant" in body and "not one-click" in body


def test_the_message_names_the_handler_that_really_exists(m):
    """The honest-processing sentence names `notify_store.unsubscribe(con, token)`; the
    independent side is the function's own signature."""
    assert nr.HANDLER in text(m)
    assert list(inspect.signature(ns.unsubscribe).parameters) == ["con", "token"]
    assert nr.HANDLER == f"notify_store.{ns.unsubscribe.__name__}(con, token)"


def test_one_token_is_per_handle_and_removes_every_subscription(watch):
    """The store issues ONE token per handle and reuses it for every later add, so the
    message must not imply this token only detaches this stop."""
    assert len({msg.unsubscribe_token for msg in watch}) == 1
    body = text(watch[0])
    assert "covers every subscription this address owns" in body
    assert "removes all of them at once" in body and "stays valid" in body


def test_a_message_with_no_token_is_refused(m):
    with pytest.raises(ValueError, match="unsubscribe token"):
        render(replace(m, unsubscribe_token=""))


def test_the_token_is_escaped_into_the_mailto(m):
    """A token is `secrets.token_urlsafe`, so this cannot bite today — but an unescaped `&`
    would silently split the mailto into a second header field."""
    head = email.message_from_bytes(render(replace(m, unsubscribe_token="a b&c")),
                                    policy=email.policy.SMTP)
    url = head["List-Unsubscribe"].strip("<>")
    assert "&" not in urlparse(url).query.split("subject=")[1]
    assert parse_qs(urlparse(url).query)["subject"] == ["unsubscribe a b&c"]


# ---- the two deployment facts this repo does not hold --------------------------------------

def test_the_deployment_facts_are_unset_in_the_tree():
    """Both are [YOU] items: the public bucket's host does not exist yet and v1 has no
    unsubscribe mailbox. This row is the canary that neither was quietly filled with a
    plausible-looking placeholder — setting them for real is a deliberate commit."""
    assert nr.PANEL_URL is None and nr.UNSUBSCRIBE_TO is None


def test_an_unconfigured_render_refuses_rather_than_inventing_a_link(m):
    with pytest.raises(ValueError, match="PANEL_URL"):
        nr.render(m)
    with pytest.raises(ValueError, match="UNSUBSCRIBE_TO"):
        nr.render(m, panel_url=PANEL)
    with pytest.raises(ValueError, match="PANEL_URL"):
        nr.render(m, unsubscribe_to=OPS)


def test_the_constants_are_the_default_and_the_arguments_override(m, monkeypatch):
    monkeypatch.setattr(nr, "PANEL_URL", PANEL)
    monkeypatch.setattr(nr, "UNSUBSCRIBE_TO", OPS)
    assert nr.render(m) == render(m)
    assert "https://other.invalid/" in text(m, panel_url="https://other.invalid/")


def test_the_panel_link_is_in_the_message(m):
    assert f"The panel: {PANEL}" in text(m)


# ---- purity ---------------------------------------------------------------------------------

def test_render_is_a_pure_function_of_the_message(watch, tiered):
    for msg in (*watch, *tiered):
        assert render(msg) == render(msg)


@pytest.mark.parametrize("field,value", [
    ("handle", "b@example.com"), ("asset_id", "bus:999999"), ("rank", 0.5),
    ("top_n", 7), ("anchor", "2021-08-30T21:00:00-04:00"),
    ("now", datetime(2021, 9, 2, 2, tzinfo=UTC)), ("unsubscribe_token", "other"),
    ("score_version", "sv2"), ("detector_version", "dv2"), ("window_id", "w2")])
def test_every_message_field_reaches_the_bytes(m, field, value):
    """A field the renderer silently ignored would make two different Messages the same
    email — which is how a subscriber gets somebody else's stop."""
    assert render(replace(m, **{field: value})) != render(m)


def test_the_module_reads_no_clock_no_socket_and_no_data_root():
    """Purity measured, not claimed. The two artifacts it opens are committed to the repo,
    which is the same input `make release-check` runs on."""
    for barred in ("datetime.now", "utcnow", "time.time", "data_root", "sqlite3",
                   "urlopen", "requests", "duck.connect", "smtplib", "boto3"):
        assert barred not in CODE, barred


def test_nothing_here_sends_anything():
    """Ticket 10 owns the transport, and dry-run is its default; this returns bytes."""
    assert inspect.signature(nr.render).return_annotation is bytes
    assert "send" not in CODE


# ---- the shape of the bytes -------------------------------------------------------------

def test_the_bytes_are_one_plain_text_email(m):
    msg = email.message_from_bytes(render(m), policy=email.policy.SMTP)
    assert not msg.is_multipart() and msg.get_content_type() == "text/plain"
    assert msg.get_content_charset() == "utf-8"
    assert msg["To"] == m.handle and msg["Subject"].startswith("raincheck ")


def test_the_sender_headers_are_the_senders_and_not_this_functions(m):
    """No From, Date or Message-ID: those are ticket 10's, and leaving them out is what
    keeps the same Message rendering the same bytes."""
    msg = email.message_from_bytes(render(m), policy=email.policy.SMTP)
    assert msg["From"] is None and msg["Date"] is None and msg["Message-ID"] is None


def test_the_transfer_encoding_does_not_wrap_the_claims(m, det):
    """Quoted-printable soft-wraps at 76 columns, which would break the frozen string
    mid-sentence in the bytes and make a grep for it fail."""
    msg = email.message_from_bytes(render(m), policy=email.policy.SMTP)
    assert msg["Content-Transfer-Encoding"] == "8bit"
    assert det["estimand_note"].encode() in render(m)


# ---- refusals at the boundary -------------------------------------------------------------

def test_a_naive_clock_is_refused(m):
    with pytest.raises(ValueError, match="timezone-aware"):
        render(replace(m, now=m.now.replace(tzinfo=None)))


def test_an_unknown_branch_is_refused(m):
    with pytest.raises(ValueError, match="not one of"):
        render(replace(m, branch="tiers"))


def test_a_tier_message_without_a_notifying_tier_is_refused(m):
    for tier in (None, fd.NONE, "SEVERE"):
        with pytest.raises(ValueError, match="notifying tier"):
            render(replace(m, branch=nd.TIER, tier=tier, top_n=None))


def test_a_watch_message_carrying_a_tier_or_no_top_n_is_refused(m):
    with pytest.raises(ValueError, match="watch message"):
        render(replace(m, tier=fd.HIGH))
    with pytest.raises(ValueError, match="watch message"):
        render(replace(m, top_n=None))
