"""
Services: what the server owner has let this game reach outside itself for.

An MCP server run as a command, one reached at a URL, or an OpenAPI service,
added in game by whoever runs the machine. See docs/archived/mcp-client.md, which this
module is the register and the plumbing of.

**Every credential is the server's.** A service is configured once, with the
server's own key or token, and there is no per-account service and never will
be: a character a player made is not that player, and must never act on that
player's email because the player happened to make it. §4.4.

**The owner classifies.** Each tool is *contained* (nothing leaves the
machine), *looks outward* (a query goes out, nothing changes) or *acts
outward* (something out there changes and stays changed). MCP's annotations,
or an OpenAPI operation's method, only fill in the first guess; the owner's
answer is the one the game uses. §5.

**One gate.** A character may use a service wherever a model could be called
for it, and not elsewhere. A player may use a contained or looks-outward tool
anywhere, and an acts-outward one wherever a model could be called for them.
`allowed` is that table, and it is the only place it is written. §5.3.

**Where it runs.** The SDK is asyncio and Evennia is Twisted, so one asyncio
loop runs in one daemon thread in the Server process, started the first time a
service is used. It owns a long-lived session per service, so a command is
started once rather than per call. Everything here that talks to a service is
*blocking work*, handed to `llm.fetch` by its caller: the worker thread waits
on the loop, and the answer comes back on the reactor the way every model
answer does. Nothing here touches the database from a worker thread; the
register is read on the reactor and handed in by value. §3.2.

**OpenAPI is an MCP server we start ourselves.** FastMCP builds one from the
spec, and it is served in process, so an OpenAPI service is one more session:
listing, calling and fingerprints are one code path. §3.3.
"""

import asyncio
import hashlib
from collections.abc import Mapping, Sequence
import json
import re
import shlex
import threading
from urllib.parse import urlparse

from evennia.utils import logger

# ---------------------------------------------------------------------------
# Vocabulary
# ---------------------------------------------------------------------------

#: How a service is reached, and who may add one. A command is a process this
#: server starts, which is running code, so it needs the permission `py`
#: already needs. A URL or a spec is network access, which is the owner's
#: decision, so it needs an admin.
COMMAND, URL, OPENAPI = "command", "url", "openapi"
KINDS = (
    (COMMAND, "A command this server runs (an MCP server over stdio)",
     "Developer"),
    (URL, "An MCP server at a web address", "Admin"),
    (OPENAPI, "An OpenAPI service, described by its spec", "Admin"),
)
KIND_NAMES = tuple(kind for kind, _said, _perm in KINDS)

#: What a tool does outside the game. See the module docstring.
CONTAINED, LOOKS, ACTS = "contained", "looks", "acts"
LEVELS = (
    (CONTAINED, "contained",
     "nothing leaves the machine: dice, a calculator, a local word list"),
    (LOOKS, "looks outward",
     "a query goes out, and nothing out there changes: weather, a search"),
    (ACTS, "acts outward",
     "something out there changes and stays changed: an email, a post"),
)
LEVEL_NAMES = tuple(level for level, _said, _why in LEVELS)

#: How an API key is sent, for a URL or a spec.
NO_AUTH, KEY_AUTH, OAUTH = "none", "key", "oauth"
AUTHS = (
    (NO_AUTH, "Nothing: the service is open"),
    (KEY_AUTH, "An API key"),
    (OAUTH, "OAuth, authorised once by an admin"),
)
HEADER, QUERY, BEARER = "header", "query", "bearer"
KEY_PLACES = (
    (HEADER, "In a header you name"),
    (QUERY, "As a query parameter you name"),
    (BEARER, "As a bearer token (Authorization: Bearer ...)"),
)

#: Where the register lives: one value in Evennia's `ServerConfig`, which
#: pickles whatever it is given. Server-wide, never on a world or an account.
REGISTER_KEY = "aimud_services"

#: Seconds a call may take, unless the service says otherwise.
TIMEOUT = 30

#: How long a tool's description may be when a rule copies it. Descriptions
#: are written for models and run long; a rule keeps the gist. §7.1.
DOES_LENGTH = 400

#: How many acts-outward calls are kept per service for its owner to read.
RECENT = 50

#: A service name: what worlds name it by, so it has to survive a document.
NAME = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")


def said_level(level):
    for name, said, _why in LEVELS:
        if name == level:
            return said
    return str(level or "unknown")


def said_kind(kind):
    for name, said, _perm in KINDS:
        if name == kind:
            return said
    return str(kind or "unknown")


def permission_for(kind):
    for name, _said, perm in KINDS:
        if name == kind:
            return perm
    return "Developer"


# ---------------------------------------------------------------------------
# The register
# ---------------------------------------------------------------------------

def _config():
    from evennia.server.models import ServerConfig

    return ServerConfig.objects


