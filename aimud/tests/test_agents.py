"""
An agent playing here: its token, the tools it is offered, and the guard.

Three kinds of test, and the third is the one that matters over time.

`TokensAreMinted` and `WhoIsAsking` are about the credential: generated rather
than typed, compared without leaking its own prefix, and refused in every way
it can be wrong. `ToolsAreOffered` and `DocumentsTravel` are about the tools,
and the round trip is the same round trip `test_exchange` makes -- exported,
imported, exported -- driven through the tool an agent would call rather than
the command a player would type.

`EveryToolIsAccountedFor` is the third kind. It walks every tool this codebase
offers a model and fails when one is neither offered to an agent nor named in
`agents.NOT_OFFERED` with its reason, so a tool added tomorrow is a decision
about whether an agent gets it rather than a silence. The same arrangement
`exchange.CARRIED` and `exchange.LEFT` have with the attribute test, for the
same reason: without it, the surface is right on the day it is written and
quietly wrong afterwards. See docs/mcp.md §10.

Nothing here opens a socket. The Portal half is HTTP and Twisted and is proved
by running it; what these hold level is the half that lives in the game.
"""

import json

from tests.base import GameTest, NoWorldTest

# The hand-built world and its furnishing, borrowed rather than written again:
# a second world fixture would be a second thing to keep level, and this one
# already populates every section a document has.
from tests.test_exchange import WorldTest


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


class EveryToolIsAccountedFor(NoWorldTest):
    """
    A tool is offered to an agent or named as left out, with the reason.

    The guard against the one way this surface rots: somebody adds a lookup
    beside the register it reads, every generator and NPC gets it, and whether
    an agent should have it is a question nobody was asked. §10 of docs/mcp.md.
    """

    def test_no_tool_is_left_out_by_accident(self):
        from world import agents, lookups

        unaccounted = sorted(
            name for name, tool in lookups.all_tools().items()
            if tool.threaded and name not in agents.NOT_OFFERED)
        self.assertEqual(
            unaccounted, [],
            "these tools cannot be offered as they are and nothing says so; "
            "add each to agents.NOT_OFFERED with the reason, or give it the "
            "deferred shape an agent can call")

    def test_nothing_is_left_out_that_no_longer_needs_to_be(self):
        from world import agents, lookups

        every = set(lookups.all_tools())
        stale = sorted(set(agents.NOT_OFFERED) - every)
        self.assertEqual(
            stale, [],
            "agents.NOT_OFFERED names tools that no longer exist; a name left "
            "here after the tool is gone excludes nothing and hides the next "
            "one that shares its name")

    def test_a_tool_left_out_has_a_reason(self):
        from world import agents

        for name, why in agents.NOT_OFFERED.items():
            self.assertTrue(len(why) > 20, f"{name} has no real reason")

    def test_the_guard_would_bite(self):
        """
        Non-vacuous: there is a threaded tool, and it is the one named.

        A guard whose set is empty passes forever. This asserts the shape it is
        guarding actually occurs.
        """
        from world import agents, lookups

        threaded = {name for name, tool in lookups.all_tools().items()
                    if tool.threaded}
        self.assertTrue(threaded, "nothing is threaded; this guard is vacuous")
        self.assertTrue(threaded <= set(agents.NOT_OFFERED))

    def test_everything_never_cut_is_a_real_tool(self):
        from world import agents

        names = {tool.name for tool in agents.document_tools()}
        self.assertTrue(agents.WHOLE <= names, agents.WHOLE - names)

    def test_the_two_local_tools_are_not_claimed_twice(self):
        """
        `send` and `poll` are answered in the Portal and must not also be
        Server-side tools, or an agent gets two tools of one name and the
        Portal's wins silently.
        """
        from server.conf import mcp_protocol
        from world import agents, lookups

        local = set(mcp_protocol.LOCAL_TOOLS)
        theirs = set(lookups.all_tools()) | {
            tool.name for tool in agents.document_tools()}
        self.assertEqual(local & theirs, set())
