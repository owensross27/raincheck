"""`make web`: the stdlib static server, plus the ONE thing it lacks - `Range:`.

`python -m http.server` answers a Range request with 200 and the whole body. That was fine
while `web/` held nothing but JSON and a 950 KB MapLibre bundle, and the Makefile said so in
a comment. frontend2 02's basemap is a 52 MB PMTiles archive, which is nothing BUT range
requests: the client reads the header, then a directory, then a few KB of tiles. Without 206
the page would pull the whole archive per tile fetch and never paint - so the local preview,
not R2, is the half of ticket 14's "needs a Range server" refusal that was still real.

R2 serves ranges already (measured at frontend2 02 against the same Cloudflare architecture:
206 + `Content-Range` + `Accept-Ranges: bytes`). This module exists so the page can be proved
BEFORE it is published, on a laptop, with no bucket.

# ponytail: ONE range, and it is buffered rather than streamed. `bytes=<a>-<b>` /
# `bytes=<a>-` / `bytes=-<n>` are honoured; a multi-range header falls back to 200 and the
# whole body, which is what RFC 9110 permits a server to do with a Range it declines. The
# ceiling: a range is read into memory before it is written, so a client asking for the
# whole 52 MB file in one range buffers 52 MB. PMTiles asks in KB and this is a preview
# server on a laptop. If either stops being true, stream the window instead.
"""
import http.server
import io
import json
import os
import socketserver
import sys
import urllib.error
import urllib.parse
import urllib.request
from functools import partial

from raincheck.paths import REPO

# "Ask the map" chat proxy (chat-integration ticket). The browser cannot hold the
# DeepSeek key - anything shipped to the page is public - so this ONE endpoint holds it
# server-side and forwards the page's own {model, messages, tools, tool_choice} body
# verbatim. Everything else about the request (system prompt, the tool loop, replay) is
# chat.js's problem; this is purely "hide the key and relay the bytes".
DEEPSEEK_URL = "https://api.deepseek.com/chat/completions"
MAX_CHAT_BODY = 256 * 1024   # 256 KB; a runaway tool-result loop should 413, not hang


def _deepseek_key() -> str | None:
    """`DEEPSEEK_API_KEY`, or the same name parsed out of the repo `.env` (KEY=value
    lines, `make web`'s own dev convenience - nothing here writes or rotates it)."""
    key = os.environ.get("DEEPSEEK_API_KEY")
    if key:
        return key
    try:
        for line in (REPO / ".env").read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            if k.strip() == "DEEPSEEK_API_KEY":
                return v.strip() or None
    except OSError:
        pass
    return None


