"""
An agent playing here: its token, the tools it is offered, and the guards.

Four kinds of test, and the third kind is the one that matters over time.

**The credential.** `TokensAreMinted` and `WhoIsAsking`: generated rather than
typed, compared without leaking its own prefix, refused in every way it can be
wrong, and the person it displaces told why.

**What an agent can do.** `ToolsAreOffered`, `DocumentsTravel` and
`WhatAnAgentIsAndIsNotOffered`. The round trip is the same round trip
`test_exchange` makes -- exported, imported, exported -- driven through the
tool an agent calls rather than the command a player types. The third of those
asserts the three rules in `agents.offered_tools` against the whole register
rather than a handful of names, so it keeps answering as tools are added.

**The guards, which is why most of this file exists.**
`TheRegisterHoldsEveryTool` reads every `tb.Tool("...")` in `world/` and fails
when one is built and not registered, registered and never built, declared with
nothing to stand in for, named by something no static pass can read, or claimed
by two modules at once. `TheRegistersModuleListsDoNotDrift` keeps one list of
modules rather than two. `TheCharacterToolsAreNotMutatedByBeingOffered` guards
the sharp edge of the conversion: `NPC_TOOLS` is module-level and shared by
every character in the game, so a shallow copy would close one character's
`get` to what was lying in one room and leave it that way for everybody.

Each of those was verified by planting the fault and watching it go red. The
arrangement is `exchange.CARRIED` and `exchange.LEFT`'s, for its reason:
without it the surface is right on the day it is written and quietly wrong
afterwards. See docs/mcp.md §10.

**The manual.** `TheManual` and `TheManualIsReachable`. Half of it is generated
from the game's own registers, and the tests assert exactly that -- every
offered tool on the tools page, every verb and maker on the commands page,
every effect on the effects page -- so a page cannot fall behind what it
describes.

Nothing here opens a socket. The Portal half is HTTP and Twisted and is proved
by running it; what these hold level is the half that lives in the game.
"""

import ast
import json
import pathlib

from tests.base import GameTest, NoWorldTest

# The hand-built world and its furnishing, borrowed rather than written again:
# a second world fixture would be a second thing to keep level, and this one
# already populates every section a document has.
from tests.test_exchange import WorldTest

#: The game directory, for the AST pass that walks every module for tools.
GAME_DIR = pathlib.Path(__file__).resolve().parent.parent


class Session:
    """
    A session with no socket behind it.

    Everything in `world/agents.py` wants a session for two things only: who
    the account is, and what it is puppeting. A real one needs a Portal, an
    AMP link and a reactor, none of which has an opinion about any of this.
    """

    def __init__(self, account=None, puppet=None, logged_in=False):
        self.account = account
        self.puppet = puppet
        self.logged_in = logged_in
        self.said = {}
        self.sessionhandler = self

    # -- what the game says to it ----------------------------------------
    def msg(self, **kwargs):
        for name, (args, _kwargs) in kwargs.items():
            self.said.setdefault(name, []).append(args)

    # -- standing in for the session handler ------------------------------
    def login(self, session, account):
        session.logged_in = True
        session.account = account

    def verdict(self, name="mcp_auth"):
        said = self.said.get(name) or []
        return said[0] if said else None


