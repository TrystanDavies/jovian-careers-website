"""A small local web server: the windows in your browser, the game in Python.

Standard library only. It binds to 127.0.0.1 by default and serves one game
per process. The browser talks to it with two JSON calls:

    GET  /api/state            -> {lines, view, words}
    POST /api/command {text}   -> {lines, view}
"""

import json
import os
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

from .view import build_view
from .vocab import completion_words

WEB_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web")

CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".woff2": "font/woff2",
    ".txt": "text/plain; charset=utf-8",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
}

MAX_BODY = 8192


class GameHost(object):
    def __init__(self, game):
        self.game = game
        self.lock = threading.Lock()


def make_handler(host, web_dir=WEB_DIR):
    root = os.path.realpath(web_dir)

    class Handler(BaseHTTPRequestHandler):
        server_version = "ColossalCave/1.0"

        def log_message(self, fmt, *args):     # keep the console quiet
            pass

        def _send(self, code, body, ctype):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, obj, code=200):
            self._send(code, json.dumps(obj).encode("utf-8"), "application/json")

        def _host_ok(self):
            # Refuse requests addressed to some other name (DNS rebinding).
            name = (self.headers.get("Host") or "").rsplit(":", 1)[0].strip("[]")
            return name in ("127.0.0.1", "localhost", "::1", self.server.server_address[0])

        def do_GET(self):
            if not self._host_ok():
                return self._send(403, b"Forbidden", "text/plain")
            path = urlparse(self.path).path
            if path == "/api/state":
                with host.lock:
                    g = host.game
                    data = {"lines": g.state.get("last_output", []), "view": build_view(g),
                            "words": completion_words()}
                return self._json(data)
            if path == "/":
                path = "/index.html"
            full = os.path.realpath(os.path.join(root, path.lstrip("/")))
            if not full.startswith(root + os.sep) or not os.path.isfile(full):
                return self._send(404, b"Not found", "text/plain")
            ext = os.path.splitext(full)[1].lower()
            with open(full, "rb") as fh:
                body = fh.read()
            self._send(200, body, CONTENT_TYPES.get(ext, "application/octet-stream"))

        def do_POST(self):
            if not self._host_ok():
                return self._send(403, b"Forbidden", "text/plain")
            # Only same-origin JSON: a JSON content type forces a CORS
            # preflight from any other site, which we never answer.
            if not (self.headers.get("Content-Type") or "").startswith("application/json"):
                return self._json({"error": "JSON only"}, 415)
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                length = 0
            if length > MAX_BODY:
                return self._json({"error": "too large"}, 413)
            try:
                body = json.loads(self.rfile.read(length) or b"{}")
            except ValueError:
                return self._json({"error": "bad JSON"}, 400)
            path = urlparse(self.path).path
            if path == "/api/command":
                text = str(body.get("text", ""))[:500]
                with host.lock:
                    result = host.game.do(text)
                return self._json(result.to_dict())
            return self._json({"error": "not found"}, 404)

    return Handler


def make_server(game, host="127.0.0.1", port=8765, tries=20):
    handler = make_handler(GameHost(game))
    last = None
    for p in range(port, port + tries) if port else [0]:
        try:
            return ThreadingHTTPServer((host, p), handler)
        except OSError as exc:
            last = exc
    raise last


def serve(game, host="127.0.0.1", port=8765, open_browser=True):
    httpd = make_server(game, host, port)
    url = "http://%s:%d/" % (host if host != "0.0.0.0" else "127.0.0.1", httpd.server_address[1])
    print("Colossal Cave is running at %s" % url)
    print("Press Ctrl+C here to stop.")
    if open_browser:
        threading.Timer(0.6, webbrowser.open, args=(url,)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nThe cave closes. Goodbye!")
    finally:
        httpd.server_close()
