"""
Who an agent is, and what it is allowed to be.

Phase 2 of docs/archived/mcp.md. An agent reaches the game over MCP and has to say who
it is before anything else happens. What it says is a token, minted here and
kept on the account it belongs to.

**A token is the account.** It is not a scoped credential and this module does
not pretend otherwise: an agent holding one can do everything the account can,
including spending its API key. §4.2 of the plan says so, the help text on
`settings agenttoken` says so, and the reason the plan recommends giving an
agent an account of its own is that an account can be given fewer permissions
and a token cannot.

The token is generated rather than typed, because a token somebody chooses is
a password again. It is compared in constant time, because a token compared
with `==` leaks its own prefix to anybody willing to ask often enough.

Nothing here opens a socket or knows what MCP is. `server/conf/mcp_protocol.py`
is the transport and runs in the Portal; this runs in the Server, where the
database is.
"""

import hmac
import secrets

from evennia.utils import logger

#: Where a token is kept on the account. Named in `exchange.LEFT`: it is a
#: secret and an account's own, and a world document holds neither.
TOKEN_ATTR = "agent_token"

#: How many bytes of randomness a token carries before encoding. 32 bytes is
#: 256 bits, which is the same bar the rest of the world uses for a bearer
#: credential that never expires.
TOKEN_BYTES = 32

#: What a token is prefixed with, so one found in a config file, a log or a
#: pasted traceback is recognisable as this game's and can be revoked rather
#: than puzzled over.
TOKEN_PREFIX = "aimud_agent_"


def mint(account):
    """
    A new token for this account, replacing whatever it had.

    Returns the token in the clear. This is the only moment it is ever
    readable: everything afterwards shows it masked, because a secret that can
    be read back is a secret sitting in the scrollback of whoever last looked.
    """
    token = TOKEN_PREFIX + secrets.token_urlsafe(TOKEN_BYTES)
    account.attributes.add(TOKEN_ATTR, token)
    logger.log_info(f"agent token minted for {account}")
    return token


def clear(account):
    """Take away this account's token. Any agent using it is on its own."""
    account.attributes.remove(TOKEN_ATTR)
    logger.log_info(f"agent token cleared for {account}")


def token_of(account):
    """The account's token, or None. For masking, never for comparing."""
    return account.attributes.get(TOKEN_ATTR)


def account_for(token):
    """
    Whose token this is, or None.

    Every account holding a token is compared against, and every comparison is
    `hmac.compare_digest`, so the work done is the same whether the first
    character matches or the last. The loop is over accounts that have a token
    at all, which on a mud of this size is a handful and on a mud of any size
    is still far fewer than the accounts.
    """
    if not token or not isinstance(token, str):
        return None
    for account in _accounts_with_tokens():
        held = account.attributes.get(TOKEN_ATTR)
        if isinstance(held, str) and hmac.compare_digest(held, token):
            return account
    return None


def _accounts_with_tokens():
    """Every account holding a token, asked of the database once."""
    from evennia.accounts.models import AccountDB

    return AccountDB.objects.filter(
        db_attributes__db_key=TOKEN_ATTR).distinct()


# ---------------------------------------------------------------------------
# Connecting
# ---------------------------------------------------------------------------

def warn_displaced(session, account):
    """
    Tell whoever is already playing as this account that they are about to be
    dropped, and by what.

    Displacement is Evennia's, not ours: one character per account means
    `sessionhandler.login` disconnects the sessions that were here first, the
    same as logging in from a second terminal. What this game adds is the
    reason, because somebody thrown out of a half-answered menu by their own
    tooling should not have to guess. §4.3.
    """
    for other in account.sessions.all():
        if other is session or not other.logged_in:
            continue
        other.msg("|yAn agent connected with your token. It takes the "
                  "character from here; you are being disconnected.|n")


