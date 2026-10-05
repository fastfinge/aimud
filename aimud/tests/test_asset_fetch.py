"""
Fetching a file somebody named: every refusal, planted. docs/archived/assets.md 6, 14.

A real HTTP server on the loopback address stands in for the internet. The
loopback address is exactly what `assets.fetch` must refuse, so the tests that
want a download to work trust it explicitly (`trusting`), and every test
that wants a refusal leaves it untrusted, or points somewhere private. No test
touches the real network: every private address is refused before anything
is sent, and every name is resolved by a patched lookup.
"""

import http.server
import os
import socket
import threading
import time
from unittest import mock

from django.test import SimpleTestCase, tag

from world import assets

WORLD = b'{"aimud": 1, "kind": "world"}'


class _Handler(http.server.BaseHTTPRequestHandler):
    """Answers by path: /world, /missing, /redirect?to=..., /big, /liar, /slow."""

    def log_message(self, *args):
        pass

    def do_GET(self):
        path, _, query = self.path.partition("?")
        if path == "/world":
            return self._send(200, WORLD)
        if path == "/redirect":
            self.send_response(302)
            self.send_header("Location", query.removeprefix("to="))
            self.end_headers()
            return None
        if path == "/big":
            return self._send(200, b"{" + b" " * 5000 + b"}")
        if path == "/liar":
            # Says it is small and is not: the cap has to count what arrives.
            self.send_response(200)
            self.send_header("Content-Length", "10")
            self.end_headers()
            try:
                self.wfile.write(b"{" + b" " * 5000)
            except OSError:
                pass
            return None
        if path == "/endless":
            # No length at all, and more than any cap.
            self.send_response(200)
            self.end_headers()
            try:
                for _ in range(200):
                    self.wfile.write(b" " * 1024)
            except OSError:
                pass
            return None
        if path == "/slow":
            time.sleep(2)
            return self._send(200, WORLD)
        return self._send(404, b"no")

    def _send(self, status, body):
        self.send_response(status)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
        return None


class _Served(SimpleTestCase):
    """A local server for the length of each test class."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever,
                                      daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        super().tearDownClass()

    def url(self, path):
        return f"http://127.0.0.1:{self.port}{path}"

    def trusting(self):
        """Treat the loopback server as public, for one test."""
        for patcher in (mock.patch.object(assets, "TRUSTED_NETWORKS",
                                          ("127.0.0.1/32",)),
                        mock.patch.object(assets, "TRUSTED_PORTS",
                                          (self.port,))):
            patcher.start()
            self.addCleanup(patcher.stop)

    def refused(self, url, most=1024):
        with self.assertRaises(assets.Refused) as caught:
            path = assets.fetch(url, most)
            os.remove(path)
        return str(caught.exception)


@tag("unit")
class AFileThatCanBeFetched(_Served):

    def test_arrives_whole_in_a_file(self):
        self.trusting()
        path = assets.fetch(self.url("/world"), 1024)
        try:
            with open(path, "rb") as handle:
                self.assertEqual(handle.read(), WORLD)
        finally:
            os.remove(path)

    def test_a_server_that_says_no(self):
        self.trusting()
        self.assertIn("answered 404", self.refused(self.url("/nothing")))


@tag("unit")
class NothingPrivate(_Served):
    """Refused before anything is sent. docs/archived/assets.md 6."""

    def test_the_loopback_address(self):
        # Port 80, so it is the address and not the port that is refused.
        self.assertIn("private network",
                      self.refused("http://127.0.0.1/world"))

    def test_a_private_network(self):
        self.assertIn("private network",
                      self.refused("http://10.0.0.1/world"))

    def test_link_local(self):
        self.assertIn("private network",
                      self.refused("http://169.254.10.10/world"))

    def test_cloud_metadata(self):
        self.assertIn("private network",
                      self.refused("http://169.254.169.254/latest/meta-data/"))

    def test_ipv6_loopback(self):
        self.assertIn("private network", self.refused("http://[::1]/world"))

    def test_a_private_address_dressed_as_ipv6(self):
        self.assertIn("private network",
                      self.refused("http://[::ffff:127.0.0.1]/world"))

    def test_a_name_that_answers_with_a_private_address(self):
        def private(host, port, *args, **kwargs):
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "",
                     ("10.1.2.3", port))]

        with mock.patch("socket.getaddrinfo", private):
            self.assertIn("private network",
                          self.refused("http://innocent.example/world"))

    def test_a_redirect_into_a_private_network(self):
        """The first hop is trusted; the second goes somewhere it must not."""
        self.trusting()
        self.assertIn("private network", self.refused(
            self.url("/redirect?to=http://10.0.0.1/world")))

    def test_a_redirect_to_cloud_metadata(self):
        self.trusting()
        self.assertIn("private network", self.refused(
            self.url("/redirect?to=http://169.254.169.254/latest/")))


@tag("unit")
class OnlyTheWeb(_Served):

    def test_not_a_file_on_this_machine(self):
        self.assertIn("only http and https",
                      self.refused("file:///etc/passwd"))

    def test_not_ftp(self):
        self.assertIn("only http and https",
                      self.refused("ftp://example.com/world.json"))

    def test_not_an_odd_port(self):
        self.assertIn("ports", self.refused("http://93.184.216.34:6667/x"))

    def test_nothing_at_all(self):
        self.assertIn("no address", self.refused("   "))


@tag("unit")
class NothingTooBig(_Served):
    """The cap is counted on what arrives, not on what a server claims."""

    def setUp(self):
        super().setUp()
        self.trusting()

    def test_a_file_that_says_it_is_too_big(self):
        self.assertIn("bigger than", self.refused(self.url("/big"), most=100))

    def test_a_server_that_sends_more_than_it_said_is_cut_at_what_it_said(self):
        """
        HTTP framing ends the body at the length given, so the extra never
        arrives. The lie that matters -- no length, and no end -- is below.
        """
        path = assets.fetch(self.url("/liar"), 100)
        try:
            self.assertEqual(os.path.getsize(path), 10)
        finally:
            os.remove(path)

    def test_a_file_with_no_length_that_never_stops(self):
        self.assertIn("bigger than",
                      self.refused(self.url("/endless"), most=10 * 1024))

    def test_nothing_is_left_behind(self):
        import tempfile

        before = set(os.listdir(tempfile.gettempdir()))
        self.refused(self.url("/big"), most=100)
        left = {name for name in set(os.listdir(tempfile.gettempdir())) - before
                if name.endswith(".fetch")}
        self.assertEqual(left, set())


@tag("unit")
class NothingForever(_Served):

    def test_a_server_that_takes_too_long(self):
        self.trusting()
        with mock.patch.object(assets, "FETCH_TIMEOUT", 0.5):
            self.assertIn("took longer", self.refused(self.url("/slow")))
