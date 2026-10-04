"""
OAuth for a service: authorised once, by an admin, as the server.

docs/mcp-client.md §11. The SDK's `OAuthClientProvider` runs the flow; this is
what it needs from the game:

* **A token store**, per service and never per account. Every credential is
  the server's (§4.4): nobody authorises a service as themselves, so no
  character can ever act as the player who made it.
* **Somewhere for the browser to come back to.** A Django view at
  `/services/oauth/callback`, in the Server process beside the connection
  manager, hands the code straight to the provider that is waiting for it.
* **Somebody to send there.** `edit service <name> authorise` starts a
  connection; when the provider has an address for the admin to open, they
  are told it. The redirect lands in their own browser, so `localhost` works
  for somebody at the machine; anybody else needs `SERVICES_PUBLIC_URL`.

Nothing here writes the database from the loop thread. The store keeps what
it was given in memory and writes it back on the reactor.
"""

import asyncio
import threading
from urllib.parse import parse_qs, urlparse

from evennia.utils import logger

#: Where the browser comes back to, under the game's web address.
CALLBACK_PATH = "services/oauth/callback"

#: Seconds the first authorisation may wait for somebody to click through.
#: Far longer than a call may take, because a person is reading a consent
#: page; and finite, because a connection held open for ever is a leak.
AUTHORISE_WAIT = 600

#: Who asked to authorise each service, to be told where to go. In memory: a
#: reload ends every authorisation in progress, and that is said, not hidden.
_WAITING = {}

#: Authorisations waiting on the browser, by OAuth `state`.
_PENDING = {}
_LOCK = threading.Lock()


def public_url():
    """The game's web address as the browser sees it, with no trailing slash."""
    from django.conf import settings

    said = str(getattr(settings, "SERVICES_PUBLIC_URL", "") or "").strip()
    if said:
        return said.rstrip("/")
    ports = getattr(settings, "WEBSERVER_PORTS", None) or [(4001, 4005)]
    return f"http://localhost:{ports[0][0]}"


def callback_url():
    return f"{public_url()}/{CALLBACK_PATH}"


def _on_reactor(work, *args):
    """Run `work` on the reactor, or at once when there is no reactor running."""
    from twisted.internet import reactor

    if reactor.running:
        reactor.callFromThread(work, *args)
    else:
        work(*args)


class Store:
    """
    The SDK's `TokenStorage`, over one service's record.

    Reads come from memory -- the record as it was when the connection was
    made -- and writes go there at once and to the register on the reactor.
    """

    def __init__(self, record):
        self.name = record.get("name")
        held = dict(record.get("oauth") or {})
        self.tokens = held.get("tokens")
        self.client = held.get("client")

    async def get_tokens(self):
        from mcp.shared.auth import OAuthToken

        return OAuthToken.model_validate(self.tokens) if self.tokens else None

    async def set_tokens(self, tokens):
        self.tokens = tokens.model_dump(mode="json", exclude_none=True)
        _on_reactor(_persist, self.name, "tokens", self.tokens)

    async def get_client_info(self):
        from mcp.shared.auth import OAuthClientInformationFull

        return (OAuthClientInformationFull.model_validate(self.client)
                if self.client else None)

    async def set_client_info(self, client_info):
        self.client = client_info.model_dump(mode="json", exclude_none=True)
        _on_reactor(_persist, self.name, "client", self.client)


def _persist(name, key, value):
    from world import services

    record = services.get(name)
    if record is None:
        return
    held = dict(record.get("oauth") or {})
    held[key] = value
    record["oauth"] = held
    services.put(record)