class TokensAreMinted(GameTest):
    accounts = True

    def test_a_token_is_generated_and_kept(self):
        from world import agents

        token = agents.mint(self.account)
        self.assertTrue(token.startswith(agents.TOKEN_PREFIX))
        self.assertEqual(agents.token_of(self.account), token)

    def test_minting_again_replaces(self):
        from world import agents

        first = agents.mint(self.account)
        second = agents.mint(self.account)
        self.assertNotEqual(first, second)
        self.assertEqual(agents.token_of(self.account), second)
        self.assertIsNone(agents.account_for(first))

    def test_clearing_takes_it_away(self):
        from world import agents

        token = agents.mint(self.account)
        agents.clear(self.account)
        self.assertIsNone(agents.token_of(self.account))
        self.assertIsNone(agents.account_for(token))

    def test_a_token_is_long_enough_to_be_one(self):
        from world import agents

        token = agents.mint(self.account)
        self.assertGreater(len(token) - len(agents.TOKEN_PREFIX), 32)

    def test_the_settings_field_mints_and_clears(self):
        from world import agents, preferences

        class Ctx:
            pass

        ctx = Ctx()
        ctx.account = self.account
        value, complaint = preferences._agent_parse(ctx, "new")
        self.assertEqual(complaint, "")
        self.assertIs(value, preferences.NEW_TOKEN)
        said = preferences._agent_set(ctx, value)
        token = agents.token_of(self.account)
        self.assertIn(token, said)

        value, complaint = preferences._agent_parse(ctx, "clear")
        self.assertEqual(complaint, "")
        self.assertIsNone(value)
        preferences._agent_set(ctx, None)
        self.assertIsNone(agents.token_of(self.account))

    def test_a_token_cannot_be_chosen(self):
        from world import preferences

        class Ctx:
            pass

        value, complaint = preferences._agent_parse(Ctx(), "hunter2")
        self.assertIsNone(value)
        self.assertIn("generated rather than chosen", complaint)

    def test_replacing_asks_first(self):
        from world import agents, preferences

        class Ctx:
            pass

        ctx = Ctx()
        ctx.account = self.account
        self.assertIsNone(preferences._agent_confirm(ctx, preferences.NEW_TOKEN))
        agents.mint(self.account)
        key, question = preferences._agent_confirm(ctx, preferences.NEW_TOKEN)
        self.assertEqual(key, "clear_agenttoken")
        self.assertIn("replaces", question)

    def test_the_confirmation_is_registered(self):
        from world import preferences

        keys = {key for key, _label, _why in preferences.CONFIRMATIONS}
        self.assertIn("clear_agenttoken", keys)

    def test_the_token_is_masked_when_shown(self):
        from world import agents, preferences

        token = agents.mint(self.account)
        shown = preferences.AGENT_TOKEN.show(None, token)
        self.assertNotEqual(shown, token)
        self.assertIn("*", shown)
        self.assertNotIn(token[8:-8], shown)

    def test_the_token_is_never_offered_to_a_model(self):
        from world import menus, preferences

        self.assertEqual(preferences.AGENT_TOKEN.kind, menus.SECRET)
        self.assertFalse(preferences.AGENT_TOKEN.suggestible)


class WhoIsAsking(GameTest):
    accounts = True

    def test_the_right_token_finds_the_account(self):
        from world import agents

        token = agents.mint(self.account)
        self.assertEqual(agents.account_for(token).id, self.account.id)

    def test_every_way_of_being_wrong_is_refused(self):
        from world import agents

        agents.mint(self.account)
        for wrong in ("", None, 0, [], "nonsense",
                      agents.TOKEN_PREFIX, agents.TOKEN_PREFIX + "x"):
            self.assertIsNone(agents.account_for(wrong), wrong)

    def test_a_near_miss_is_refused(self):
        from world import agents

        token = agents.mint(self.account)
        self.assertIsNone(agents.account_for(token[:-1]))
        self.assertIsNone(agents.account_for(token + "x"))

    def test_an_account_with_no_token_is_never_found(self):
        from world import agents

        self.assertIsNone(agents.account_for("anything at all"))

    def test_logging_in_answers_the_portal(self):
        from server.conf import inputfuncs
        from world import agents

        token = agents.mint(self.account)
        session = Session()
        inputfuncs.mcp_auth(session, token=token)
        ok, said = session.verdict()
        self.assertTrue(ok)
        self.assertIn(self.account.key, said)
        self.assertTrue(session.logged_in)
        # The tool list goes first, or the Portal answers before it arrives.
        self.assertIn("mcp_tools", session.said)

    def test_a_refusal_answers_the_portal_too(self):
        from server.conf import inputfuncs

        session = Session()
        inputfuncs.mcp_auth(session, token="nonsense")
        ok, said = session.verdict()
        self.assertFalse(ok)
        self.assertIn("agenttoken", said)
        self.assertFalse(session.logged_in)

    def test_a_session_already_in_is_refused(self):
        from server.conf import inputfuncs
        from world import agents

        token = agents.mint(self.account)
        session = Session(logged_in=True)
        inputfuncs.mcp_auth(session, token=token)
        ok, _said = session.verdict()
        self.assertFalse(ok)

    def test_whoever_was_playing_is_told_why(self):
        from world import agents

        playing = Session(account=self.account, logged_in=True)
        told = []
        playing.msg = lambda text=None, **kw: told.append(text)

        class Sessions:
            @staticmethod
            def all():
                return [playing]

        original = type(self.account).sessions
        try:
            type(self.account).sessions = Sessions()
            agents.warn_displaced(Session(), self.account)
        finally:
            type(self.account).sessions = original
        self.assertTrue(told)
        self.assertIn("agent", told[0].lower())


