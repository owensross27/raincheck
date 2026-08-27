"""slack.post is transport only: right payload out, `ok` verdict honoured, no socket in
any test (request/post are split exactly so this file never needs one)."""
import io
import json
import urllib.request

import pytest

from raincheck import slack


def test_request_carries_channel_text_and_bearer_token(monkeypatch):
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test")
    req = slack.request("cluster is up")
    assert req.full_url == slack.API
    assert req.get_header("Authorization") == "Bearer xoxb-test"
    assert json.loads(req.data) == {"channel": "#raincheck-notifs", "text": "cluster is up"}


def test_missing_token_refuses_before_any_network(monkeypatch):
    monkeypatch.delenv("SLACK_BOT_TOKEN", raising=False)
    with pytest.raises(RuntimeError, match="SLACK_BOT_TOKEN"):
        slack.request("anything")


def _fake_urlopen(body: dict):
    # io.BytesIO is already a context manager, exactly like the real response object
    return lambda req, timeout: io.BytesIO(json.dumps(body).encode())


def test_post_returns_slack_reply_on_ok(monkeypatch):
    monkeypatch.setattr(urllib.request, "urlopen", _fake_urlopen({"ok": True, "ts": "1.2"}))
    assert slack.post("hi", token="xoxb-test")["ts"] == "1.2"


def test_post_raises_on_ok_false_with_slacks_reason(monkeypatch):
    """Slack sends HTTP 200 for `channel_not_found`; the body's ok field is the verdict."""
    monkeypatch.setattr(urllib.request, "urlopen",
                        _fake_urlopen({"ok": False, "error": "channel_not_found"}))
    with pytest.raises(RuntimeError, match="channel_not_found"):
        slack.post("hi", token="xoxb-test")
