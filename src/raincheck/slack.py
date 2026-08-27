"""Slack transport: one function, `post(text)`, to the ops channel.

This is the OPS side-channel Ross chartered 2026-08-27 (#raincheck-notifs) - a place for
pipeline pulses and by-hand announcements. It is NOT the notify arming step: nothing in
`notify_dryrun`/`notify_decide` imports this module, and the subscriber mail path stays
the by-hand HITL the rehearsal documents. Wiring a caller to this module is a separate,
explicit decision each time.

Token: `SLACK_BOT_TOKEN` from the environment (`.env` via the Makefile, the same home as
every other credential here - never a file in the repo). The bot must be invited to the
channel (`/invite @<bot>` once, in Slack).

stdlib urllib on `chat.postMessage`; Slack answers HTTP 200 with `{"ok": false}` on every
application error, so the body's `ok` is the verdict, never the status code.
"""
import json
import os
import sys
import urllib.request

API = "https://slack.com/api/chat.postMessage"
CHANNEL = "#raincheck-notifs"


def request(text: str, channel: str = CHANNEL, token: str | None = None) -> urllib.request.Request:
    """The prepared HTTP request, separate from sending so a test never needs a socket."""
    token = token or os.environ.get("SLACK_BOT_TOKEN", "")
    if not token:
        raise RuntimeError("SLACK_BOT_TOKEN is not set - add it to .env")
    return urllib.request.Request(
        API,
        data=json.dumps({"channel": channel, "text": text}).encode(),
        headers={"Authorization": f"Bearer {token}",
                 "Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )


def post(text: str, channel: str = CHANNEL, token: str | None = None) -> dict:
    """Send one message; return Slack's parsed reply. Raises on `ok: false` - a transport
    that swallows its own failure is worse than none."""
    with urllib.request.urlopen(request(text, channel, token), timeout=10) as resp:
        reply = json.loads(resp.read())
    if not reply.get("ok"):
        raise RuntimeError(f"slack refused: {reply.get('error', 'unknown')} "
                           f"(channel {channel!r} - is the bot invited?)")
    return reply


def main(argv: list[str]) -> int:
    if not argv or argv[0] in ("-h", "--help"):
        print("usage: python -m raincheck.slack <text> [--channel '#name']", file=sys.stderr)
        return 2
    channel = CHANNEL
    if "--channel" in argv:
        i = argv.index("--channel")
        channel = argv[i + 1]
        argv = argv[:i] + argv[i + 2:]
    reply = post(" ".join(argv), channel)
    print(f"sent to {channel} ts={reply.get('ts')}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