class ToolsAreOffered(GameTest):
    accounts = True

    def agent_session(self):
        return Session(account=self.account, puppet=self.char1,
                       logged_in=True)

    def test_every_schema_is_shaped_the_way_mcp_wants(self):
        from world import agents

        schemas = agents.tool_schemas(self.agent_session())
        self.assertTrue(schemas)
        for schema in schemas:
            self.assertIn("name", schema)
            self.assertTrue(schema["description"])
            self.assertEqual(schema["inputSchema"].get("type"), "object")

    def test_the_document_tools_are_there(self):
        from world import agents

        names = {schema["name"]
                 for schema in agents.tool_schemas(self.agent_session())}
        self.assertIn("export_world", names)
        self.assertIn("import_world", names)

    def test_the_lookups_are_there(self):
        from world import agents, lookups

        names = {schema["name"]
                 for schema in agents.tool_schemas(self.agent_session())}
        offered = set(lookups.all_tools()) - set(agents.NOT_OFFERED)
        self.assertTrue(offered & names, "no lookup reached an agent")

    def test_an_unknown_tool_is_refused(self):
        from world import agents

        said, failed = agents.run_tool(self.agent_session(), "gibberish", {})
        self.assertTrue(failed)
        self.assertIn("gibberish", said)

    def test_a_tool_left_out_says_why(self):
        from world import agents

        name = sorted(agents.NOT_OFFERED)[0]
        said, failed = agents.run_tool(self.agent_session(), name, {})
        self.assertTrue(failed)
        self.assertIn("not offered", said)

    def test_arguments_are_checked_before_a_handler_sees_them(self):
        from world import agents

        said, failed = agents.run_tool(self.agent_session(), "import_world", {})
        self.assertTrue(failed)
        self.assertIn("required", said)

    def test_a_long_answer_is_cut_and_says_so(self):
        from world import agents

        self.assertEqual(agents._shortened("list_traits", "x" * 50), "x" * 50)
        cut = agents._shortened("list_traits", "x" * (agents.MOST_RESULT + 500))
        self.assertTrue(cut.endswith(agents.CUT_SHORT))
        self.assertLess(len(cut), agents.MOST_RESULT + len(agents.CUT_SHORT) + 1)

    def test_a_document_is_never_cut(self):
        from world import agents

        long = "x" * (agents.MOST_RESULT + 500)
        self.assertEqual(agents._shortened("export_world", long), long)


class DocumentsTravel(WorldTest):
    """The round trip, driven through the tools rather than the commands."""

    accounts = True

    def agent_session(self):
        return Session(account=self.account, puppet=self.char1,
                       logged_in=True)

    def standing_in(self, root):
        self.char1.move_to(root, quiet=True)
        return self.agent_session()

    def tool(self, session, name, args):
        from world import agents

        return agents.run_tool(session, name, args)

    def test_a_world_reads_out_as_a_document(self):
        root = self.world()
        self.furnish(root)
        said, failed = self.tool(self.standing_in(root), "export_world", {})
        self.assertFalse(failed, said)
        doc = json.loads(said)
        self.assertEqual(doc["kind"], "world")
        self.assertEqual(doc["title"], "The School")

    def test_the_round_trip_is_the_same_document(self):
        root = self.world()
        self.furnish(root)
        session = self.standing_in(root)
        first, failed = self.tool(session, "export_world", {})
        self.assertFalse(failed, first)

        said, failed = self.tool(session, "import_world", {"document": first})
        self.assertFalse(failed, said)
        self.assertIn("is yours", said)

        built = self.account.db.created_worlds[-1]
        from evennia.objects.models import ObjectDB

        again, failed = self.tool(session, "export_world",
            {"world": str(len(self.account.db.created_worlds))})
        self.assertFalse(failed, again)
        self.assertEqual(json.loads(first), json.loads(again))
        self.assertTrue(ObjectDB.objects.filter(id=built).exists())

    def test_a_document_that_is_not_one_is_refused_whole(self):
        session = self.standing_in(self.world())
        said, failed = self.tool(session, "import_world",
                                  {"document": '{"nope": 1}'})
        self.assertTrue(failed)
        self.assertIn("aimud", said)

    def test_text_that_is_not_json_is_refused(self):
        session = self.standing_in(self.world())
        said, failed = self.tool(session, "import_world",
                                  {"document": "this is not json"})
        self.assertTrue(failed)
        self.assertIn("not a document", said)

    def test_a_document_too_big_is_refused_before_it_is_parsed(self):
        from world import exchange

        session = self.standing_in(self.world())
        said, failed = self.tool(session, "import_world",
            {"document": "x" * (exchange.MOST_BYTES + 1)})
        self.assertTrue(failed)
        self.assertIn("most a world may be", said)

    def test_exporting_names_a_world_that_is_not_yours(self):
        session = self.standing_in(self.world())
        said, failed = self.tool(session, "export_world",
                                  {"world": "no such world"})
        self.assertTrue(failed or "No world" in said)
        self.assertIn("world", said.lower())

    def test_nowhere_to_export_from_says_so(self):
        session = self.agent_session()
        self.char1.move_to(self.room1, quiet=True)
        said, _failed = self.tool(session, "export_world", {})
        self.assertIn("not standing in a world", said)

    def test_exporting_does_not_move_the_restore_point(self):
        from world import exchange

        root = self.world()
        before = root.attributes.get(exchange.RESTORE_ATTR)
        self.tool(self.standing_in(root), "export_world", {})
        self.assertEqual(root.attributes.get(exchange.RESTORE_ATTR), before)
