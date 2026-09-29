"""
The MCP endpoint, and the session behind it.

Phases 1, 3 and 5 of docs/mcp.md. This runs in the **Portal**, which is where
Evennia's protocols live and the only place a new way in can be added without
inventing one. It is modelled on `evennia/server/portal/webclient_ajax.py`
almost line for line, because that is an HTTP resource that makes sessions and
is therefore the existence proof this plan rested on.

Nothing here touches the database or imports a game module. A token is checked
by `world/agents.py` in the Server, reached the way every other structured
message reaches it: an inputfunc. §3.4.

**An MCP session is an Evennia session** (§3.2). Once `initialize` has been
answered there is a session in the handler, logged in, puppeting a character,
and every part of the game that knows what a session is now knows about the
agent: `who` lists it, `@boot` removes it, a menu will open for it, and an NPC
speaking in the room reaches it without anything here asking.

The transport is MCP's streamable HTTP: one endpoint, `POST` carrying a
JSON-RPC message, the reply as `application/json`. `Mcp-Session-Id` carries
the session between calls and is the id the Evennia session is filed under
here. `DELETE` ends it, as does an idle timeout, as does `@boot`.

Two tools are answered here and every other tool is forwarded. `send` and
`poll` are about this connection -- what was typed, what has been said since
-- and the Portal is where that lives. Everything else is a question about the
game, and the game is in the other process.
"""

import json
import time
import uuid

from twisted.internet import reactor
from twisted.web import resource, server

from evennia.server import session
from evennia.utils import logger
from evennia.utils.ansi import parse_ansi
from evennia.utils.utils import ip_from_request, to_bytes, to_str

#: JSON-RPC 2.0, and the revision of MCP this speaks.
JSONRPC = "2.0"
PROTOCOL_VERSION = "2025-06-18"

#: How long the endpoint waits for the mud to stop talking before it answers a
#: `send`. A mud replies when it is ready and not before: a command that moves
#: you prints the room, and a command that wakes an NPC may print again a
#: moment later. Waiting for quiet is the honest way to read a stream with no
#: end marker, and it is what a person staring at a terminal does too.
SETTLE = 0.25

#: The longest a single `send` waits for quiet, however talkative the room is.
MOST_WAIT = 10.0

#: The longest `poll` blocks when the mud has said nothing at all.
POLL_WAIT = 20.0

#: The longest a forwarded tool call waits for the Server to answer.
TOOL_WAIT = 30.0

#: How long a session may go untouched before the Portal drops it, and how
#: often the sweep looks.
IDLE = 3600
SWEEP = 60

#: The most one tool result may say, in characters. `toolbox.MOST_RESULT` is
#: the same number for the same reason, and cannot be imported here.
MOST_RESULT = 4000
CUT_SHORT = "\n[... cut short: ask again for less, or for the rest]"

#: JSON-RPC's own codes, plus the one MCP adds for a dead session.
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603

#: The tools this process answers without asking the Server.
LOCAL_TOOLS = {
    "send": {
        "name": "send",
        "description": (
            "Type one line into the mud, as a player would, and read what it "
            "says back. This is the whole game: every command, and every "
            "point in every menu, is reachable by typing. Prompts are "
            "included in the reply."),
        "inputSchema": {
            "type": "object",
            "properties": {
                "line": {
                    "type": "string",
                    "description": "The line to type, without a newline.",
                },
            },
            "required": ["line"],
        },
    },
    "poll": {
        "name": "poll",
        "description": (
            "Read whatever the mud has said since you last read it, without "
            "typing anything. Waits a short while if it has said nothing, so "
            "you can listen for an NPC or an event rather than asking over "
            "and over."),
        "inputSchema": {
            "type": "object",
            "properties": {
                "wait": {
                    "type": "number",
                    "description": (
                        "Seconds to wait for something to happen before "
                        "answering with nothing. Zero answers at once."),
                },
            },
        },
    },
}


