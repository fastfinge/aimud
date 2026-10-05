"""
OAuth for a service: authorised once, by an admin, as the server.

docs/mcp-client.md §11. The SDK runs the flow; these hold the game's half of
it at each seam: the token store that is the server's and nobody else's, the
redirect that tells the admin where to go, the browser coming back to a view
that hands the code to whatever was waiting, and refusing to start what
cannot work.
"""

import asyncio
import threading
from unittest import mock

from django.test import RequestFactory, override_settings, tag

from tests.base import GameTest
from tests.support import immediately
from world import service_auth, services


def _record(**extra):
    record = services.blank("calendar", services.URL)
    record.update(url="https://calendar.example/mcp", auth=services.OAUTH)
    record.update(extra)
    return record


class _Loop:
    """An asyncio loop on its own thread, as the connection manager runs one."""

    def __enter__(self):
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self.loop.run_forever, daemon=True)
        self.thread.start()
        return self

    def run(self, coroutine, timeout=5):
        return asyncio.run_coroutine_threadsafe(coroutine, self.loop).result(timeout)

    def __exit__(self, *exc):
        self.loop.call_soon_threadsafe(self.loop.stop)


@tag("world")
class TheTokensAreTheServers(GameTest):
    """
    The store writes on the reactor. There is no reactor running in a test, so
    what it hands the reactor is collected and run here, on the test's thread,
    which is where the reactor would run it.
    """

    def setUp(self):
        super().setUp()
        self.queued = []
        patcher = mock.patch.object(service_auth, "_on_reactor",
                                    lambda work, *args: self.queued.append((work, args)))
        patcher.start()
        self.addCleanup(patcher.stop)

    def settle(self):
        while self.queued:
            work, args = self.queued.pop(0)
            work(*args)

    def test_a_token_is_kept_on_the_service_and_read_back(self):
        from mcp.shared.auth import OAuthToken

        services.put(_record())
        store = service_auth.Store(services.get("calendar"))
        with _Loop() as loop:
            loop.run(store.set_tokens(OAuthToken(access_token="at-1",
                                                 refresh_token="rt-1")))
            self.settle()
            again = service_auth.Store(services.get("calendar"))
            got = loop.run(again.get_tokens())
        self.assertEqual(got.access_token, "at-1")
        self.assertEqual(services.get("calendar")["oauth"]["tokens"]["refresh_token"],
                         "rt-1")

    def test_nothing_is_kept_on_an_account(self):
        from mcp.shared.auth import OAuthToken

        services.put(_record())
        store = service_auth.Store(services.get("calendar"))
        with _Loop() as loop:
            loop.run(store.set_tokens(OAuthToken(access_token="at-2")))
        self.settle()
        self.assertEqual(services.get("calendar")["oauth"]["tokens"]["access_token"],
                         "at-2")
        for attribute in self.char1.attributes.all():
            self.assertNotIn("at-2", str(attribute.value))

    def test_it_is_said_to_be_authorised_without_saying_the_token(self):
        from commands import services_subject

        services.put(_record(oauth={"tokens": {"access_token": "at-secret"}}))
        said = services_subject.auth_line(services.get("calendar"))
        self.assertIn("authorised", said)
        self.assertNotIn("at-secret", said)


@tag("world")
class SendingTheAdminToAgree(GameTest):

    @override_settings(SERVICES_PUBLIC_URL="https://mud.example")
    def test_the_redirect_comes_back_to_the_callback(self):
        provider = service_auth.provider(_record())
        uris = [str(uri) for uri in provider.context.client_metadata.redirect_uris]
        self.assertEqual(uris, ["https://mud.example/services/oauth/callback"])

    def test_whoever_asked_is_told_the_address(self):
        told = []
        caller = mock.Mock(msg=told.append)
        service_auth._WAITING["calendar"] = caller
        provider = service_auth.provider(_record())
        try:
            with _Loop() as loop:
                loop.run(provider.context.redirect_handler(
                    "https://auth.example/authorize?state=abc&client_id=x"))
        finally:
            service_auth._WAITING.pop("calendar", None)
            service_auth._PENDING.pop("abc", None)
        self.assertIn("https://auth.example/authorize?state=abc", told[0])

    def test_the_browser_coming_back_hands_the_code_over(self):
        provider = service_auth.provider(_record())
        with _Loop() as loop:
            loop.run(provider.context.redirect_handler(
                "https://auth.example/authorize?state=xyz"))
            waiting = asyncio.run_coroutine_threadsafe(
                provider.context.callback_handler(), loop.loop)
            self.assertTrue(service_auth.arrived("the-code", "xyz"))
            result = waiting.result(5)
        self.assertEqual(result.code, "the-code")
        self.assertEqual(result.state, "xyz")

    def test_a_state_nobody_sent_is_not_accepted(self):
        self.assertFalse(service_auth.arrived("code", "never-sent"))


@tag("world")
class TheCallbackPage(GameTest):

    def get(self, **query):
        request = RequestFactory().get("/services/oauth/callback", query)
        return service_auth.callback_view(request)

    def test_nothing_waiting(self):
        reply = self.get(code="c", state="nope")
        self.assertEqual(reply.status_code, 400)

    def test_the_service_said_no(self):
        reply = self.get(error="access_denied", state="s")
        self.assertEqual(reply.status_code, 400)
        self.assertIn("access_denied", reply.content.decode())

    def test_somebody_waiting(self):
        with mock.patch.object(service_auth, "arrived", return_value=True) as got:
            reply = self.get(code="c", state="s")
        self.assertEqual(reply.status_code, 200)
        got.assert_called_once_with("c", "s", None)

    def test_it_is_routed(self):
        from django.urls import resolve

        self.assertIs(resolve("/services/oauth/callback").func,
                      service_auth.callback_view)


@tag("world")
class StartingIt(GameTest):

    def test_a_service_not_set_to_oauth(self):
        services.put(_record(auth=services.NO_AUTH))
        self.assertIn("not set", service_auth.begin("calendar"))

    def test_a_command_cannot_be(self):
        services.put(_record(kind=services.COMMAND))
        self.assertIn("web address", service_auth.begin("calendar"))

    def test_it_connects_with_a_long_wait_and_says_how_it_went(self):
        services.put(_record())
        told = []
        caller = mock.Mock(msg=told.append)
        seen = {}

        def listing(record, timeout=None):
            seen["timeout"] = timeout
            return {}, ""

        with immediately(), mock.patch.object(services, "connect_and_list", listing):
            said = service_auth.begin("calendar", caller)
        self.assertIn("browser", said)
        self.assertEqual(seen["timeout"], service_auth.AUTHORISE_WAIT)
        self.assertIn("authorised", told[-1])

    @override_settings(SERVICES_PUBLIC_URL="")
    def test_without_a_public_address_it_says_where_it_works(self):
        services.put(_record())
        with immediately(), mock.patch.object(services, "connect_and_list",
                                              lambda record, timeout=None: ({}, "")):
            said = service_auth.begin("calendar")
        self.assertIn("this machine", said)
