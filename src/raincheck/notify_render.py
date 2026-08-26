"""Notify ticket 09 (spec section 7; SEAM N): a decided Message becomes bytes a person
reads. ONE pure function, `render(Message) -> bytes`, and nothing else.

WHAT THIS IS ALLOWED TO SAY. Nothing of its own. Ticket 08's `Message` is frozen and
carries no prose at all, so every CLAIM in the rendered text is read from the two
committed artifacts through `flood_panel.strings(det, art)` - the same call the panel
renders from, which is what makes "a message and the panel cannot contradict each other"
structural rather than a promise. The connective words (the labels, the Window block, the
unsubscribe instruction) are this module's; the claims are flood 10's, flood 11's and
notify 01's.

WHICH BRANCH IS RENDERED IS THE MESSAGE'S, NOT A CHOICE MADE HERE. `nd.branch(det)` reads
`cutpoints.provisional`, still `true`, so WATCH is the branch v1 ships and `m.tier` is
`None` on every real message today. A headline that read `m.tier` would print `None` to
every subscriber. On watch the claim is worded from `m.top_n` and `m.rank` as a WATCH -
among the N most exposed right now - never as a tier and never as a depth. Where `m.tier`
IS set it is an `fd.TIERS` member and its label is read from `display.tier_labels`.

TWO DEPLOYMENT FACTS THIS REPO DOES NOT HOLD, so they are named constants and this
function REFUSES rather than inventing them: the panel's public URL (the public bucket
and its custom domain are still a [YOU] item, so no URL exists anywhere in the tree) and
the mailbox an unsubscribe request reaches (v1 has NO HTTP endpoint by spec section 9, so
`List-Unsubscribe` is a mailto and nothing here records an address). A fabricated link
404s and a fabricated mailto bounces; refusing is the same shape as `nd.policy()` refusing
a Policy that did not come from the artifact.

Wiring this into the 30 s loop is ticket 10's and replaying it is ticket 11's. This module
opens no socket, no database and no data root - only the two artifacts committed to the
repo, which is the same input `make release-check` runs on.
"""
from email.message import EmailMessage
from email.policy import SMTP
from urllib.parse import quote

from raincheck import flood_detect as fd
from raincheck import flood_exposure as fe
from raincheck import flood_panel as fp
from raincheck import notify_decide as nd

# [YOU] - the panel's public URL. The public bucket, its custom domain and its CORS rule
# are all still open, so there is no address to write here yet; `publish.PUBLIC_BUCKET`
# names the bucket and not a host. Set it beside the host, or pass `panel_url=`.
PANEL_URL: str | None = None

# [YOU] - the mailbox an unsubscribe reaches. v1 has no ingress and no endpoint (spec
# section 9); the operator runs `notify_store.unsubscribe(con, token)` by hand, so this is
# where a subscriber sends the token. Set it beside the sender's identity (ticket 10), or
# pass `unsubscribe_to=`.
UNSUBSCRIBE_TO: str | None = None

# The handler a subscriber's token actually reaches, named in the message so the
# processing expectation is honest rather than implied. It is a python function and not a
# URL because v1 has no endpoint; ticket 07 built it as the same function an endpoint
# would call if one is ever added.
HANDLER = "notify_store.unsubscribe(con, token)"

# Everything below is a LABEL, never a claim. A claim is read from `fp.strings(det, art)`.
SUBJECT = "raincheck {branch}: {asset_id}"


def strings() -> dict:
    """THE claim vocabulary, read from the two committed artifacts through the panel's own
    selector. Read at render time, so recording flood 12's verdict or re-wording a label
    reaches a message with no redeploy - `display.*` is deliberately outside
    `detector_version` and the panel already reads it this way [F15]."""
    return fp.strings(fd.constants(), fe.coefficients())


def _claim(m: nd.Message, s: dict) -> tuple[str, str]:
    """(subject branch word, the sentence that says what happened). The watch branch is
    worded from `top_n` and `rank`; the tier branch from the artifact's own label."""
    if m.branch == nd.WATCH:
        return "watch", (
            f"{m.asset_id} ({m.asset_kind}) is among the {m.top_n} {m.asset_kind} units "
            f"ranked most exposed right now. This is a WATCH: it is not a tier, it is not "
            f"a depth, and no water has been observed.")
    label = s["tier_labels"][m.tier]
    return label, (
        f"{m.asset_id} ({m.asset_kind}) entered the {label} tier for this Window. "
        f"A tier is a rank cut, not a depth, and no water has been observed.")