class TheRegisterHoldsEveryTool(NoWorldTest):
    """
    `world/toolkit.py` knows every tool in the game, and an AST pass proves it.

    The guard against the way a tool register rots: somebody writes a tool
    beside the thing it reads, and whether it belongs on the register -- and so
    whether an agent should have it -- is a question nobody is asked. The same
    arrangement `exchange.CARRIED` and `exchange.LEFT` have with the attribute
    test, and for the same reason. §10 of docs/mcp.md.

    Two directions, because one alone is half a guard. A tool built and not
    registered is a silence; a tool registered and never built is a name that
    excludes nothing and hides the next tool to share it.
    """

    #: Where a tool can be made. `toolbox` itself only defines what one is.
    WHERE = "world"
    SKIP = ("world/toolbox.py",)

    def _made(self):
        """
        Every `tb.Tool(...)` in `world/`, split by whether it is a declaration.

        The split is what makes the second direction of this guard bite at all.
        A declaration is itself a `tb.Tool("name", ...)` call -- it has to be,
        it is a `Tool` -- so counting those as evidence that something builds
        the tool would make "registered but never built" impossible to fail,
        which is exactly what the first version of this test did. A call
        inside a `def tools():` body is the register speaking; anywhere else is
        the tool actually being made.

        Answers `(built, declared)`, each `{name: [where]}`, with `None` for a
        name no static pass can read.
        """
        built, declared = {}, {}
        for path in sorted((GAME_DIR / self.WHERE).rglob("*.py")):
            relative = path.relative_to(GAME_DIR).as_posix()
            if relative in self.SKIP:
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"))
            registers = {node for node in ast.walk(tree)
                         if isinstance(node, ast.FunctionDef)
                         and node.name == "tools"}
            speaking = {inner for node in registers
                        for inner in ast.walk(node)}
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                if not isinstance(node.func, ast.Attribute):
                    continue
                if node.func.attr not in ("Tool", "from_schema"):
                    continue
                named = None
                if node.args and isinstance(node.args[0], ast.Constant) \
                        and isinstance(node.args[0].value, str):
                    named = node.args[0].value
                else:
                    for keyword in node.keywords:
                        if keyword.arg == "name" and isinstance(
                                keyword.value, ast.Constant):
                            named = keyword.value.value
                where = f"{relative}:{node.lineno}"
                into = declared if node in speaking else built
                into.setdefault(named, []).append(where)
        return built, declared

    def built(self):
        """{name: [where]} for every tool something actually makes."""
        return self._made()[0]

    def declared(self):
        """{name: [where]} for every tool a module's `tools()` stands in for."""
        return self._made()[1]

    def test_every_tool_built_is_on_the_register(self):
        from world import toolkit

        registered = set(toolkit.every_tool())
        missing = {name: where for name, where in self.built().items()
                   if name is not None and name not in registered}
        self.assertEqual(
            missing, {},
            "these tools are built and the register does not know them; add "
            "each to its module's `tools()` (or `lookup_tools()` if it is a "
            "lookup), so that whether an agent may call it is a decision "
            "somebody made")

    def test_every_tool_on_the_register_is_built(self):
        from world import toolkit

        built = set(self.built())
        stale = sorted(set(toolkit.every_tool()) - built)
        self.assertEqual(
            stale, [],
            "the register names tools that nothing builds; a name left behind "
            "after its tool is gone excludes nothing and hides the next tool "
            "that shares it")

    def test_every_declaration_stands_in_for_a_tool_that_exists(self):
        """
        A declaration is a stand-in, so there has to be something to stand in
        for. Delete the factory and leave the declaration, and this is what
        says so -- the register would otherwise go on advertising a tool the
        game cannot make.
        """
        built = set(self.built())
        orphans = {name: where for name, where in self.declared().items()
                   if name not in built}
        self.assertEqual(
            orphans, {},
            "these tools are declared by a module's `tools()` and nothing "
            "builds them; either the factory has gone and the declaration "
            "should go with it, or the tool is made under another name")

    def test_no_tool_is_made_under_a_name_nothing_can_read(self):
        """
        Every tool is named by a literal where it is built.

        This is what the NPC tool conversion bought. `NPC_TOOLS` were raw
        dicts passed through `from_schema`, so thirteen of the game's tools
        were named only inside a dictionary -- an AST pass found the other
        fifty and none of them. A name worked out at runtime is a tool this
        guard cannot see, and a guard with a blind spot is worse than none.
        """
        self.assertNotIn(
            None, self.built(),
            "a tool is built whose name is not a literal at the call site, so "
            "no static pass can find it; name it in the call")

    def test_a_name_is_claimed_once(self):
        from world import toolkit

        twice = {name: where
                 for name, where in toolkit.where_defined().items()
                 if len(where) > 1}
        self.assertEqual(
            twice, {},
            "two modules register a tool of the same name, so whichever is "
            "gathered second silently wins")

    def test_the_guard_would_bite(self):
        """Non-vacuous: there really are tools, and plenty of them."""
        from world import toolkit

        self.assertGreater(len(toolkit.every_tool()), 40)
        self.assertGreater(len(self.built()), 40)