class RangeHandler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        # the chat launcher's FREE health probe: "is a proxy here at all, and does it hold
        # a key" - answered locally, never forwarded, so a page load costs no upstream
        # call. The public static host has no handler at this path (a plain 404), which is
        # exactly how chat.js tells "local preview" from "deployed page" and disables its
        # launcher instead of letting the first question die on a mystery error.
        if self.path == "/api/chat":
            return self._chat_json(200, {"proxy": True, "key": _deepseek_key() is not None})
        return super().do_GET()

    def do_POST(self):
        # every early return below fires BEFORE the body is read off the socket - and this
        # handler is served over HTTP/1.1 keep-alive (RangeHandler.protocol_version), so an
        # unread body left sitting in the stream is not discarded, it is the START OF THE
        # NEXT REQUEST on the same connection. Measured while writing the tests: a 403
        # response followed by the client's next request came back "400 Bad request
        # version", because the previous POST's body bytes were still queued and got parsed
        # as a request line. `close_connection = True` on every early exit forces the socket
        # closed instead, which is the only cheap way to discard a body of unknown or
        # over-cap length without adding a second content-length-aware read path.
        if self.path != "/api/chat":
            self.close_connection = True
            self.send_error(404)
            return
        # strict same-origin: a POST with a JSON content-type is cross-origin-blocked by
        # the browser's own preflight already, but a non-preflighted client (curl, a
        # second local process) is not - this is the second, independent gate on the one
        # endpoint that can spend the user's API key.
        origin = self.headers.get("Origin")
        if origin and urllib.parse.urlsplit(origin).netloc != self.headers.get("Host", ""):
            self.close_connection = True
            self._chat_json(403, {"error": "cross_origin"})
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = MAX_CHAT_BODY + 1   # an unparsable Content-Length is refused, not guessed
        if length > MAX_CHAT_BODY:
            self.close_connection = True
            self._chat_json(413, {"error": "too_large"})
            return
        body = self.rfile.read(length)
        key = _deepseek_key()
        if not key:
            self._chat_json(503, {"error": "no_key"})
            return
        req = urllib.request.Request(DEEPSEEK_URL, data=body, method="POST",
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"})
        try:
            with urllib.request.urlopen(req, timeout=120) as res:
                self._chat_bytes(res.status, res.read())
        except urllib.error.HTTPError as e:
            # DeepSeek's own 4xx/5xx body (a bad key, a rate limit) - pass it through
            # verbatim so the page can show DeepSeek's own error message.
            self._chat_bytes(e.code, e.read())
        except (urllib.error.URLError, TimeoutError, OSError):
            self._chat_json(502, {"error": "upstream_unreachable"})

    def _chat_json(self, status: int, obj: dict) -> None:
        self._chat_bytes(status, json.dumps(obj).encode())

    def _chat_bytes(self, status: int, body: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_head(self):
        rng = self.headers.get("Range")
        path = self.translate_path(self.path)
        if not rng or os.path.isdir(path):
            return super().send_head()
        try:
            with open(path, "rb") as f:
                size = os.fstat(f.fileno()).st_size
                span = _span(rng, size)
                if span is None:          # a Range we decline -> the whole body, 200
                    return super().send_head()
                start, end = span
                if start >= size:
                    self.send_response(416)
                    self.send_header("Content-Range", f"bytes */{size}")
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return None
                f.seek(start)
                window = f.read(end - start + 1)
        except OSError:
            return super().send_head()

        self.send_response(206)
        self.send_header("Content-type", self.guess_type(path))
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.send_header("Content-Length", str(len(window)))
        self.send_header("Last-Modified", self.date_time_string(os.stat(path).st_mtime))
        self.end_headers()
        return io.BytesIO(window)


def _span(header: str, size: int) -> tuple[int, int] | None:
    """`Range:` -> an inclusive (start, end), or None for anything not honoured here."""
    unit, _, spec = header.partition("=")
    # MEASURED-EQUIVALENT MUTANT, recorded so the next session does not rediscover it and
    # either delete it blindly or file it as a hole: removing `or "," in spec` changes NO
    # behaviour, because in `a-b,c-d` the first `-` always leaves the comma inside the part
    # `int()` parses, so every multi-range form already returns None (proved on seven forms
    # at frontend2 02). It stays because that rejection is an ACCIDENT of the parse and this
    # one is the intent - a later edit that made the numeric parse more permissive would
    # otherwise start honouring half of a multi-range request silently.
    if unit.strip().lower() != "bytes" or "," in spec:
        return None
    first, sep, last = spec.strip().partition("-")
    if not sep:
        return None
    try:
        if not first:                                   # bytes=-N: the last N bytes
            n = int(last)
            return (max(0, size - n), size - 1) if n > 0 else None
        start = int(first)
        end = int(last) if last else size - 1
    except ValueError:
        return None
    return (start, min(end, size - 1)) if start <= end else None


def serve(port: int = 8000, directory: str = ".", bind: str = "127.0.0.1") -> None:
    """Blocking, until Ctrl-C. HTTP/1.1 so Content-Length is honoured per response and the
    client may keep the connection - a PMTiles read is many small requests in a row."""
    handler = partial(RangeHandler, directory=directory)
    RangeHandler.protocol_version = "HTTP/1.1"
    socketserver.ThreadingTCPServer.allow_reuse_address = True
    with socketserver.ThreadingTCPServer((bind, port), handler) as httpd:
        print(f"serving {directory} on http://localhost:{port}/ (Range: supported)",
              flush=True)
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("")


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    directory = "."
    if "--directory" in argv:
        i = argv.index("--directory")
        directory = argv[i + 1]
        del argv[i:i + 2]
    # LOOPBACK BY DEFAULT since /api/chat exists: the proxy spends a real API key per
    # request, the Origin check only binds browsers (curl sends no Origin), and the old
    # "" bind put both on every interface - the whole LAN could spend the key. A phone
    # preview on the local network is an explicit choice now: --bind 0.0.0.0.
    bind = "127.0.0.1"
    if "--bind" in argv:
        i = argv.index("--bind")
        bind = argv[i + 1]
        del argv[i:i + 2]
    serve(int(argv[0]) if argv else 8000, directory, bind)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
