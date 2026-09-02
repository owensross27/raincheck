"""`make web`'s Range support (frontend2 02).

`python -m http.server` answers a Range request with 200 and the whole body. A PMTiles
archive is nothing but range requests, so the local preview would pull 52 MB per tile fetch
and never paint - which is the half of the 2026-08-17 basemap refusal ("needs a Range
server") that was still real after R2 answered the other half.

These run the REAL server on a real socket and speak to it with `urllib`, because the bug
this replaces lived in the HTTP layer and a unit test of `_span()` alone would have passed
against a handler that never sent a 206.
"""
import http.client
import io
import json
import threading
import urllib.error
import urllib.parse
import urllib.request

import pytest

from raincheck import webserve

BODY = bytes(range(256)) * 8          # 2,048 bytes, every byte value, position-identifiable


@pytest.fixture
def host(tmp_path):
    """The server, on an ephemeral port, serving one known file. Yields its base URL."""
    (tmp_path / "nyc.pmtiles").write_bytes(BODY)
    import socketserver
    from functools import partial

    handler = partial(webserve.RangeHandler, directory=str(tmp_path))
    webserve.RangeHandler.protocol_version = "HTTP/1.1"
    with socketserver.ThreadingTCPServer(("127.0.0.1", 0), handler) as httpd:
        httpd.daemon_threads = True
        t = threading.Thread(target=httpd.serve_forever, daemon=True)
        t.start()
        try:
            yield f"http://127.0.0.1:{httpd.server_address[1]}"
        finally:
            httpd.shutdown()


def get(url, rng=None):
    req = urllib.request.Request(url)
    if rng:
        req.add_header("Range", rng)
    with urllib.request.urlopen(req, timeout=10) as res:
        return res.status, dict(res.headers), res.read()


def test_a_single_range_comes_back_206_with_the_window_and_the_full_size(host):
    """THE test. 206, `Content-Range: bytes <a>-<b>/<total>`, a Content-Length that is the
    WINDOW and not the file, and the exact bytes asked for - a PMTiles client reads a
    directory entry by offset, so an off-by-one here is a corrupt tile and not a slow page.
    MUTATION KILLED: returning 200 (the stdlib behaviour this module exists to replace),
    sending the whole body under a 206, or an inclusive/exclusive slip at either end."""
    status, headers, body = get(f"{host}/nyc.pmtiles", "bytes=100-199")
    assert status == 206
    assert headers["Content-Range"] == f"bytes 100-199/{len(BODY)}"
    assert headers["Content-Length"] == "100"
    assert headers["Accept-Ranges"] == "bytes"
    assert body == BODY[100:200]


def test_an_open_ended_and_a_suffix_range_are_both_honoured(host):
    """`bytes=<a>-` (to EOF) and `bytes=-<n>` (the last n) are the two other forms a client
    actually sends; PMTiles opens with a fixed-offset header read and then asks for
    directory windows. MUTATION KILLED: treating a missing end as 0, or reading `bytes=-N`
    as "from 0 to N", which would silently serve the WRONG WINDOW rather than fail."""
    _, headers, body = get(f"{host}/nyc.pmtiles", "bytes=2000-")
    assert headers["Content-Range"] == f"bytes 2000-2047/{len(BODY)}"
    assert body == BODY[2000:]
    _, headers, body = get(f"{host}/nyc.pmtiles", "bytes=-16")
    assert headers["Content-Range"] == f"bytes 2032-2047/{len(BODY)}"
    assert body == BODY[-16:]


def test_no_range_header_is_the_ordinary_stdlib_200(host):
    """Everything else on this page is a plain GET, and none of it may change."""
    status, headers, body = get(f"{host}/nyc.pmtiles")
    assert status == 200 and body == BODY
    assert "Content-Range" not in headers


def test_a_range_this_server_declines_falls_back_to_the_whole_body(host):
    """# ponytail: single-range only. RFC 9110 lets a server ignore a Range it chooses not
    to honour, and 200-with-everything is the safe way to do that - a client gets correct
    bytes and merely pays for them. MUTATION KILLED: emitting a 206 for a multi-range
    request while sending ONE range's bytes, which is a silently truncated response.
    MUTATION SURVIVED, and it is equivalent rather than unpinned: deleting the explicit
    `"," in spec` guard leaves every multi-range form still refused, because the comma
    always lands inside the part `int()` parses. See the comment in webserve._span."""
    for bad in ("bytes=0-99,200-299", "items=0-99", "bytes=abc-def", "bytes=200-100"):
        status, headers, body = get(f"{host}/nyc.pmtiles", bad)
        assert status == 200, bad
        assert "Content-Range" not in headers, bad
        assert body == BODY, bad