def greeting(account):
    """
    What an agent is told once it is in. MCP shows this as instructions.

    Short, and its real job is to name the manual: there is far more worth
    knowing than belongs in a handshake, and `world/manual.py` is where it is
    kept -- including the half of it generated from the game's own registers,
    which no fixed greeting could stay level with.
    """
    from world import manual

    return (
        f"Connected to aimud as {account.key}. You are playing a text mud, "
        "typing at it with the `send` tool exactly as a person would. "
        "Everything this game can do is reachable by typing, menus included: "
        "`help` lists commands, `look` describes where you are, and a menu "
        "tells you what to type next. Use `poll` to hear what happens while "
        f"you are not typing. Call `manual` (page '{manual.FIRST}') first: it "
        "explains what there is to do here, how to build a world, and how to "
        "use this connection to drive a test.")


# ---------------------------------------------------------------------------
# Tools the Server owns
# ---------------------------------------------------------------------------

#: Tools that exist and are deliberately not offered to an agent, with the
#: reason. Not a denylist to be filled in quietly: each line is an answer, and
#: the guard test in `tests/test_agents.py` fails until a new tool is either
#: offered or named here. §10 of docs/archived/mcp.md.
NOT_OFFERED = {
    "commonsense": "threaded: it reaches the second lexicon over the network, "
                   "and a tool run from the Server's reactor thread would "
                   "stop the whole mud while it waited. Wants the deferred "
                   "shape `llm.fetch` uses before it can be offered",
    "list_tools": "a service's tools reach a world through a rule, and these "
                  "are offered to the loop that writes rules and nowhere "
                  "else; an agent reads the same through `view services` and "
                  "uses a tool by typing the verb. docs/archived/mcp-client.md 6",
    "show_tool": "the same as list_tools: written for the rule loop, and "
                 "`view service <name>` says it in full to anybody",
}

#: The most one tool answer may say, and what is added when it is cut.
#: `toolbox.MOST_RESULT`'s number, for its reason: every list tool takes a
#: query, a limit and an offset, so a model can always ask again for less.
MOST_RESULT = 4000
CUT_SHORT = "\n[... cut short: ask again for less, or for the rest]"

#: Tools whose answer is never cut, and why. A world document is one
#: indivisible thing, not a list: four thousand characters of it is not a
#: shorter document, it is broken JSON, and `export_world` is the tool this
#: whole surface exists for. The ceiling is still `exchange.MOST_BYTES`,
#: because that is the most a world may be at all.
WHOLE = frozenset({"export_world"})


def _context(session):
    """The `toolbox.ToolContext` a tool run for this agent gets."""
    from world import sponsor as sponsor_mod, toolbox as tb

    character = getattr(session, "puppet", None)
    room = getattr(character, "location", None) if character else None
    world_root = room.db.world_root if room is not None else None
    account = getattr(session, "account", None)
    # Inside a world, its creator pays, as for anybody standing there; an
    # agent is a player. Outside every world there is nobody else to ask.
    # docs/archived/shared-worlds.md 5.3.
    if world_root is not None:
        sponsor = sponsor_mod.of_world(world_root, actor=character)
    elif account is not None:
        sponsor = sponsor_mod.of_account(account, actor=character)
    else:
        sponsor = None
    return tb.ToolContext(
        world_root=world_root, room=room, actor=character,
        sponsor=sponsor, job="agent")