def provider(record):
    """The httpx auth for one service: the SDK's provider, wired to the game."""
    from mcp.client.auth import OAuthClientProvider
    from mcp.shared.auth import OAuthClientMetadata

    from django.conf import settings

    name = record.get("name")
    waiting = {}

    async def redirect(url):
        state = (parse_qs(urlparse(url).query).get("state") or [""])[0]
        loop = asyncio.get_running_loop()
        future = loop.create_future()
        waiting["future"] = future
        with _LOCK:
            _PENDING[state] = (loop, future, name)
        caller = _WAITING.get(name)
        said = (f"To let this game use |w{name}|n, open this address and agree "
                f"to it:\n{url}\nIt comes back to {callback_url()}.")
        if caller is not None:
            _on_reactor(caller.msg, said)
        logger.log_info(f"services: {name} wants authorising at {url}")

    async def callback():
        future = waiting.get("future")
        if future is None:
            raise RuntimeError("nothing was sent to be authorised")
        return await asyncio.wait_for(future, AUTHORISE_WAIT)

    metadata = OAuthClientMetadata(
        client_name=f"aimud ({getattr(settings, 'SERVERNAME', 'aimud')})",
        redirect_uris=[callback_url()],
        grant_types=["authorization_code", "refresh_token"],
        response_types=["code"],
    )
    return OAuthClientProvider(
        server_url=record.get("url") or "", client_metadata=metadata,
        storage=Store(record), redirect_handler=redirect,
        callback_handler=callback)


def arrived(code, state, iss=None):
    """
    The browser came back. True when somebody was waiting for it.

    Called on the reactor by the view; the provider waiting is on the loop
    thread, so the answer is handed across rather than set here.
    """
    from mcp.shared.auth import AuthorizationCodeResult

    with _LOCK:
        pending = _PENDING.pop(str(state or ""), None)
    if pending is None:
        return False
    loop, future, _name = pending
    result = AuthorizationCodeResult(code=str(code), state=state, iss=iss)
    loop.call_soon_threadsafe(
        lambda: future.done() or future.set_result(result))
    return True


def begin(name, caller=None):
    """
    Start authorising a service. Answers what to tell whoever asked.

    Connects, with a long wait: the provider finds there is no token, sends
    for one, and `redirect` tells the caller where to go. When they agree and
    the browser comes back, the connection lists the tools as any refresh
    does, and the caller is told how it went.
    """
    from world import llm, services

    record = services.get(name)
    if record is None:
        return f"There is no service called {name}."
    if record.get("auth") != services.OAUTH:
        return (f"{name} is not set to be authorised with OAuth. "
                f"|wedit service {name} auth oauth|n sets it.")
    if record.get("kind") != services.URL:
        return "Only a service at a web address can be authorised with OAuth."
    _WAITING[name] = caller

    def done(result):
        _WAITING.pop(name, None)
        tools, status = result
        fresh = services.get(name)
        if fresh is None:
            return
        if tools is not None:
            fresh["tools"] = services.merge_tools(fresh.get("tools"), tools)
        fresh["status"] = status
        services.put(fresh)
        if caller is not None:
            caller.msg(f"|w{name}|n could not be authorised: {status}" if status
                       else f"|w{name}|n is authorised, as this server, and its "
                            f"tools are listed. |wview service {name}|n.")

    def failed(failure):
        _WAITING.pop(name, None)
        logger.log_info(f"services: authorising {name} failed: {failure}")
        if caller is not None:
            caller.msg(f"Authorising {name} went wrong.")

    llm.fetch(services.connect_and_list, record, AUTHORISE_WAIT,
              on_success=done, on_error=failed)
    note = _reachable_note()
    return (f"Connecting to {name} to authorise it. You will be given an "
            f"address to open in a browser; it comes back to "
            f"{callback_url()}." + (f" {note}" if note else ""))


def _reachable_note():
    """What to say when the callback address is only good on this machine."""
    from django.conf import settings

    if getattr(settings, "SERVICES_PUBLIC_URL", ""):
        return ""
    return ("That address only works from a browser on this machine; set "
            "SERVICES_PUBLIC_URL in settings for anywhere else.")


def callback_view(request):
    """`/services/oauth/callback`: where the browser comes back to."""
    from django.http import HttpResponse

    code = request.GET.get("code")
    state = request.GET.get("state")
    error = request.GET.get("error")
    if error:
        return HttpResponse(f"The service said no: {error}. Nothing was "
                            f"authorised.", status=400,
                            content_type="text/plain; charset=utf-8")
    if not code or not arrived(code, state, request.GET.get("iss")):
        return HttpResponse("Nothing here was waiting for that. Start again "
                            "with edit service <name> authorise.",
                            status=400,
                            content_type="text/plain; charset=utf-8")
    return HttpResponse("Done. You can close this and go back to the game.",
                        content_type="text/plain; charset=utf-8")