def _error(id_, code, message, data=None):
    body = {"code": code, "message": message}
    if data is not None:
        body["data"] = data
    return {"jsonrpc": JSONRPC, "id": id_, "error": body}


def _result(id_, value):
    return {"jsonrpc": JSONRPC, "id": id_, "result": value}


def _content(text, failed=False):
    """A tool result in MCP's shape: content, and whether it went wrong."""
    text = str(text or "")
    if len(text) > MOST_RESULT:
        text = text[:MOST_RESULT] + CUT_SHORT
    return {"content": [{"type": "text", "text": text}], "isError": failed}


def _plain(text):
    """
    Text as an agent should read it: no colour, no markup, nothing to strip.

    §3.3. The session declares itself as taking none of it, so this is belt
    and braces rather than the only guard -- but a world is free to write a
    code into a description by hand, and an agent reading `|w` as a word would
    be reading the world wrongly.
    """
    return parse_ansi(to_str(text), strip_ansi=True, xterm256=False, mxp=False)


class McpSession(session.Session):
    """
    One agent's connection, as the rest of Evennia sees it.

    The buffer is the only thing here a telnet session does not have, and it
    exists because MCP is request-shaped and a mud is not: between one `send`
    and the next the world goes on happening, and what it said has to be
    somewhere when the agent next asks. §5.2.
    """

    def __init__(self, *args, **kwargs):
        self.protocol_key = "mcp"
        super().__init__(*args, **kwargs)
        self.lines = []
        self.structured = {}
        self.waiting = None
        self.timer = None
        self.last_seen = time.time()
        self.tools = {}

    # -- the session handler's side -----------------------------------------

    def disconnect(self, reason="Server disconnected."):
        self.note(reason)
        self.client.session_closed(self.csessid)
        self.sessionhandler.disconnect(self)

    def at_login(self):
        pass

    def data_in(self, **kwargs):
        self.sessionhandler.data_in(self, **kwargs)

    def data_out(self, **kwargs):
        self.sessionhandler.data_out(self, **kwargs)

    # -- what the mud says --------------------------------------------------

    def note(self, text, prompt=False):
        """Put a line in the buffer and wake anybody waiting on one."""
        text = str(text or "")
        if not text.strip():
            return
        self.lines.append({"text": text, "prompt": prompt})
        self.client.stirred(self)

    def send_text(self, *args, **kwargs):
        if not args or args[0] is None:
            return
        options = kwargs.get("options") or {}
        self.note(_plain(args[0]), prompt=bool(options.get("send_prompt")))

    def send_prompt(self, *args, **kwargs):
        if args and args[0] is not None:
            self.note(_plain(args[0]), prompt=True)

    def send_default(self, cmdname, *args, **kwargs):
        """
        Anything that is not prose: a tool's answer, a login's verdict.

        Filed by name so whoever asked can collect it. `options` is Evennia
        telling a client about its own capabilities and is none of our
        business.
        """
        if cmdname == "options":
            return
        self.structured.setdefault(cmdname, []).append(
            {"args": list(args), "kwargs": dict(kwargs)})
        self.client.stirred(self)

    def take(self, name):
        """Everything filed under a structured name, and forget it."""
        return self.structured.pop(name, [])

    def drain(self):
        """Every line said since last time, and forget them."""
        lines, self.lines = self.lines, []
        return lines