def register():
    """Every service this server has, as {name: record}. A copy."""
    stored = _config().conf(REGISTER_KEY, default=None) or {}
    try:
        return {str(name): dict(record) for name, record in dict(stored).items()}
    except (TypeError, ValueError):
        return {}


def _save(records):
    _config().conf(REGISTER_KEY, value=dict(records))


def get(name):
    """One service's record, or None."""
    return register().get(str(name or "").strip().lower())


def names():
    return sorted(register())


def put(record):
    """Write one service's record, replacing whatever had its name."""
    records = register()
    records[record["name"]] = dict(record)
    _save(records)


def remove(name):
    """Forget a service. What its tools did to worlds stays done."""
    records = register()
    gone = records.pop(str(name or "").strip().lower(), None)
    _save(records)
    _manager().drop(str(name or "").strip().lower())
    return gone is not None


def blank(name="", kind=URL):
    """Every slot a record has, so nothing reading one has to guess."""
    return {
        "name": name, "kind": kind,
        "command": "", "args": [], "env": {},
        "url": "", "spec": "", "headers": {},
        "auth": NO_AUTH, "key_place": HEADER, "key_name": "", "key": "",
        "timeout": TIMEOUT,
        "tools": {}, "status": "", "recent": [],
        "oauth": {},
    }


def name_complaint(name, existing=None):
    """Why this cannot name a service, or ''."""
    name = str(name or "").strip().lower()
    if not NAME.match(name):
        return ("A service's name is one word: lower-case letters, digits, "
                "dashes or underscores, starting with a letter, at most 32. "
                "Worlds name it by this.")
    if existing is not None and name in existing:
        return f"There is already a service called {name}."
    return ""


# ---------------------------------------------------------------------------
# Reading what a service says about its tools
# ---------------------------------------------------------------------------

def guess_level(annotations=None, method=None):
    """
    The first guess at a tool's level, from what the service says about it.

    MCP's annotations are hints, and the spec's defaults are the cautious
    ones: a tool that says nothing is open-world and not read-only, which is
    "acts outward" -- assume the worst. An OpenAPI operation has a method, and
    GET and HEAD are read-only by definition. Only ever a guess: the owner's
    answer replaces it. §5.2.
    """
    if method is not None:
        return LOOKS if str(method).upper() in ("GET", "HEAD") else ACTS
    hints = dict(annotations or {})
    if hints.get("openWorldHint") is False:
        return CONTAINED
    if hints.get("readOnlyHint") is True:
        return LOOKS
    return ACTS