class WhatTheRegisterSaysAboutEachTool(NoWorldTest):
    """Kinds, and which tools can be called at all."""

    def test_every_tool_has_one_of_the_three_kinds(self):
        from world import toolbox as tb, toolkit

        kinds = {tb.LOOKUP, tb.FINISH, tb.ACT}
        for name, tool in toolkit.every_tool().items():
            self.assertIn(tool.kind, kinds, name)

    def test_all_three_kinds_are_represented(self):
        from world import toolbox as tb, toolkit

        by_kind = toolkit.by_kind()
        for kind in (tb.LOOKUP, tb.FINISH, tb.ACT):
            self.assertTrue(by_kind.get(kind), f"nothing is a {kind}")

    def test_a_kind_is_worked_out_from_the_flags(self):
        from world import toolbox as tb

        self.assertEqual(tb.Tool("x", looks=True).kind, tb.LOOKUP)
        self.assertEqual(tb.Tool("x", finishes=True).kind, tb.FINISH)
        self.assertEqual(tb.Tool("x").kind, tb.ACT)

    def test_a_tool_with_no_handler_is_a_declaration(self):
        from world import toolbox as tb

        self.assertFalse(tb.Tool("x").runnable)
        self.assertTrue(tb.Tool("x", handler=lambda *a: None).runnable)

    def test_every_lookup_gathered_from_a_register_can_be_called(self):
        """
        A lookup defined beside the register it reads is always the real thing.

        Declarations exist because a finish tool cannot be built without the
        conversation it answers. A lookup gathered by `lookup_tools()` has no
        such excuse, and one declared rather than defined would be offered to
        an agent and then fail when called.

        A character's own lookup is the exception, and `check_traits` is the
        one: sizing somebody up does not count against what a character may do
        in a turn, so it is a lookup by kind, and like every other tool in
        `NPC_TOOLS` its handler belongs to one character's turn rather than to
        the module. It is `runnable` only once `_toolbox_for` has bound it.
        That is also the only thing keeping it away from an agent -- its kind
        alone would let it through -- which is why `offered_tools` asks about
        `runnable` before it asks about anything else.
        """
        from world import npc_gen, toolbox as tb, toolkit

        characters = {tool.name for tool in npc_gen.NPC_TOOLS}
        declared = sorted(name for name, tool in toolkit.every_tool().items()
                          if tool.kind == tb.LOOKUP and not tool.runnable
                          and name not in characters)
        self.assertEqual(declared, [])

    def test_a_characters_lookup_is_bound_for_the_turn_and_not_before(self):
        from world import npc_gen, toolbox as tb

        looking = [tool for tool in npc_gen.NPC_TOOLS
                   if tool.kind == tb.LOOKUP]
        self.assertTrue(looking, "no character tool only looks any more")
        for tool in looking:
            self.assertIn(tool.name, npc_gen.LOOKING)
            self.assertFalse(tool.runnable)

    def test_the_npc_tools_are_tool_objects_with_no_handler(self):
        from world import npc_gen, toolbox as tb

        for tool in npc_gen.NPC_TOOLS:
            self.assertIsInstance(tool, tb.Tool)
            self.assertFalse(tool.runnable, tool.name)
        self.assertEqual(npc_gen.TOOL_NAMES,
                         frozenset(tool.name for tool in npc_gen.NPC_TOOLS))

    def test_but_leaves_the_original_alone(self):
        from world import toolbox as tb

        tool = tb.Tool("x", "what it always means", {"type": "object"})
        changed = tool.but(description="just now", handler=lambda *a: None)
        self.assertEqual(tool.description, "what it always means")
        self.assertIsNone(tool.handler)
        self.assertEqual(changed.name, "x")
        self.assertEqual(changed.description, "just now")
        self.assertTrue(changed.runnable)

    def test_but_refuses_a_field_a_tool_does_not_have(self):
        from world import toolbox as tb

        with self.assertRaises(TypeError):
            tb.Tool("x").but(nonsense=True)


