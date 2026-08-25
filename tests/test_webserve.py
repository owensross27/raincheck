"""`make web`'s Range support (frontend2 02).

`python -m http.server` answers a Range request with 200 and the whole body. A PMTiles
archive is nothing but range requests, so the local preview would pull 52 MB per tile fetch
and never paint - which is the half of the 2026-08-17 basemap refusal ("needs a Range
server") that was still real after R2 answered the other half.

These run the REAL server on a real socket and speak to it with `urllib`, because the bug
this replaces lived in the HTTP layer and a unit test of `_span()` alone would have passed
against a handler that never sent a 206.
"""
import threading
import urllib.error
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