def offered_tools(ctx):
    """
    `{name: Tool}` for every tool an agent may call, beyond `send` and `poll`.

    Read off `world/toolkit.py`, the register of every tool in the game, so
    there is one list and not a second one kept level by hand. Three things
    take a tool off it, and each is a rule rather than a name:

    * **It cannot be called at all.** A tool with no handler is a declaration
      (`Tool.runnable`): a generator's finish tool, made per call and
      meaningless without the conversation it answers, or one of `NPC_TOOLS`,
      which is what a character is offered and gets its handler bound for one
      turn. Neither is a thing an agent could run if it tried.
    * **It does not act.** Only lookups are offered, plus this module's own
      document tools. An agent that wanted to move or speak types it with
      `send`, where the parser, the rules and the room all get their say --
      which is the whole argument of docs/archived/mcp.md §5.1.
    * **`NOT_OFFERED` names it**, with the reason, for a tool that is runnable
      and a lookup and still cannot be offered as it stands.

    So a lookup added tomorrow beside the register it reads reaches an agent
    without anybody wiring it up, and anything else added tomorrow does not
    reach one by accident. `tests/test_agents.py` holds both halves.
    """
    from world import toolbox as tb, toolkit

    ours = {tool.name for tool in document_tools()}
    found = {}
    for name, tool in toolkit.every_tool().items():
        if not tool.runnable or name in NOT_OFFERED or tool.threaded:
            continue
        if tool.kind != tb.LOOKUP and name not in ours:
            continue
        if not tool.offered(ctx):
            continue
        found[name] = tool
    return found


def tool_schemas(session):
    """Every offered tool, in the shape MCP describes a tool."""
    ctx = _context(session)
    schemas = []
    for name, tool in sorted(offered_tools(ctx).items()):
        function = tool.schema(ctx)["function"]
        schemas.append({
            "name": function["name"],
            "description": function.get("description") or "",
            "inputSchema": function.get("parameters")
            or {"type": "object", "properties": {}},
        })
    return schemas


def run_tool(session, name, args):
    """
    Run one tool and answer `(what to say, whether it went wrong)`.

    Never raises past its caller: the Portal is holding an HTTP request open,
    and a traceback that reaches nobody is a timeout with no reason attached.
    `inputfuncs.mcp_tool` is the net under this one.
    """
    from world import toolbox as tb

    ctx = _context(session)
    tool = offered_tools(ctx).get(name)
    if tool is None:
        if name in NOT_OFFERED:
            return f"{name} is not offered here: {NOT_OFFERED[name]}.", True
        return f"No tool called {name!r}.", True

    parameters = tool.parameters
    if callable(parameters):
        parameters = parameters(ctx)
    wrong = tb.problems_with(args, parameters)
    if wrong:
        return "; ".join(wrong), True

    said = []
    tool.handler(ctx, args, said.append)
    if not said:
        # Every tool offered here answers before it returns. One that does not
        # has grown a callback, and saying so is better than an empty result
        # that reads like a world with nothing in it.
        return (f"{name} did not answer. It has probably grown an "
                f"asynchronous step, which this surface cannot carry yet."
                ), True
    answer = said[0]
    if isinstance(answer, tb.Complaint):
        return _shortened(name, str(answer)), True
    if isinstance(answer, tb.Accepted):
        return _shortened(name, str(answer.said)), False
    return _shortened(name, str(answer)), False


def _shortened(name, said):
    """One answer, cut if it is long and cutting it would not ruin it."""
    if name in WHOLE or len(said) <= MOST_RESULT:
        return said
    return said[:MOST_RESULT] + CUT_SHORT


# ---------------------------------------------------------------------------
# The world as a document
# ---------------------------------------------------------------------------

def tools():
    """
    What this module defines for the register: the two document tools.

    `world/toolkit.py` calls this. Runnable rather than declared, unlike a
    generator's finish tools: these need no live conversation around them, and
    an agent calls them directly.
    """
    return document_tools()


def document_tools():
    """
    Reading a world out and building one from a document.

    These are the reason this surface is worth having (§6 of docs/archived/mcp.md). A
    test fixture is one `import_world` rather than four hundred menu answers,
    and what comes back out of `export_world` is the assertion.

    Neither writes to the shared folder and neither touches the restore point:
    a document that went nowhere is not an export, and an agent reading a
    world out should not quietly change where `reset world` goes back to. A
    player's `export world` still does both.
    """
    from world import toolbox as tb

    return [
        tb.Tool(
            "export_world",
            "Read a whole world out as one JSON document: its rooms, ways, "
            "things, people, errands, rules and vocabulary, as the world "
            "stands right now. Nothing in it is a database reference, so it "
            "can be read, edited and built again. Costs nothing.",
            {
                "type": "object",
                "properties": {
                    "world": {
                        "type": "string",
                        "description": "Which world, by its number in `view "
                                       "worlds` or by its title. Leave it out "
                                       "for the world you are standing in.",
                    },
                },
            },
            _export_handler, looks=True),
        tb.Tool(
            "import_world",
            "Build a world from a JSON document, the shape `export_world` "
            "answers with. Validated whole and refused entire with every "
            "reason if anything is wrong, so nothing is ever half built. "
            "Costs nothing, and needs no API key.",
            {
                "type": "object",
                "properties": {
                    "document": {
                        "type": "string",
                        "description": "The world document, as JSON text.",
                    },
                },
                "required": ["document"],
            },
            _import_handler),
    ]