def _body(m: nd.Message, s: dict, panel_url: str, unsubscribe_to: str) -> str:
    _, claim = _claim(m, s)
    lines = [claim, "",
             f"Rank {m.rank:.4f} - {s['cutpoint_basis']}.", ""]
    lines += [f"Window {s['window_interval']}",
              f"  anchor  {m.anchor}",
              f"  now     {m.now.isoformat()}",
              "The evidence is hour-grain rainfall totals over that Window and it trails "
              "the storm.",
              f"Nothing in this message was measured at {m.asset_id}.", ""]
    lines += [f"What is ranked: {s['estimand']} - {s['estimand_note']}", "",
              s["within_cell"]]
    if m.no_skill_claim:
        lines.append(m.no_skill_claim)
    if m.tier is not None:
        lines.append(f"Cutpoints: {s['tiers_provisional']}")
    lines += ["", f"Model: {s['panel']['headline']} - {s['panel']['release']}; "
                  f"{s['panel']['caveat']}.",
              f"Stamps: score {m.score_version} - detector {m.detector_version}",
              f"Window id: {m.window_id}", ""]
    lines += [s["operating_truth"], "",
              f"The panel: {panel_url}", "",
              f"To stop these, send this token to {unsubscribe_to}:",
              f"  {m.unsubscribe_token}",
              f"An operator runs `{HANDLER}` by hand - v1 has no unsubscribe endpoint, so "
              "removal is not instant and this is not one-click.",
              "One token covers every subscription this address owns, it removes all of "
              "them at once, and it stays valid if more are added later."]
    return "\n".join(lines) + "\n"


def render(m: nd.Message, *, panel_url: str | None = None,
           unsubscribe_to: str | None = None) -> bytes:
    """A decided Message as the bytes of one plain-text email. Pure: the same Message and
    the same two artifacts render the same bytes, every time.

    No `From`, no `Date` and no `Message-ID` - those are the sender's (ticket 10), which
    is also what keeps this deterministic.
    """
    if m.now.tzinfo is None:
        raise ValueError("Message.now must be timezone-aware: a naive clock in a message "
                         "is an ambiguous time in somebody's inbox")
    if m.branch not in nd.BRANCHES:
        raise ValueError(f"{m.branch} is not one of {nd.BRANCHES}")
    if m.branch == nd.TIER and m.tier not in fd.TIERS[1:]:
        raise ValueError(f"a tier message must carry a notifying tier, not {m.tier!r}")
    if m.branch == nd.WATCH and (m.tier is not None or not m.top_n):
        raise ValueError("a watch message carries top_n and no tier: "
                         f"tier={m.tier!r} top_n={m.top_n!r}")
    if not m.unsubscribe_token:
        raise ValueError("every message carries the handle's unsubscribe token")
    panel_url = panel_url or PANEL_URL
    unsubscribe_to = unsubscribe_to or UNSUBSCRIBE_TO
    if not panel_url or not unsubscribe_to:
        raise ValueError(
            "set notify_render.PANEL_URL and notify_render.UNSUBSCRIBE_TO (or pass them): "
            "the public host and the unsubscribe mailbox are deployment facts this repo "
            "does not hold, and a message with a dead link or a bouncing unsubscribe is "
            "worse than one that was never rendered")

    s = strings()
    branch_word, _ = _claim(m, s)
    msg = EmailMessage(policy=SMTP)
    msg["To"] = m.handle
    msg["Subject"] = SUBJECT.format(branch=branch_word, asset_id=m.asset_id)
    # RFC 2369 only. `List-Unsubscribe-Post` (RFC 8058) is deliberately NOT set: it
    # promises one-click removal, and v1's removal is an operator running a function.
    msg["List-Unsubscribe"] = (
        f"<mailto:{unsubscribe_to}?subject=unsubscribe%20{quote(m.unsubscribe_token, safe='')}>")
    # 8bit, not quoted-printable: QP soft-wraps at 76 columns, which would break the
    # frozen operating-truth string mid-sentence in the bytes. The rendered text has to
    # survive a grep, so the transfer encoding may not fold it.
    msg.set_content(_body(m, s, panel_url, unsubscribe_to), charset="utf-8", cte="8bit")
    return msg.as_bytes()