class McpResource(resource.Resource):
    """
    The endpoint. One of these, serving every agent.

    Holds the sessions by their MCP session id and the request each is
    waiting on. A request is answered when the mud goes quiet, when the thing
    it asked for arrives, or when it has waited long enough -- never by
    guessing that nothing more is coming.
    """

    isLeaf = True

    def __init__(self, sessionhandler):
        super().__init__()
        self.sessions = {}
        self.sessionhandler = sessionhandler
        self.protocol_class = McpSession
        self.calls = 0
        reactor.callLater(SWEEP, self._sweep)

    # -- waiting, and being woken -------------------------------------------

    def stirred(self, sess):
        """
        The mud has said something on this session.

        A waiter with an `until` is looking for one particular thing and
        ignores everything else. One without is collecting a reply, so any
        line restarts its quiet timer: the room is still talking, and the
        answer is not ready.
        """
        waiting = sess.waiting
        if not waiting:
            return
        until = waiting.get("until")
        if until is not None:
            if until():
                self._finish(sess)
            return
        if sess.timer and sess.timer.active():
            sess.timer.cancel()
        if time.time() >= waiting["deadline"]:
            self._finish(sess)
            return
        sess.timer = reactor.callLater(waiting["settle"], self._finish, sess)

    def _finish(self, sess):
        waiting, sess.waiting = sess.waiting, None
        if sess.timer and sess.timer.active():
            sess.timer.cancel()
        sess.timer = None
        if waiting and waiting.get("then"):
            waiting["then"]()

    def _wait(self, sess, then, settle=SETTLE, most=MOST_WAIT, until=None):
        """
        Call `then` when the mud has been quiet for `settle` seconds, or when
        `until()` first says yes, or when `most` seconds have gone by.
        """
        self._finish(sess)
        sess.waiting = {"then": then, "settle": settle, "until": until,
                        "deadline": time.time() + most}
        sess.timer = reactor.callLater(
            most if until is not None else settle, self._finish, sess)

    # -- sessions -----------------------------------------------------------

    def session_closed(self, csessid):
        sess = self.sessions.pop(csessid, None)
        if sess is not None:
            self._finish(sess)

    def _sweep(self):
        reactor.callLater(SWEEP, self._sweep)
        cutoff = time.time() - IDLE
        for csessid, sess in list(self.sessions.items()):
            if sess.last_seen < cutoff:
                logger.log_info(f"mcp: session {csessid} idled out")
                sess.disconnect("Idle.")

    def _open(self, request, token, then):
        """
        A session, connected and told to log itself in.

        The verdict comes back from the Server as a structured `mcp_auth`,
        because the Portal has no database and no business having one. Until
        it arrives this session is connected and unauthenticated, which is
        exactly what a telnet session is between `connect` and the password
        being right.
        """
        csessid = uuid.uuid4().hex
        sess = self.protocol_class()
        sess.client = self
        sess.init_session("mcp", ip_from_request(request), self.sessionhandler)
        sess.csessid = csessid
        sess.protocol_flags.update({
            "ENCODING": "utf-8",
            "UTF-8": True,
            "OOB": True,
            "ANSI": False,
            "XTERM256": False,
            "MXP": False,
            "NOCOLOR": True,
            "SCREENREADER": True,
            "CLIENTNAME": "aimud MCP",
            "INPUTDEBUG": False,
        })
        self.sessions[csessid] = sess
        self.sessionhandler.connect(sess)
        self._wait(sess, then, most=TOOL_WAIT,
                   until=lambda: bool(sess.structured.get("mcp_auth")))
        self._once_connected(sess, lambda: sess.data_in(mcp_auth=((token,), {})))
        return sess

    def _once_connected(self, sess, then, waited=0.0):
        """
        Do `then` when the Server has actually heard of this session.

        `connect()` does not connect: it puts the session on a queue behind a
        throttle that exists to stop a flood of connections, and only then
        tells the Server about it over AMP. Anything sent in before that is
        sent on behalf of a session the Server has never heard of, and is
        dropped in silence -- which is what the phase 0 spike spent its second
        run finding out. A person typing cannot lose this race and an agent
        calling `initialize` always does.
        """
        if getattr(sess, "server_connected", False):
            then()
            return
        if waited >= TOOL_WAIT:
            logger.log_err("mcp: session never reached the Server")
            return
        reactor.callLater(0.05, self._once_connected, sess, then, waited + 0.05)

    # -- HTTP ----------------------------------------------------------------

    def render_POST(self, request):
        try:
            body = json.loads(request.content.read() or b"{}")
        except (ValueError, TypeError):
            return self._reply(request, _error(None, PARSE_ERROR,
                                               "That was not JSON."), 400)
        if not isinstance(body, dict):
            return self._reply(request, _error(None, INVALID_REQUEST,
                                               "A message is an object."), 400)
        return self._dispatch(request, body)

    def render_DELETE(self, request):
        sess = self._session_of(request)
        if sess is not None:
            sess.disconnect("The agent disconnected.")
        request.setResponseCode(204)
        return b""

    def render_GET(self, request):
        """
        No server-initiated stream. `poll` is how the mud reaches an agent
        (§14), and until that proves not to be enough there is nothing here.
        """
        request.setResponseCode(405)
        request.setHeader(b"allow", b"POST, DELETE")
        return b""

    # -- dispatch ------------------------------------------------------------

    def _dispatch(self, request, body):
        method = body.get("method")
        id_ = body.get("id")
        params = body.get("params") or {}
        if not isinstance(params, dict):
            return self._reply(request, _error(
                id_, INVALID_PARAMS, "Parameters are an object."), 400)

        if method == "initialize":
            return self._initialize(request, id_, params)
        if id_ is None:
            # A notification. Nothing here needs answering, and JSON-RPC says
            # a notification gets no reply at all.
            request.setResponseCode(202)
            return b""

        sess = self._session_of(request)
        if sess is None:
            return self._reply(request, _error(
                id_, INVALID_REQUEST,
                "No session. Call initialize first; if you had one, it has "
                "been closed."), 404)
        sess.last_seen = time.time()

        if method == "ping":
            return self._reply(request, _result(id_, {}))
        if method == "tools/list":
            return self._reply(request, _result(id_, {
                "tools": list(LOCAL_TOOLS.values()) + list(sess.tools.values()),
            }))
        if method == "tools/call":
            return self._call(request, sess, id_, params)
        return self._reply(request, _error(
            id_, METHOD_NOT_FOUND, f"No method called {method!r}."), 404)

    def _initialize(self, request, id_, params):
        token = self._token_of(request)
        if not token:
            request.setHeader(b"www-authenticate", b'Bearer realm="aimud"')
            return self._reply(request, _error(
                id_, INVALID_REQUEST,
                "This mud wants a bearer token. Type `settings agenttoken` "
                "in the game to mint one."), 401)

        def answered():
            verdict = sess.take("mcp_auth")
            if not verdict:
                sess.disconnect("Nobody answered.")
                self._reply(request, _error(
                    id_, INTERNAL_ERROR,
                    "The game did not answer in time."), 503)
                return
            args = verdict[0]["args"]
            ok = bool(args[0]) if args else False
            said = args[1] if len(args) > 1 else ""
            if not ok:
                sess.disconnect("Refused.")
                request.setHeader(b"www-authenticate", b'Bearer realm="aimud"')
                self._reply(request, _error(
                    id_, INVALID_REQUEST, said or "That token is not known."),
                    401)
                return
            tools = sess.take("mcp_tools")
            if tools and tools[0]["args"]:
                for tool in tools[0]["args"][0] or []:
                    sess.tools[tool["name"]] = tool
            request.setHeader(b"mcp-session-id",
                              to_bytes(sess.csessid))
            self._reply(request, _result(id_, {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "aimud", "version": "1"},
                "instructions": said or None,
            }))

        sess = self._open(request, token, answered)
        request.notifyFinish().addErrback(lambda _: self._finish(sess))
        return server.NOT_DONE_YET

    def _call(self, request, sess, id_, params):
        name = params.get("name")
        args = params.get("arguments") or {}
        if not isinstance(args, dict):
            return self._reply(request, _error(
                id_, INVALID_PARAMS, "Arguments are an object."), 400)
        if name == "send":
            return self._send(request, sess, id_, args)
        if name == "poll":
            return self._poll(request, sess, id_, args)
        if name in sess.tools:
            return self._forward(request, sess, id_, name, args)
        return self._reply(request, _error(
            id_, INVALID_PARAMS, f"No tool called {name!r}."), 404)

    def _send(self, request, sess, id_, args):
        line = args.get("line")
        if not isinstance(line, str) or not line.strip():
            return self._reply(request, _result(
                id_, _content("A line to type is required.", failed=True)))

        def answered():
            self._reply(request, _result(
                id_, _content(_said(sess.drain()) or "(nothing was said)")))

        self._wait(sess, answered, settle=SETTLE, most=MOST_WAIT)
        request.notifyFinish().addErrback(lambda _: self._finish(sess))
        sess.data_in(text=((line,), {}))
        return server.NOT_DONE_YET

    def _poll(self, request, sess, id_, args):
        if sess.lines:
            return self._reply(request, _result(id_, _content(
                _said(sess.drain()))))
        try:
            wait = min(float(args.get("wait", POLL_WAIT)), POLL_WAIT)
        except (TypeError, ValueError):
            wait = POLL_WAIT
        if wait <= 0:
            return self._reply(request, _result(
                id_, _content("(nothing has been said)")))

        def answered():
            self._reply(request, _result(id_, _content(
                _said(sess.drain()) or "(nothing has been said)")))

        self._wait(sess, answered, most=wait, until=lambda: bool(sess.lines))
        request.notifyFinish().addErrback(lambda _: self._finish(sess))
        return server.NOT_DONE_YET

    def _forward(self, request, sess, id_, name, args):
        """A tool the Server owns: hand it over and wait for the answer."""
        self.calls += 1
        ticket = str(self.calls)

        def arrived():
            answers = [entry for entry in sess.take("mcp_tool")
                       if entry["args"] and entry["args"][0] == ticket]
            if not answers:
                self._reply(request, _result(id_, _content(
                    "The game did not answer in time.", failed=True)))
                return
            said = answers[0]["args"]
            text = said[1] if len(said) > 1 else ""
            failed = bool(said[2]) if len(said) > 2 else False
            self._reply(request, _result(id_, _content(text, failed=failed)))

        self._wait(sess, arrived, most=TOOL_WAIT,
                   until=lambda: any(
                       entry["args"] and entry["args"][0] == ticket
                       for entry in sess.structured.get("mcp_tool", [])))
        request.notifyFinish().addErrback(lambda _: self._finish(sess))
        sess.data_in(mcp_tool=((ticket, name, args), {}))
        return server.NOT_DONE_YET

    # -- small helpers -------------------------------------------------------

    def _token_of(self, request):
        header = request.getHeader(b"authorization") or b""
        header = to_str(header).strip()
        if header.lower().startswith("bearer "):
            return header[7:].strip()
        return ""

    def _session_of(self, request):
        csessid = request.getHeader(b"mcp-session-id")
        if not csessid:
            return None
        return self.sessions.get(to_str(csessid).strip())

    def _reply(self, request, body, code=200):
        """
        Answer one request and be done with it.

        Always returns `NOT_DONE_YET`, even where the answer was ready all
        along: this finishes the request itself, and a `render_` method that
        finishes a request and then also returns a body makes Twisted write to
        a closed request and drop the connection with nothing sent. Which is
        how the phase 0 spike spent its first run.
        """
        if request.finished or request._disconnected:
            return server.NOT_DONE_YET
        request.setResponseCode(code)
        request.setHeader(b"content-type", b"application/json")
        try:
            request.write(to_bytes(json.dumps(body, ensure_ascii=False)))
            request.finish()
        except Exception:
            logger.log_trace()
        return server.NOT_DONE_YET


def _said(lines):
    """The buffer as one piece of text, prompts marked as prompts."""
    said = []
    for line in lines:
        text = line["text"].rstrip()
        if not text:
            continue
        said.append(f"> {text}" if line.get("prompt") else text)
    return "\n".join(said)