class WhatAnAgentIsAndIsNotOffered(GameTest):
    """
    The three rules in `agents.offered_tools`, each asserted against the real
    register rather than a handful of names.
    """

    accounts = True

    def agent_session(self):
        return Session(account=self.account, puppet=self.char1,
                       logged_in=True)

    def offered(self):
        from world import agents

        return agents.offered_tools(agents._context(self.agent_session()))

    def test_nothing_that_cannot_be_called_is_offered(self):
        for name, tool in self.offered().items():
            self.assertTrue(tool.runnable, name)

    def test_no_tool_that_acts_is_offered(self):
        from world import agents, toolbox as tb

        ours = {tool.name for tool in agents.document_tools()}
        for name, tool in self.offered().items():
            if name in ours:
                continue
            self.assertEqual(tool.kind, tb.LOOKUP, name)

    def test_a_characters_own_tools_are_not_offered(self):
        """
        `move`, `say`, `get` and the rest are typed with `send`, not called.

        They are on the register -- a character has them -- and an agent must
        not be handed them, because typing goes through the parser, the rules
        and everyone watching, and a direct call would go through none of it.
        """
        from world import npc_gen

        offered = set(self.offered())
        for tool in npc_gen.NPC_TOOLS:
            self.assertNotIn(tool.name, offered)

    def test_no_generator_finish_tool_is_offered(self):
        from world import toolbox as tb, toolkit

        offered = set(self.offered())
        for name, tool in toolkit.every_tool().items():
            if tool.kind == tb.FINISH:
                self.assertNotIn(name, offered)

    def test_every_lookup_that_can_answer_is_offered(self):
        """
        The half that makes this worth doing: a lookup added tomorrow beside
        the register it reads reaches an agent with nobody wiring it up.
        """
        from world import agents, toolbox as tb, toolkit

        ctx = agents._context(self.agent_session())
        offered = set(self.offered())
        for name, tool in toolkit.every_tool().items():
            if tool.kind != tb.LOOKUP or not tool.runnable:
                continue
            if name in agents.NOT_OFFERED or tool.threaded:
                continue
            if not tool.offered(ctx):
                continue
            self.assertIn(name, offered, name)

    def test_what_is_left_out_is_left_out_on_purpose(self):
        from world import agents, toolbox as tb, toolkit

        unaccounted = sorted(
            name for name, tool in toolkit.every_tool().items()
            if tool.kind == tb.LOOKUP and tool.runnable and tool.threaded
            and name not in agents.NOT_OFFERED)
        self.assertEqual(
            unaccounted, [],
            "these lookups cannot be offered as they are and nothing says so; "
            "add each to agents.NOT_OFFERED with the reason, or give it the "
            "deferred shape an agent can call")

    def test_nothing_is_left_out_that_no_longer_exists(self):
        from world import agents, toolkit

        stale = sorted(set(agents.NOT_OFFERED) - set(toolkit.every_tool()))
        self.assertEqual(stale, [])

    def test_each_reason_is_a_real_one(self):
        from world import agents

        for name, why in agents.NOT_OFFERED.items():
            self.assertGreater(len(why), 20, name)

    def test_everything_never_cut_is_a_real_tool(self):
        from world import agents

        names = {tool.name for tool in agents.document_tools()}
        self.assertLessEqual(agents.WHOLE, names)

    def test_the_two_local_tools_are_not_claimed_twice(self):
        """
        `send` and `poll` are answered in the Portal and must not also be on
        the register, or an agent gets two tools of one name and the Portal's
        wins silently.
        """
        from server.conf import mcp_protocol
        from world import toolkit

        self.assertEqual(
            set(mcp_protocol.LOCAL_TOOLS) & set(toolkit.every_tool()), set())