def test_a_range_past_the_end_is_416_and_not_an_empty_200(host):
    """An unsatisfiable range must SAY so: a client that reads a zero-length 200 as a valid
    tile writes a corrupt cache entry. MUTATION KILLED: clamping the start into range (which
    serves the wrong bytes under a success code) or falling through to 200."""
    with pytest.raises(urllib.error.HTTPError) as exc:
        get(f"{host}/nyc.pmtiles", f"bytes={len(BODY)}-{len(BODY) + 10}")
    assert exc.value.code == 416
    assert exc.value.headers["Content-Range"] == f"bytes */{len(BODY)}"


def test_the_span_parser_is_inclusive_and_clamps_only_the_end():
    """The arithmetic on its own, since the cases that matter are boundaries. An end past
    EOF clamps (a client may ask for more than is there and RFC 9110 says serve what
    exists); a start past EOF does NOT clamp - it is the 416 above."""
    assert webserve._span("bytes=0-0", 2048) == (0, 0)
    assert webserve._span("bytes=0-", 2048) == (0, 2047)
    assert webserve._span("bytes=2040-99999", 2048) == (2040, 2047)
    assert webserve._span("bytes=-1", 2048) == (2047, 2047)
    assert webserve._span("bytes=-99999", 2048) == (0, 2047)
    # a start past EOF survives the parser and is refused by send_head as a 416
    assert webserve._span("bytes=5000-6000", 2048) == (5000, 2047)
    for bad in ("bytes=0-99,200-299", "items=0-99", "bytes=", "bytes=x-y", "bytes=9-1",
                "bytes=-0"):
        assert webserve._span(bad, 2048) is None, bad


# =========================================================================================
# POST /api/chat - the "Ask the map" chat proxy (chat-integration ticket). Same real-socket
# pattern as the Range tests above: the thing under test IS the HTTP layer (status codes,
# which headers reach DeepSeek, whether upstream is ever dialled), so a call straight into
# a handler method would miss exactly the bugs that matter - same reasoning as the module
# docstring gives for the Range tests.

CHAT_BODY = json.dumps({"model": "deepseek-chat",
                         "messages": [{"role": "user", "content": "hi"}],
                         "tools": [], "tool_choice": "auto"}).encode()


def post(url, body: bytes, headers=None):
    """Like `get` above, but over `http.client` rather than `urllib.request.urlopen` -
    several tests below monkeypatch THAT function to stand in for the server's own upstream
    call, and the test's own request to the local server must not be caught by its own mock.
    Reads the response body on a non-2xx instead of raising, since every test below is
    choosing between status codes, not treating one as the happy path."""
    parsed = urllib.parse.urlsplit(url)
    conn = http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=10)
    try:
        conn.request("POST", parsed.path or "/", body=body,
                      headers={"Content-Type": "application/json", **(headers or {})})
        res = conn.getresponse()
        return res.status, dict(res.getheaders()), res.read()
    finally:
        conn.close()


def chat_post(host, body=CHAT_BODY, headers=None):
    return post(f"{host}/api/chat", body, headers)


class FakeResponse:
    """A stand-in for what `urlopen` returns: a context manager with `.status`/`.read()`,
    the two members `_chat_bytes` touches."""
    def __init__(self, status: int, body: bytes):
        self.status = status
        self._body = body

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_the_server_binds_loopback_by_default():
    """/api/chat spends a real API key per request and the Origin check only binds
    browsers (curl sends no Origin) - so the default bind is 127.0.0.1, and putting the
    proxy on the LAN is an explicit `--bind 0.0.0.0`, never an accident of the old ""
    default."""
    import inspect

    assert inspect.signature(webserve.serve).parameters["bind"].default == "127.0.0.1"


def test_the_health_get_answers_locally_and_never_touches_the_network(host, monkeypatch, tmp_path):
    """GET /api/chat is the launcher's FREE probe: {"proxy": true, "key": bool}, answered
    by this server alone - upstream must never be dialled, or every page load with a
    configured key would cost a DeepSeek call. On the public static host this path is a
    plain 404, which is how chat.js tells preview from deployed and disables itself."""
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.setattr(webserve, "REPO", tmp_path)

    def boom(*a, **k):
        raise AssertionError("the health probe must never dial upstream")
    monkeypatch.setattr(urllib.request, "urlopen", boom)

    # http.client, the same way post() below dodges the urlopen mock: the test's own
    # request must not be caught by the guard aimed at the server's upstream call
    def health():
        parsed = urllib.parse.urlsplit(f"{host}/api/chat")
        conn = http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=10)
        try:
            conn.request("GET", "/api/chat")
            res = conn.getresponse()
            return res.status, json.loads(res.read())
        finally:
            conn.close()

    assert health() == (200, {"proxy": True, "key": False})
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
    assert health() == (200, {"proxy": True, "key": True})


