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
import os
import socketserver
import sys
from functools import partial


class RangeHandler(http.server.SimpleHTTPRequestHandler):
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


def serve(port: int = 8000, directory: str = ".", bind: str = "") -> None:
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
    serve(int(argv[0]) if argv else 8000, directory)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