class TheManual(GameTest):
    """
    The documentation an agent reads, and the half of it that is generated.

    The generated half is the point: a page listing the tools, the commands or
    the effects by hand is wrong the first time anything is added, so these
    assert that each page is built from the register rather than transcribed
    from it. A page that has fallen behind fails here rather than misleading
    whoever read it.
    """

    accounts = True

    def test_every_page_has_a_title_and_a_body(self):
        from world import manual

        self.assertTrue(manual.PAGES)
        for key, _title in manual.contents():
            text = manual.page(key)
            self.assertGreater(len(text), 200, key)

    def test_the_first_page_exists_and_names_the_others(self):
        from world import manual

        first = manual.page(manual.FIRST)
        for key, _title in manual.contents():
            if key == manual.FIRST:
                continue
            self.assertIn(key, first, f"{key} is not mentioned on the front page")

    def test_a_page_nobody_has_asks_for_the_ones_there_are(self):
        from world import manual

        said = manual.page("nonsense")
        self.assertIn("no page called that", said)
        self.assertIn(manual.FIRST, said)

    def test_no_page_asked_for_at_all_is_the_first_one(self):
        from world import manual

        self.assertEqual(manual.page(""), manual.page(manual.FIRST))
        self.assertEqual(manual.page(None), manual.page(manual.FIRST))

    def test_the_tools_page_lists_the_tools_that_exist(self):
        from world import agents, manual, toolbox as tb

        page = manual.page("tools")
        offered = agents.offered_tools(tb.ToolContext())
        self.assertTrue(offered)
        for name in offered:
            self.assertIn(name, page, f"{name} is offered and unmentioned")
        self.assertIn("send", page)
        self.assertIn("poll", page)

    def test_the_tools_page_says_what_is_left_out_and_why(self):
        from world import agents, manual

        page = manual.page("tools")
        for name, why in agents.NOT_OFFERED.items():
            self.assertIn(name, page)
            self.assertIn(why.split(":")[0], page)

    def test_the_commands_page_lists_every_verb_and_maker(self):
        from commands import subjects
        from world import making, manual

        page = manual.page("commands")
        verbs = {verb for subject in subjects.registered()
                 for verb in subject.uses}
        for verb in verbs:
            self.assertIn(verb, page, f"the verb {verb} is unmentioned")
        for maker in making.registered():
            self.assertIn(maker.key, page, f"{maker.key} is unmentioned")

    def test_the_effects_page_lists_every_effect_a_rule_may_use(self):
        from world import effects, manual

        page = manual.page("effects")
        for name in effects.VOCABULARY:
            self.assertIn(name, page, f"the effect {name} is unmentioned")

    def test_a_page_is_plain_text_a_screen_reader_can_read(self):
        """
        No colour codes, no tables, no aligned columns of figures.

        Read aloud at least as often as looked at -- the same reason `score`
        and `worldcheck` have no bars or columns.
        """
        from world import manual

        for key, _title in manual.contents():
            text = manual.page(key)
            self.assertNotIn("|w", text, key)
            self.assertNotIn("|n", text, key)
            self.assertNotIn("+---", text, key)


class TheManualIsReachable(GameTest):
    """It is a tool, gathered the way every other lookup is."""

    accounts = True

    def agent_session(self):
        return Session(account=self.account, puppet=self.char1,
                       logged_in=True)

    def test_it_is_on_the_register(self):
        from world import toolkit

        self.assertIn("manual", toolkit.every_tool())

    def test_it_is_a_lookup(self):
        from world import toolbox as tb, toolkit

        self.assertEqual(toolkit.every_tool()["manual"].kind, tb.LOOKUP)

    def test_an_agent_is_offered_it_without_anything_wiring_it_up(self):
        from world import agents

        names = {schema["name"]
                 for schema in agents.tool_schemas(self.agent_session())}
        self.assertIn("manual", names)

    def test_calling_it_answers_a_page(self):
        from world import agents, manual

        said, failed = agents.run_tool(self.agent_session(), "manual",
                                       {"page": "documents"})
        self.assertFalse(failed, said)
        self.assertIn("export_world", said)
        self.assertEqual(said, manual.page("documents"))

    def test_calling_it_with_no_page_answers_the_first(self):
        from world import agents, manual

        said, failed = agents.run_tool(self.agent_session(), "manual", {})
        self.assertFalse(failed, said)
        self.assertEqual(said, manual.page(manual.FIRST))

    def test_its_schema_names_every_page(self):
        from world import agents, manual

        schema = next(s for s in agents.tool_schemas(self.agent_session())
                      if s["name"] == "manual")
        choices = schema["inputSchema"]["properties"]["page"]["enum"]
        self.assertEqual(sorted(choices), sorted(manual.PAGES))

    def test_the_greeting_points_at_it(self):
        from world import agents, manual

        said = agents.greeting(self.account)
        self.assertIn("manual", said)
        self.assertIn(manual.FIRST, said)

    def test_no_page_is_longer_than_one_answer_may_be(self):
        """
        A page is cut at `MOST_RESULT` like anything else, and a page that has
        to be cut is one nobody reads the end of. The remedy is another page,
        not a longer one.
        """
        from world import agents, manual

        for key, _title in manual.contents():
            self.assertLess(len(manual.page(key)), agents.MOST_RESULT,
                            f"the {key} page is too long to arrive whole")


