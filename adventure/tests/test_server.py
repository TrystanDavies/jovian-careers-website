"""The local web server: a quick round trip on a spare port."""

import json
import threading
import unittest
import urllib.error
import urllib.request

from advent.engine import Game
from advent.server import make_server


class ServerTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.httpd = make_server(Game(seed=1, peaceful=True), port=0)
        cls.base = "http://127.0.0.1:%d" % cls.httpd.server_address[1]
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def request(self, path, body=None, headers=None):
        data = json.dumps(body).encode() if body is not None else None
        hdrs = {"Content-Type": "application/json"} if body is not None else {}
        hdrs.update(headers or {})
        req = urllib.request.Request(self.base + path, data=data, headers=hdrs)
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                return resp.status, resp.read()
        except urllib.error.HTTPError as err:
            return err.code, err.read()

    def test_page_and_assets(self):
        for path in ("/", "/style.css", "/app.js", "/fonts/VT323-Regular.woff2"):
            status, body = self.request(path)
            self.assertEqual(status, 200, path)
            self.assertTrue(body)

    def test_state_and_command(self):
        status, body = self.request("/api/state")
        self.assertEqual(status, 200)
        state = json.loads(body)
        self.assertIn("End of Road", "\n".join(state["lines"]))
        self.assertIn("<svg", state["view"]["scene"])
        self.assertTrue(state["words"])
        status, body = self.request("/api/command", {"text": "east"})
        self.assertEqual(status, 200)
        data = json.loads(body)
        self.assertEqual(data["view"]["room"]["id"], "building")
        self.request("/api/command", {"text": "west"})

    def test_refuses_non_json_posts(self):
        req = urllib.request.Request(self.base + "/api/command", data=b"text=east",
                                     headers={"Content-Type": "application/x-www-form-urlencoded"})
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req, timeout=5)
        self.assertEqual(ctx.exception.code, 415)

    def test_refuses_foreign_host_and_escapes(self):
        self.assertEqual(self.request("/api/state", headers={"Host": "evil.example"})[0], 403)
        self.assertEqual(self.request("/../advent/engine.py")[0], 404)
        self.assertEqual(self.request("/%2e%2e/advent/engine.py")[0], 404)


if __name__ == "__main__":
    unittest.main()