def test_no_key_is_503_and_never_touches_the_network(host, monkeypatch, tmp_path):
    """No `DEEPSEEK_API_KEY` env var and no `.env` carrying it -> 503 {"error":"no_key"} -
    and upstream is never dialled AT ALL, which is the actual requirement (not just an
    accident of the 503): `urlopen` is replaced with something that fails the test if it is
    ever called, rather than a mock nobody inspects."""
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.setattr(webserve, "REPO", tmp_path)   # an empty dir: no .env to fall back to

    def boom(*a, **k):
        raise AssertionError("upstream must not be called with no key configured")
    monkeypatch.setattr(urllib.request, "urlopen", boom)

    status, _, body = chat_post(host)
    assert status == 503
    assert json.loads(body) == {"error": "no_key"}


def test_the_env_file_fallback_resolves_the_key_when_the_env_var_is_unset(host, monkeypatch, tmp_path):
    """The fallback the ticket asks for: with no process env var, the key still comes from
    `<repo>/.env`'s `KEY=value` lines. Proved by reaching the forwarded-request assertion
    below (a 200 carrying the file's key as the Bearer token) rather than falling to 503."""
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    (tmp_path / ".env").write_text("SOME_OTHER_KEY=x\nDEEPSEEK_API_KEY=fromfile123\n")
    monkeypatch.setattr(webserve, "REPO", tmp_path)

    captured = {}
    def fake_urlopen(req, timeout=None):
        captured["auth"] = req.get_header("Authorization")
        return FakeResponse(200, b'{"ok":true}')
    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    status, _, body = chat_post(host)
    assert status == 200
    assert body == b'{"ok":true}'
    assert captured["auth"] == "Bearer fromfile123"


def test_oversize_body_is_413_before_any_key_check(host, monkeypatch, tmp_path):
    """256 KB cap. No key is configured here on purpose: a 413 must come from the
    Content-Length check alone, before the key is even looked at - an oversized request must
    never double as a way to probe whether a key is configured."""
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.setattr(webserve, "REPO", tmp_path)

    big = b"x" * (webserve.MAX_CHAT_BODY + 1)
    status, _, body = chat_post(host, body=big)
    assert status == 413
    assert json.loads(body) == {"error": "too_large"}


def test_post_to_any_other_path_is_404(host):
    """Only /api/chat accepts POST; nothing else on this server does."""
    status, _, _ = post(f"{host}/api/other", b"{}")
    assert status == 404


def test_the_forwarded_request_carries_model_messages_and_the_bearer_key(host, monkeypatch):
    """The proxy's one job: relay the page's own {model, messages, tools, tool_choice} body
    to DeepSeek untouched, with the key attached server-side - never client-side, which is
    the entire reason this endpoint exists rather than a direct fetch from chat.js."""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "serverkey456")

    captured = {}
    def fake_urlopen(req, timeout=None):
        captured["url"] = req.full_url
        captured["auth"] = req.get_header("Authorization")
        captured["payload"] = json.loads(req.data)
        captured["timeout"] = timeout
        return FakeResponse(200, b'{"choices":[]}')
    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    status, _, body = chat_post(host)
    assert status == 200
    assert body == b'{"choices":[]}'          # the upstream JSON, returned VERBATIM
    assert captured["url"] == webserve.DEEPSEEK_URL
    assert captured["auth"] == "Bearer serverkey456"
    assert captured["timeout"] == 120
    assert captured["payload"]["model"] == "deepseek-chat"
    assert captured["payload"]["messages"] == [{"role": "user", "content": "hi"}]
    assert captured["payload"]["tool_choice"] == "auto"


def test_upstream_error_bodies_pass_through_verbatim(host, monkeypatch):
    """A bad key or a rate limit is DeepSeek's own error, and the UI shows DeepSeek's own
    message - so a 401 from upstream must come back as a 401 with the SAME body, not a
    generic 502 that throws the message away."""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "wrongkey")
    err_body = b'{"error":{"message":"Authentication Fails"}}'

    def fake_urlopen(req, timeout=None):
        raise urllib.error.HTTPError(req.full_url, 401, "Unauthorized", {}, io.BytesIO(err_body))
    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    status, _, body = chat_post(host)
    assert status == 401
    assert body == err_body


def test_cross_origin_post_is_refused_before_the_key_check(host, monkeypatch):
    """Strict same-origin: an `Origin` header naming a different host is refused outright.
    `urlopen` is a fail-the-test stand-in again, proving the refusal happens before upstream
    is ever considered."""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "shouldnotmatter")

    def boom(*a, **k):
        raise AssertionError("a cross-origin request must not reach upstream")
    monkeypatch.setattr(urllib.request, "urlopen", boom)

    status, _, body = chat_post(host, headers={"Origin": "http://evil.example:1234"})
    assert status == 403
    assert json.loads(body) == {"error": "cross_origin"}