class TheCharacterToolsAreNotMutatedByBeingOffered(GameTest):
    """
    Offering a tool must leave the definition alone.

    `NPC_TOOLS` is module-level and every character in the game shares it, so a
    shallow copy anywhere in `_with_choices`, `_described` or `_without` would
    close one character's `get` to whatever was lying in one room and leave it
    that way for everybody, in every world, until the server restarted. The
    kind of bug that looks like a model misbehaving.
    """

    def setUp(self):
        super().setUp()
        self.room1.db.world_root = self.room1
        self.room1.db.is_world_root = True
        self.room1.db.is_ai_room = True
        from evennia import create_object
        from typeclasses.npcs import NPC

        self.npc = create_object(NPC, key="Bram", location=self.room1)
        self.thing = create_object("typeclasses.objects.Object",
                                   key="lantern", location=self.room1)

    def definitions(self):
        import json

        from world import npc_gen, toolbox as tb

        ctx = tb.ToolContext(room=self.room1, actor=self.npc)
        return json.dumps([tool.schema(ctx) for tool in npc_gen.NPC_TOOLS],
                          sort_keys=True)

    def test_offering_changes_nothing_about_the_definitions(self):
        from world import npc_gen

        before = self.definitions()
        npc_gen._tools_for(self.npc, self.room1)
        npc_gen._tools_for(self.npc, self.room1)
        self.assertEqual(before, self.definitions())

    def test_no_definition_carries_a_choice_from_one_room(self):
        from world import npc_gen

        npc_gen._tools_for(self.npc, self.room1)
        for tool in npc_gen.NPC_TOOLS:
            properties = (tool.parameters or {}).get("properties") or {}
            for argument, spec in properties.items():
                self.assertNotIn("enum", spec,
                                 f"{tool.name}.{argument} kept an enum")
                self.assertNotIn("minimum", spec,
                                 f"{tool.name}.{argument} kept a bound")

    def test_a_note_about_one_moment_does_not_stick(self):
        from world import npc_gen

        said = {tool.name: tool.description for tool in npc_gen.NPC_TOOLS}
        offered = {tool.name: tool.description
                   for tool in npc_gen._tools_for(self.npc, self.room1)}
        # At least one tool really is told something about this moment, or this
        # test is asserting nothing.
        self.assertTrue(
            any(offered.get(name, "") != description
                for name, description in said.items()),
            "no tool was told anything about this moment")
        for tool in npc_gen.NPC_TOOLS:
            self.assertEqual(tool.description, said[tool.name])


class TheRegistersModuleListsDoNotDrift(NoWorldTest):
    """
    One list of modules, not two.

    `toolkit.modules()` is `lookups.MODULES` plus `toolkit.ALSO`. Keeping a
    second full copy would mean a module added for its lookups and forgotten
    here would have them vanish off the register -- and so out of an agent's
    hands -- with nothing anywhere saying so.
    """

    def test_also_adds_only_what_lookups_does_not_have(self):
        from world import lookups, toolkit

        both = sorted(set(toolkit.ALSO) & set(lookups.MODULES))
        self.assertEqual(
            both, [],
            "these are in lookups.MODULES already; toolkit.ALSO is only for "
            "modules whose tools are not lookups")

    def test_every_module_with_lookups_is_on_the_register(self):
        from world import lookups, toolkit

        self.assertTrue(set(lookups.MODULES) <= set(toolkit.modules()))

    def test_every_module_named_is_a_module_that_defines_a_tool(self):
        import importlib

        from world import toolkit

        for name in toolkit.modules():
            module = importlib.import_module(f"world.{name}")
            self.assertTrue(
                hasattr(module, "lookup_tools") or hasattr(module, "tools"),
                f"world/{name}.py is on the register and defines no tool")