def _export_handler(ctx, args, answer):
    import json

    from world import exchange, lore, toolbox as tb

    root, complaint = _world_for(ctx, str(args.get("world") or "").strip())
    if root is None:
        answer(tb.complain(complaint))
        return
    doc = exchange.document(root)
    wrong = exchange.problems(doc)
    if wrong:
        # The same refusal a player gets, for the same reason: a document this
        # server cannot read back is not an export.
        answer(tb.complain(
            f"{lore.title(root)} could not be written down: {wrong[0]}"))
        return
    answer(json.dumps(doc, ensure_ascii=False, indent=1, sort_keys=True))


def _import_handler(ctx, args, answer):
    import json

    from world import exchange, lore, toolbox as tb

    said = args.get("document")
    if not isinstance(said, str) or not said.strip():
        answer(tb.complain("A world document, as JSON text, is required."))
        return
    size = len(said.encode("utf-8"))
    if size > exchange.MOST_BYTES:
        # Checked here because `exchange.read` checks the file's size and this
        # document never was a file.
        answer(tb.complain(
            f"that document is {size // 1024} KiB, and "
            f"{exchange.MOST_BYTES // 1024} KiB is the most a world may be"))
        return
    try:
        doc = json.loads(said)
    except ValueError as exc:
        answer(tb.complain(f"that is not a document this can read: {exc}"))
        return
    account = _account_of(ctx)
    if account is None:
        answer(tb.complain("Only an account can hold a world."))
        return
    try:
        root = exchange.build(doc, account, ctx.actor)
    except exchange.Refused as refusal:
        answer(tb.complain(
            "\n".join(str(said) for said in refusal.complaints[:10])))
        return
    from commands.world_subject import resolve_worlds

    number = len(resolve_worlds(account))
    answer(f"{lore.title(root)} is yours, "
           f"{len(exchange.rooms_of(root))} room(s). "
           f"`enter world {number}` goes there. Its text reaches your model "
           f"on your key when you play it.")


def _account_of(ctx):
    """
    The agent's own account: whose worlds it can name, and who owns one it
    imports. Not the sponsor's -- in a world that is whoever made it, which
    is who pays and nothing else (docs/archived/shared-worlds.md 5.3).
    """
    return getattr(ctx.actor, "account", None)


def _world_for(ctx, said):
    """The world a tool was asked about, or (None, why not)."""
    from commands.world_subject import resolve_worlds
    from world import exchange, lore

    account = _account_of(ctx)
    if not said:
        if ctx.world_root is not None:
            return ctx.world_root, ""
        return None, ("You are not standing in a world. Name one by its "
                      "number or title, or `enter world 1` first.")
    if account is None:
        return None, "Only an account can hold a world."
    worlds = resolve_worlds(account)
    if said.isdigit():
        wanted = int(said)
        if 1 <= wanted <= len(worlds):
            return worlds[wanted - 1][0], ""
        return None, f"There is no world {wanted}; you have {len(worlds)}."
    wanted = exchange.slug(said)
    for root, _count in worlds:
        if exchange.slug(lore.title(root)) == wanted:
            return root, ""
    return None, (f"No world of yours is called {said!r}. `view worlds` lists "
                  f"them.")