def fingerprint(input_schema, output_schema):
    """
    What a world records about a tool it uses: the shape, not the words.

    Schemas only. A description is reworded freely and the rule keeps its own
    copy; a level is the importing owner's decision. Canonical JSON so key
    order cannot change it. §10.2.
    """
    canonical = json.dumps({"input": input_schema or {},
                            "output": output_schema or {}},
                           sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


#: What a parameter's schema may be, to be something a menu can ask for.
SCALARS = ("string", "number", "integer", "boolean")


def _type_of(schema):
    kind = (schema or {}).get("type")
    if isinstance(kind, Sequence) and not isinstance(kind, str):
        kinds = [k for k in kind if k != "null"]
        return kinds[0] if len(kinds) == 1 else None
    return kind


def plain(schema):
    """
    One value's schema with "or nothing" taken off it.

    `X | None` in Python comes out as `anyOf: [X, {"type": "null"}]` from
    Pydantic and FastMCP -- which is to say, every optional parameter of most
    Python MCP servers. That is one shape, optional, not several: refusing it
    refused kagi's own search over a domain list nobody had to give. A union
    of more than one real shape is left as it is, for `unfillable` to say so.
    """
    # Mapping and Sequence, never dict and list: a schema read back from the
    # register is Evennia's _SaverDict, which is neither, and a `dict` test
    # here refused every parameter of every stored tool.
    if not isinstance(schema, Mapping):
        return schema
    for key in ("anyOf", "oneOf"):
        branches = schema.get(key)
        if not isinstance(branches, Sequence) or isinstance(branches, str):
            continue
        real = [b for b in branches
                if not (isinstance(b, Mapping) and b.get("type") == "null")]
        if len(real) == 1 and isinstance(real[0], Mapping):
            merged = {k: v for k, v in schema.items() if k != key}
            merged.update(real[0])
            return plain(merged)
    return dict(schema)


def unfillable(param):
    """Why a rule could never fill this parameter, or '' when one can."""
    param = plain(param)
    if not isinstance(param, Mapping):
        return "it has no shape"
    if any(key in param for key in ("oneOf", "anyOf", "allOf", "$ref")):
        return "it may be one of several shapes"
    kind = _type_of(param)
    if kind in SCALARS or "enum" in param:
        return ""
    if kind == "array" and _type_of(plain(param.get("items") or {})) in SCALARS:
        return ""
    return f"it is {kind or 'of no stated type'}, which no menu can ask for"


def input_complaint(schema):
    """
    Why a tool's input cannot be written as a rule's arguments, or ''.

    A parameter is a scalar, an enum, or an array of scalars -- what a menu
    can ask for and a word or a figure can fill -- once "or nothing" is taken
    off it (`plain`). Only a *required* parameter of any other shape refuses
    the tool, so the owner sees why rather than finding out from a rule that
    cannot be written. An optional one is left out instead: no rule can name
    it, and the tool is called without it. §7.2.
    """
    schema = schema or {}
    if schema.get("type") not in (None, "object"):
        return "its input is not a set of named parameters"
    required = set(schema.get("required") or [])
    for name, param in (schema.get("properties") or {}).items():
        why = unfillable(param)
        if why and name in required:
            return f"{name} is required, and {why}"
    return ""


def parameters(schema, every=False):
    """
    [(name, schema, required)] a rule may fill, in the order the service
    listed them, each with "or nothing" taken off. `every` includes the
    optional ones no rule can fill, for somebody reading the tool in full.
    """
    schema = schema or {}
    required = set(schema.get("required") or [])
    return [(str(name), dict(plain(param) or {}), name in required)
            for name, param in (schema.get("properties") or {}).items()
            if every or not unfillable(param)]


def left_out(schema):
    """The optional parameters no rule can fill, and why: [(name, why)]."""
    return [(str(name), unfillable(param))
            for name, param in ((schema or {}).get("properties") or {}).items()
            if unfillable(param)]


def outputs(schema):
    """[(field, schema)] a result mapping may name, from an output schema."""
    return [(str(name), dict(plain(field) or {}))
            for name, field in ((schema or {}).get("properties") or {}).items()]


def is_bounded(field_schema):
    """Whether a result field has a closed set of answers: an enum or a boolean."""
    return "enum" in (field_schema or {}) or _type_of(field_schema) == "boolean"


def is_numeric(field_schema):
    return _type_of(field_schema) in ("number", "integer")


def is_text(field_schema):
    return _type_of(field_schema) == "string"


def merge_tools(old, listed, openapi=False):
    """
    The tool table after a fresh listing, keeping what the owner decided.

    A tool the owner has seen keeps its level and whether it is on, unless its
    shape changed -- then it is back to its guess and off, because what the
    owner agreed to is not what is there. A new tool gets its guess, on for an
    MCP server (whose author chose what to offer) and off for an OpenAPI
    service (whose spec lists everything the API has). §5.2, §12.
    """
    old = dict(old or {})
    merged = {}
    for name, info in listed.items():
        before = old.get(name)
        info = dict(info)
        if before and before.get("refused") and not info.get("refused") \
                and not before.get("decided"):
            # Refused by this game rather than switched off by the owner --
            # and this game has since learned to take it. It is as new as it
            # would have been the first time, not left off for a reason
            # nobody gave.
            before = None
        if before and before.get("fingerprint") == info["fingerprint"]:
            info["level"] = before.get("level", info["level"])
            info["on"] = bool(before.get("on", True))
            info["decided"] = bool(before.get("decided", False))
        else:
            info["on"] = not openapi and not before
            info["decided"] = False
        if info.get("refused"):
            info["on"] = False
        merged[name] = info
    return merged


def tool_id(service, tool):
    return f"{service}.{tool}"


def split_id(wanted):
    """('service', 'tool') from 'service.tool', or ('', '')."""
    service, _dot, tool = str(wanted or "").strip().partition(".")
    if not service or not tool:
        return "", ""
    return service.lower(), tool


def find(wanted, records=None):
    """(record, tool info) for 'service.tool', or (None, None)."""
    service, tool = split_id(wanted)
    record = (records if records is not None else register()).get(service)
    if record is None:
        return None, None
    info = (record.get("tools") or {}).get(tool)
    return (record, dict(info)) if info is not None else (record, None)


def usable(records=None):
    """
    Every tool a rule may name: switched on, and with input a rule can fill.

    As [(id, record, info)], sorted. What the rule generator's `list_tools`
    shows and what the rule form offers; tools switched off or refused are
    nobody's to write a rule with. §7.6.
    """
    found = []
    if _locked_down():
        return found
    for name, record in sorted((records or register()).items()):
        for tool, info in sorted((record.get("tools") or {}).items()):
            if info.get("on") and not info.get("refused"):
                found.append((tool_id(name, tool), record, dict(info)))
    return found


def does(info):
    """A tool's description as a rule keeps it: one paragraph, capped."""
    text = " ".join(str((info or {}).get("description") or "").split())
    if len(text) > DOES_LENGTH:
        text = text[:DOES_LENGTH - 3].rstrip() + "..."
    return text


# ---------------------------------------------------------------------------
# The gate
# ---------------------------------------------------------------------------

def _locked_down():
    from django.conf import settings

    return bool(getattr(settings, "LOCKDOWN_MODE", False))


def is_character(actor):
    """Whether this is a character the world plays, rather than a player."""
    return bool(getattr(getattr(actor, "db", None), "is_npc", False))


def allowed(sponsor, actor, level):
    """
    Whether this actor may use a tool of this level, here. §5.3.

    | | contained | looks outward | acts outward |
    | a player | yes | yes | where a model could be called |
    | a character | where a model could be called, at every level |

    A character that cannot call a model does not reach outside the game at
    all, which makes a world with no key easy to explain. An agent is a
    player. Nothing reaches out in `LOCKDOWN_MODE`.
    """
    if _locked_down():
        return False
    answers = bool(getattr(sponsor, "answers", False))
    if is_character(actor) or level == ACTS:
        return answers
    return True


def refusal(sponsor, actor, level):
    """Why not, in the words the no-key messages already use, or ''."""
    if allowed(sponsor, actor, level):
        return ""
    if _locked_down():
        return "Nothing here reaches outside the game while the server is locked down."
    return "Nobody is paying for this world to reach outside the game."


# ---------------------------------------------------------------------------
# Addresses this game refuses
# ---------------------------------------------------------------------------

def address_complaint(url):
    """
    Why this address may not be a service, or ''.

    aimud's own MCP endpoint is refused: the game driving itself as an agent
    would be a way round every gate in docs/archived/mcp.md. §4.3.
    """
    from django.conf import settings

    try:
        parsed = urlparse(str(url or "").strip())
    except ValueError:
        return "That is not a web address."
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return "A service's address starts with http:// or https://."
    own_port = int(getattr(settings, "MCP_PORT", 4007) or 0)
    local = parsed.hostname in ("localhost", "127.0.0.1", "::1", "0.0.0.0",
                                str(getattr(settings, "MCP_INTERFACE", "")))
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    if local and port == own_port:
        return ("That is this game's own MCP endpoint. A world reaching it "
                "would be the game playing itself, round every gate an agent "
                "goes through.")
    return ""


# ---------------------------------------------------------------------------
# What a call answers
# ---------------------------------------------------------------------------

class Answer:
    """
    What a tool sent back, in the three shapes a rule can use.

    `structured` is its `structuredContent`, or None; `text` is every text
    block joined; `error` is set when the tool said it failed, or the call
    never got an answer at all, and then `reached` says which -- a service
    that cannot be reached is not the rule's fault. §7.5.
    """

    def __init__(self, structured=None, text="", error="", reached=True,
                 files=()):
        self.structured = dict(structured) if isinstance(structured, Mapping) else None
        self.text = str(text or "")
        self.error = str(error or "")
        self.reached = reached
        #: Files the tool sent back -- an image, a sound -- as `(bytes, mime
        #: type)`, for `assets.from_tool` to keep. docs/archived/assets.md 11.
        self.files = list(files or [])

    @property
    def ok(self):
        return not self.error

    def field(self, name):
        """One field of the answer, from its structure, or None."""
        if self.structured is not None and name in self.structured:
            return self.structured[name]
        if self.text and self.structured is None:
            # A tool with no output schema that answered in JSON anyway.
            try:
                parsed = json.loads(self.text)
            except ValueError:
                return None
            if isinstance(parsed, dict):
                return parsed.get(name)
        return None

    def __repr__(self):
        return (f"Answer(structured={self.structured!r}, text={self.text[:40]!r}, "
                f"error={self.error!r}, reached={self.reached})")


# ---------------------------------------------------------------------------
# The loop, and one connection per service
# ---------------------------------------------------------------------------

def _client_info():
    from django.conf import settings
    from mcp_types import Implementation

    return Implementation(
        name="aimud", version="1",
        title=f"aimud ({getattr(settings, 'SERVERNAME', 'aimud')})",
        description="A multiplayer text game reaching out on behalf of its "
                    "players and characters.")


def _user_agent():
    from django.conf import settings

    return f"aimud ({getattr(settings, 'SERVERNAME', 'aimud')}; a multiplayer game)"


def _http_client(record, base_url=None):
    """An httpx client with the record's headers and key, as the SDK wants."""
    import httpx2

    headers = {"User-Agent": _user_agent()}
    headers.update({str(k): str(v) for k, v in (record.get("headers") or {}).items()})
    params = {}
    if record.get("auth") == KEY_AUTH and record.get("key"):
        place = record.get("key_place") or HEADER
        if place == BEARER:
            headers["Authorization"] = f"Bearer {record['key']}"
        elif place == QUERY:
            params[record.get("key_name") or "api_key"] = record["key"]
        else:
            headers[record.get("key_name") or "X-API-Key"] = record["key"]
    auth = None
    if record.get("auth") == OAUTH:
        from world import service_auth

        auth = service_auth.provider(record)
    kwargs = {"headers": headers, "params": params, "auth": auth,
              "timeout": float(record.get("timeout") or TIMEOUT)}
    if base_url:
        kwargs["base_url"] = base_url
    return httpx2.AsyncClient(**kwargs)


def _load_spec(record):
    """An OpenAPI spec, from a URL or a file, as a dict. Blocking."""
    source = str(record.get("spec") or "").strip()
    if not source:
        raise ValueError("no spec given")
    if source.startswith(("http://", "https://")):
        import httpx2

        reply = httpx2.get(source, headers={"User-Agent": _user_agent()},
                           timeout=float(record.get("timeout") or TIMEOUT))
        reply.raise_for_status()
        text = reply.text
    else:
        from pathlib import Path

        from django.conf import settings

        path = Path(source)
        if not path.is_absolute():
            path = Path(settings.GAME_DIR) / path
        text = path.read_text(encoding="utf-8")
    try:
        return json.loads(text)
    except ValueError:
        import yaml

        return yaml.safe_load(text)


def spec_methods(spec):
    """{operationId: method} for every operation in an OpenAPI spec."""
    found = {}
    for _path, item in ((spec or {}).get("paths") or {}).items():
        for method, operation in (item or {}).items():
            if isinstance(operation, Mapping) and operation.get("operationId"):
                found[str(operation["operationId"])] = method.upper()
    return found


def spec_key(spec):
    """
    (where, name) for an API key, from an OpenAPI spec's `securitySchemes`.

    The first `apiKey` scheme, or an HTTP bearer one, so the owner does not
    have to read the spec to fill in the form. (None, None) when the spec says
    nothing a key could be sent by. §12.
    """
    schemes = (((spec or {}).get("components") or {}).get("securitySchemes")
               or {})
    for scheme in schemes.values():
        scheme = scheme or {}
        if scheme.get("type") == "apiKey" and scheme.get("in") in ("header", "query"):
            return (HEADER if scheme["in"] == "header" else QUERY,
                    str(scheme.get("name") or ""))
        if scheme.get("type") == "http" and str(scheme.get("scheme")).lower() == "bearer":
            return BEARER, ""
    return None, None


def home_of(name):
    """
    `server/services/<name>/`: a command service's own home, made if missing.

    Its working directory and its `HOME`. A command that keeps state -- a
    history, a cache, a login -- keeps it here, as the server's, and not in
    the game directory or in whoever runs the server's own profile. Found
    with the first real service: on Windows the SDK passes a child no `HOME`,
    so kagi wrote `.\.cache` into the game directory. §4.4: every credential
    is the server's, and so is every file.

    (kagi's searches still failed here, with "failed to lock ... Access is
    denied". That one is kagi-cli's own on Windows, not anything about where
    it runs: it opens its history append-only and then asks for a lock, which
    Windows refuses on an append-only handle. Its other tools are unaffected.)
    """
    from pathlib import Path

    from django.conf import settings

    safe = re.sub(r"[^a-z0-9_-]", "_", str(name or "service").lower())
    home = Path(settings.GAME_DIR) / "server" / "services" / safe
    home.mkdir(parents=True, exist_ok=True)
    return home


def command_params(record):
    """What the SDK starts for a command service: its own home, then its env."""
    from mcp.client.stdio import StdioServerParameters

    home = home_of(record.get("name"))
    env = {"HOME": str(home)}
    # The owner's own variables win, `HOME` included: a service they know
    # wants its real profile is theirs to point there.
    env.update({str(k): str(v) for k, v in (record.get("env") or {}).items()})
    return StdioServerParameters(
        command=record.get("command") or "",
        args=list(record.get("args") or []),
        env=env, cwd=str(home))


#: What decides how a service is reached. A connection is made again when one
#: of these changes, and never because the tool table, the status or the
#: record of recent calls did -- those change on every listing and every
#: acts-outward call, and restarting a command each time left its process,
#: or the one it launched, holding files the next one needed.
CONNECTION_FIELDS = ("kind", "command", "args", "env", "url", "spec",
                     "headers", "auth", "key_place", "key_name", "key",
                     "timeout")


def connection_of(record):
    return {field: record.get(field) for field in CONNECTION_FIELDS}


def target(record):
    """
    What the SDK's `Client` connects to for this service, and any methods.

    (target, {tool: method}). The methods are an OpenAPI service's, so a
    guess can be made from them; an MCP server's tools carry annotations
    instead. Blocking: an OpenAPI spec may have to be fetched. The seam a
    test replaces to serve an in-process server.
    """
    kind = record.get("kind")
    if kind == COMMAND:
        from mcp.client.stdio import stdio_client

        params = command_params(record)
        # Never the SDK's default, which is `sys.stderr` -- and in the Server
        # that is Twisted's LoggingFile, whose fileno() is -1, so every command
        # failed to start with "[Errno 9] Bad file descriptor". Found by the
        # first real service added on a live server; see `stderr_log`.
        return stdio_client(params, errlog=stderr_log(record.get("name"))), {}
    if kind == URL:
        from mcp.client.streamable_http import streamable_http_client

        return streamable_http_client(
            record.get("url"), http_client=_http_client(record)), {}
    if kind == OPENAPI:
        from fastmcp import FastMCP

        spec = _load_spec(record)
        if record.get("auth") == KEY_AUTH and not record.get("key_name"):
            place, named = spec_key(spec)
            if place:
                record = dict(record, key_place=place, key_name=named)
        servers = spec.get("servers") or [{}]
        base = str((servers[0] or {}).get("url") or "").strip() or None
        server = FastMCP.from_openapi(
            spec, client=_http_client(record, base_url=base),
            name=record.get("name") or "openapi")
        return server._mcp_server, spec_methods(spec)
    raise ValueError(f"no such kind of service: {kind}")


#: Where each command's stderr goes, opened once per name per process.
_STDERR = {}
_STDERR_LOCK = threading.Lock()


def stderr_path(name):
    """`server/logs/services/<name>.log`: what a command says about itself."""
    from pathlib import Path

    from django.conf import settings

    safe = re.sub(r"[^a-z0-9_-]", "_", str(name or "service").lower())
    return Path(settings.GAME_DIR) / "server" / "logs" / "services" / f"{safe}.log"


def stderr_log(name):
    """
    A real file for a command's stderr: the one thing a child process must be
    handed that has a file descriptor behind it.

    And worth having for its own sake: a server that will not start almost
    always says why on stderr -- a key not set, a package missing -- and this
    is where the owner can read it. `connect_and_list` quotes the last line.
    """
    with _STDERR_LOCK:
        held = _STDERR.get(name)
        if held is None or held.closed:
            path = stderr_path(name)
            path.parent.mkdir(parents=True, exist_ok=True)
            held = open(path, "a", encoding="utf-8", buffering=1)
            _STDERR[name] = held
        return held


def stderr_size(name):
    """How much a command's stderr log holds now, to read only what follows."""
    try:
        return stderr_path(name).stat().st_size
    except OSError:
        return 0


def stderr_said(name, since=0, most=200):
    """
    The last thing a command wrote to stderr since `since`, or ''.

    Only since: the log is kept across attempts, and quoting a line an earlier
    failure left would be telling the owner the wrong reason.
    """
    try:
        with open(stderr_path(name), "rb") as log:
            log.seek(since)
            text = log.read().decode("utf-8", errors="replace")
    except OSError:
        return ""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return lines[-1][:most] if lines else ""


class _Connection:
    """
    One service's session, owned by one task for its whole life.

    The SDK's client uses task groups, which must be entered and left by the
    same task, so a call is never made on the client directly: it is put on a
    queue the owning task serves. Found in the phase 0 spike; written down so
    nobody has to find it again.
    """

    def __init__(self, loop, record):
        self.loop = loop
        self.record = dict(record)
        self.queue = None
        self.task = None
        self.ready = None
        self.methods = {}

    async def _serve(self):
        from mcp.client import Client

        self.queue = asyncio.Queue()
        try:
            where, self.methods = await asyncio.to_thread(target, self.record)
            async with Client(where, client_info=_client_info(),
                              read_timeout_seconds=float(
                                  self.record.get("timeout") or TIMEOUT)) as client:
                if not self.ready.done():
                    self.ready.set_result(True)
                while True:
                    job, done = await self.queue.get()
                    if job is None:
                        break
                    try:
                        done.set_result(await job(client))
                    except BaseException as exc:          # handed back, not lost
                        if not done.done():
                            done.set_exception(exc)
        except BaseException as exc:
            if not self.ready.done():
                self.ready.set_exception(exc)
            # Whatever was waiting is told, rather than left hanging until its
            # own timeout says something less useful.
            while self.queue is not None and not self.queue.empty():
                _job, done = self.queue.get_nowait()
                if done is not None and not done.done():
                    done.set_exception(exc)
            # Not raised again: everybody who was waiting has been handed it,
            # and a task that ends in an exception nobody retrieves is only a
            # line in the log saying so.
            return

    async def start(self):
        self.ready = self.loop.create_future()
        self.task = asyncio.ensure_future(self._serve())
        await self.ready

    async def do(self, job):
        if self.task is None or self.task.done():
            raise ConnectionError("the session has closed")
        done = self.loop.create_future()
        await self.queue.put((job, done))
        return await done

    async def close(self):
        if self.queue is not None and self.task is not None and not self.task.done():
            await self.queue.put((None, None))
            try:
                await asyncio.wait_for(self.task, 5)
            except BaseException:
                self.task.cancel()


class _Manager:
    """The loop thread, and the connections it holds, by service name."""

    def __init__(self):
        self.loop = None
        self.thread = None
        self.connections = {}
        self.lock = threading.Lock()

    def _ensure_loop(self):
        with self.lock:
            if self.loop is None or not self.thread.is_alive():
                self.loop = asyncio.new_event_loop()
                self.thread = threading.Thread(
                    target=self.loop.run_forever, name="aimud-services",
                    daemon=True)
                self.thread.start()
                self.connections = {}
        return self.loop

    def run(self, coroutine, timeout):
        """Run a coroutine on the loop and wait for it. Blocking."""
        loop = self._ensure_loop()
        future = asyncio.run_coroutine_threadsafe(coroutine, loop)
        try:
            return future.result(timeout)
        except BaseException:
            future.cancel()
            raise

    async def _connection(self, record):
        name = record["name"]
        held = self.connections.get(name)
        if held is not None and connection_of(held.record) != connection_of(record):
            # Edited since it connected: the old session has the old command,
            # address or key. Close it rather than keep talking to it.
            await held.close()
            held = None
        if held is None or held.task is None or held.task.done():
            held = _Connection(self.loop, record)
            self.connections[name] = held
            try:
                await held.start()
            except BaseException:
                self.connections.pop(name, None)
                raise
        return held

    async def _do(self, record, job):
        held = await self._connection(record)
        try:
            return await held.do(job)
        except ConnectionError:
            # Closed under us -- a command that exited, a server restarted.
            # Once more, from a fresh session, and then it is a failure.
            self.connections.pop(record["name"], None)
            held = await self._connection(record)
            return await held.do(job)

    def do(self, record, job, timeout=None):
        """Run `job(client)` against this service's session. Blocking."""
        timeout = float(timeout or record.get("timeout") or TIMEOUT)
        # Connecting may start a process, and the call then has its own time.
        return self.run(self._do(dict(record), job), timeout * 2 + 5)

    def methods(self, name):
        held = self.connections.get(name)
        return dict(held.methods) if held is not None else {}

    def drop(self, name):
        held = self.connections.pop(name, None)
        if held is not None and self.loop is not None:
            asyncio.run_coroutine_threadsafe(held.close(), self.loop)


_MANAGER = None


def _manager():
    global _MANAGER
    if _MANAGER is None:
        _MANAGER = _Manager()
    return _MANAGER


# ---------------------------------------------------------------------------
# Listing and calling: blocking work, for `llm.fetch`
# ---------------------------------------------------------------------------

def _dump(model):
    """A pydantic model from the SDK as plain JSON-able data."""
    if model is None:
        return None
    if hasattr(model, "model_dump"):
        return model.model_dump(by_alias=True, exclude_none=True, mode="json")
    return model


def list_tools(record, timeout=None):
    """
    What a service offers, as {tool: info}. Blocking.

    Each info holds the description, both schemas, the annotations, the guessed
    level, the fingerprint, and -- when its input is something no rule can
    fill -- why it is refused.
    """
    async def job(client):
        found, cursor = [], None
        while True:
            page = await client.list_tools(cursor=cursor)
            found.extend(page.tools)
            cursor = getattr(page, "next_cursor", None)
            if not cursor:
                return found

    tools = _manager().do(record, job, timeout=timeout)
    methods = _manager().methods(record["name"])
    listed = {}
    for tool in tools:
        input_schema = _dump(getattr(tool, "input_schema", None)) or {}
        output_schema = _dump(getattr(tool, "output_schema", None))
        annotations = _dump(getattr(tool, "annotations", None)) or {}
        method = methods.get(tool.name)
        listed[tool.name] = {
            "description": str(getattr(tool, "description", "") or ""),
            "input": input_schema,
            "output": output_schema,
            "annotations": annotations,
            "method": method,
            "level": guess_level(annotations,
                                 method if record.get("kind") == OPENAPI else None),
            "fingerprint": fingerprint(input_schema, output_schema),
            "refused": input_complaint(input_schema),
        }
    return listed


def call(record, tool, arguments, retry=False):
    """
    Call one tool. Blocking, and never raises: failure is an `Answer` too.

    `retry` is whether a call that never got an answer may be sent again,
    which is only ever true for a tool the service marks idempotent -- sending
    an email twice because the first reply was lost is the one thing worse
    than not sending it. §7.5.
    """
    async def job(client):
        return await client.call_tool(tool, dict(arguments or {}))

    attempts = 2 if retry else 1
    last = ""
    for _attempt in range(attempts):
        try:
            result = _manager().do(record, job)
        except Exception as exc:                      # never reached
            last = _reason(exc)
            logger.log_info(f"services: {record.get('name')}.{tool} "
                            f"could not be reached: {last}")
            continue
        text = "\n".join(
            str(getattr(block, "text", "") or "")
            for block in (getattr(result, "content", None) or [])
            if getattr(block, "type", "") == "text").strip()
        structured = getattr(result, "structured_content", None)
        if getattr(result, "is_error", False):
            return Answer(structured, text, error=text or "the tool said it failed")
        return Answer(structured, text,
                      files=files_in(getattr(result, "content", None) or []))
    return Answer(error=last or "no answer", reached=False)


def files_in(blocks):
    """
    The files among a tool's content blocks, as `(bytes, mime type)`.

    MCP sends an image or a sound as base64 in an `image` or `audio` block,
    and a file of any other kind as an embedded resource with a `blob`. Text
    is not a file. A block whose data will not decode is skipped rather than
    trusted: what is kept is only ever what `assets.add` then checks again.
    """
    import base64
    import binascii

    found = []
    for block in blocks:
        kind = getattr(block, "type", "")
        if kind in ("image", "audio"):
            data, mime = getattr(block, "data", ""), getattr(block, "mimeType", "")
        elif kind == "resource":
            resource = getattr(block, "resource", None)
            data = getattr(resource, "blob", "") if resource is not None else ""
            mime = getattr(resource, "mimeType", "") if resource is not None else ""
        else:
            continue
        if not data:
            continue
        try:
            found.append((base64.b64decode(data, validate=True), str(mime or "")))
        except (binascii.Error, ValueError):
            logger.log_info(f"services: a {kind} block was not base64, and "
                            f"was not kept")
    return found


def _reason(exc):
    """One line about why a service could not be reached."""
    if isinstance(exc, TimeoutError) or type(exc).__name__ == "TimeoutError":
        return "it took too long to answer"
    inner = getattr(exc, "exceptions", None)
    if inner:
        return _reason(inner[0])
    said = str(exc).strip() or type(exc).__name__
    return said.splitlines()[0][:200]


def connect_and_list(record, timeout=None):
    """
    (tools, status) for a service: a fresh listing, or why there is none.

    Blocking, and never raises, because a service down this afternoon is not
    a wrong setting -- it is saved anyway, and says why. §4.2.
    """
    _manager().drop(record["name"])
    before = stderr_size(record.get("name")) if record.get("kind") == COMMAND else 0
    try:
        return list_tools(record, timeout=timeout), ""
    except Exception as exc:
        reason = _reason(exc)
        if record.get("kind") == COMMAND:
            said = stderr_said(record.get("name"), since=before)
            if said:
                reason += f" -- it said: {said}"
        logger.log_info(f"services: {record.get('name')} could not be listed: {reason}")
        return None, reason


def refresh(name, on_done=None):
    """
    Connect to a service, list its tools, and write the table back.

    Off the reactor through `llm.fetch`; the register is written on the way
    back, on the reactor. `on_done(record)` is told how it went.
    """
    from world import llm

    record = get(name)
    if record is None:
        if on_done:
            on_done(None)
        return

    def written(result):
        tools, status = result
        fresh = get(name)
        if fresh is None:
            return None
        if tools is not None:
            fresh["tools"] = merge_tools(fresh.get("tools"), tools,
                                         openapi=fresh.get("kind") == OPENAPI)
        fresh["status"] = status
        put(fresh)
        if on_done:
            on_done(fresh)
        return None

    def failed(failure):
        logger.log_info(f"services: refreshing {name} failed: {failure}")
        if on_done:
            on_done(get(name))

    llm.fetch(connect_and_list, record, on_success=written, on_error=failed)


# ---------------------------------------------------------------------------
# The record of what reached outside
# ---------------------------------------------------------------------------

def note_outward(service, tool, actor, world_root, sponsor, arguments, answer):
    """
    Record one acts-outward call, for the owner to trace later. §7.5.

    Who acted, in which world, under which sponsor, which tool, with what.
    Bounded, beside the service, because when something happens in the real
    world the owner needs to find what in the game did it.
    """
    import time

    record = get(service)
    if record is None:
        return
    payer = getattr(sponsor, "account", None)
    entry = {
        "when": time.time(),
        "tool": tool,
        "actor": getattr(actor, "key", "") or "",
        "is_character": is_character(actor),
        "world": getattr(world_root, "key", "") or "",
        "world_id": getattr(world_root, "id", None),
        "payer": getattr(payer, "key", "") or "",
        "arguments": dict(arguments or {}),
        "ok": bool(answer.ok),
        "error": answer.error,
    }
    record["recent"] = (list(record.get("recent") or []) + [entry])[-RECENT:]
    put(record)


# ---------------------------------------------------------------------------
# Small readers for forms
# ---------------------------------------------------------------------------

def read_args(text):
    """A command's arguments as typed, split the way a shell would."""
    try:
        return shlex.split(str(text or ""), posix=True), ""
    except ValueError as exc:
        return None, f"Those arguments do not split cleanly: {exc}."


def read_pairs(text):
    """
    `NAME=value` pairs, one per line or separated by semicolons.

    For environment variables and headers. Values may hold `=`; names may not.
    """
    pairs = {}
    for chunk in re.split(r"[;\n]", str(text or "")):
        chunk = chunk.strip()
        if not chunk:
            continue
        name, eq, value = chunk.partition("=")
        if not eq or not name.strip():
            return None, f"{chunk!r} is not NAME=value."
        pairs[name.strip()] = value.strip()
    return pairs, ""


def said_pairs(pairs):
    """Names only: the values may be secrets."""
    names = sorted((pairs or {}).keys())
    return ", ".join(names) if names else "none"
