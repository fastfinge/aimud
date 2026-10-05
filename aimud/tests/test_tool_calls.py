"""
The `call_tool` effect: a rule asking a service something, or having it act.

docs/archived/mcp-client.md §6 and §7. A tool reaches a world only through a rule, so
everything here is driven the way a player drives it: a verb typed, a rule
found, the call made, and the answer landing -- as a condition, a figure, a
description, or told privately to whoever asked. Never as narration, and never
to the room.

The server is `tests/fixtures/weather_server.py`, served in process by the
real manager (`tests.support.serving`); `immediately` makes `llm.fetch`
synchronous, so by the time an attempt returns its calls have been made.
"""

from unittest import mock

from django.test import SimpleTestCase, tag
from evennia import create_object

from tests.base import GameTest
from tests.support import FakeSponsor, immediately, serving
from world import actions, services, tool_calls, verbs
from world import rulebooks as R


# ---------------------------------------------------------------------------
# Reading and writing what a rule says
# ---------------------------------------------------------------------------

@tag("unit")
class Sources(SimpleTestCase):

    def test_each_reads(self):
        self.assertEqual(tool_calls.read_source("value:metric"),
                         {"from": "value", "value": "metric"})
        self.assertEqual(tool_calls.read_source("word:direct"),
                         {"from": "word", "role": "direct"})
        self.assertEqual(tool_calls.read_source("name:actor"),
                         {"from": "name", "role": "actor"})
        self.assertEqual(tool_calls.read_source("trait:actor:strength"),
                         {"from": "trait", "role": "actor", "name": "strength"})
        self.assertEqual(tool_calls.read_source("state:here:weather"),
                         {"from": "state", "role": "here", "name": "weather"})
        self.assertEqual(tool_calls.read_source("ask"), {"from": "ask"})

    def test_a_value_may_hold_colons(self):
        self.assertEqual(tool_calls.read_source("value:12:30")["value"], "12:30")

    def test_nonsense_does_not_read(self):
        for text in ("", "word", "word:nobody", "trait:actor", "colour:red"):
            with self.subTest(text=text):
                self.assertIsNone(tool_calls.read_source(text))

    def test_written_and_read_back(self):
        for text in ("value:x", "word:direct", "trait:actor:luck",
                     "state:here:weather", "ask", "name:target"):
            with self.subTest(text=text):
                self.assertEqual(
                    tool_calls.write_source(tool_calls.read_source(text)), text)


@tag("unit")
class Targets(SimpleTestCase):

    def test_each_reads(self):
        self.assertEqual(tool_calls.read_target("state:here"),
                         {"to": "state", "role": "here"})
        self.assertEqual(tool_calls.read_target("trait:actor:luck"),
                         {"to": "trait", "role": "actor", "name": "luck"})
        self.assertEqual(tool_calls.read_target("description:direct"),
                         {"to": "description", "role": "direct"})
        self.assertEqual(tool_calls.read_target("actor"), {"to": "actor"})

    def test_nonsense_does_not_read(self):
        for text in ("", "room", "state:", "trait:actor", "narration"):
            with self.subTest(text=text):
                self.assertIsNone(tool_calls.read_target(text))


@tag("unit")
class AnswersInBrackets(SimpleTestCase):

    def test_taken_off_the_line(self):
        self.assertEqual(tool_calls.answers_in("forecast london [units=metric days=3]"),
                         ("forecast london", {"units": "metric", "days": "3"}))

    def test_quoted_values(self):
        self.assertEqual(tool_calls.answers_in('send [to="Ana B" text=hi]')[1],
                         {"to": "Ana B", "text": "hi"})

    def test_nothing_in_brackets_is_left_alone(self):
        self.assertEqual(tool_calls.answers_in("look at the [sign]"),
                         ("look at the [sign]", {}))
        self.assertEqual(tool_calls.answers_in("forecast london"),
                         ("forecast london", {}))


# ---------------------------------------------------------------------------
# Whether a call is one that can be made
# ---------------------------------------------------------------------------

def _call(tool="weather.forecast", **fields):
    effect = {"type": "call_tool", "tool": tool,
              "args": {"city": "word:direct"}, "results": {}}
    effect.update(fields)
    return effect


@tag("world")
class Complaints(GameTest):

    def test_a_good_one_has_none(self):
        with serving():
            self.assertEqual(tool_calls.complaints(_call(
                results={"conditions": "state:here", "high_c": "trait:actor:warmth"})), [])

    def test_no_such_service_or_tool(self):
        with serving():
            self.assertIn("no service", tool_calls.complaints(_call("nowhere.x"))[0])
            self.assertIn("no tool", tool_calls.complaints(_call("weather.nope"))[0])

    def test_a_tool_switched_off(self):
        with serving() as record:
            record["tools"]["forecast"]["on"] = False
            services.put(record)
            self.assertIn("switched off", tool_calls.complaints(_call())[0])

    def test_a_refused_tool(self):
        with serving():
            said = tool_calls.complaints(_call("weather.ledger", args={}))
            self.assertIn("cannot be called", said[0])

    def test_a_required_parameter_with_no_source(self):
        with serving():
            said = tool_calls.complaints(_call(args={}))
            self.assertTrue(any("needs city" in line for line in said), said)

    def test_a_parameter_it_does_not_take(self):
        with serving():
            said = tool_calls.complaints(_call(args={"city": "word:direct",
                                                     "colour": "value:red"}))
            self.assertTrue(any("colour" in line for line in said), said)

    def test_a_condition_needs_set_answers(self):
        with serving():
            said = tool_calls.complaints(_call(results={"high_c": "state:here"}))
            self.assertTrue(any("set of answers" in line for line in said), said)

    def test_a_figure_needs_a_number(self):
        with serving():
            said = tool_calls.complaints(
                _call(results={"conditions": "trait:actor:warmth"}))
            self.assertTrue(any("not a number" in line for line in said), said)

    def test_words_can_only_be_told_or_described(self):
        with serving():
            said = tool_calls.complaints(_call(results={"text": "state:here"}))
            self.assertTrue(any("description" in line for line in said), said)

    def test_a_model_may_not_ask(self):
        """§7.6: a learned rule is used by characters and the planner."""
        with serving():
            self.assertEqual(tool_calls.complaints(_call(args={"city": "ask"})), [])
            said = tool_calls.complaints(_call(args={"city": "ask"}), by_model=True)
            self.assertTrue(any("cannot be asked" in line for line in said), said)


@tag("world")
class Completing(GameTest):

    def setUp(self):
        super().setUp()
        self.root = self.room1
        self.root.db.is_world_root = True
        self.root.db.world_root = self.root

    def test_what_it_does_is_copied_never_typed(self):
        with serving() as record:
            kept = R.add(self.root, R.blank(
                action="forecast", phase=R.CARRY_OUT,
                effects=[_call(does="Steals your wallet.")]))
            effect = kept["effects"][0]
            self.assertEqual(effect["does"], "Gets today's forecast for a city.")
            self.assertEqual(effect["fingerprint"],
                             record["tools"]["forecast"]["fingerprint"])

    def test_an_enum_is_registered_before_it_comes_back(self):
        """So the rules about rain can be written before it rains."""
        with serving():
            R.add(self.root, R.blank(action="forecast", phase=R.CARRY_OUT,
                                     effects=[_call(results={"conditions": "state:here"})]))
            known = set(verbs.vocabulary(self.root))
            for value in ("sunny", "rain", "storm"):
                self.assertIn(value, known)


# ---------------------------------------------------------------------------
# The whole road: a verb typed, a call made, an answer landing
# ---------------------------------------------------------------------------

class _AWorldWithWeather(GameTest):

    def setUp(self):
        super().setUp()
        self.root = self.room1
        self.root.db.is_world_root = True
        self.root.db.world_root = self.root
        self.root.db.is_ai_room = True
        self.watcher = create_object("typeclasses.characters.Character",
                                     key="Watcher", location=self.room1)

    def rule(self, action, effects, **fields):
        actions.declare(self.root, action,
                        applies_to=[{"role": "direct", "optional": True}])
        fields.setdefault("report", "{actor} $pconj(consult) the almanac.")
        return R.add(self.root, R.blank(action=action, phase=R.CARRY_OUT,
                                        scope={"world": True},
                                        effects=effects, **fields))

    def attempt(self, line, who=None, sponsor=None):
        """Type a line, and answer with what the actor and the room read."""
        from world import attempt as attempt_mod
        from world import events

        who = who or self.char1
        mine, theirs = [], []
        with mock.patch.object(who, "msg", side_effect=lambda text=None, **kw:
                               mine.append(str(text))), \
             mock.patch.object(self.watcher, "msg",
                               side_effect=lambda text=None, **kw:
                               theirs.append(str(text))):
            with immediately():
                attempt_mod.attempt(
                    who, line, sponsor if sponsor is not None else FakeSponsor(key=""),
                    on_message=lambda text, event=None: events.show(text, event, who))
        return "\n".join(mine), "\n".join(theirs)


@tag("world")
class AnAnswerBecomesACondition(_AWorldWithWeather):

    def test_the_word_typed_is_passed_and_nothing_is_conjured(self):
        with serving():
            self.rule("forecast", [_call(results={"conditions": "state:here"})])
            self.attempt("forecast london")
        self.assertIn("rain", verbs.states(self.room1))
        self.assertFalse([obj for obj in self.room1.contents
                          if obj.key.lower() == "london"],
                         "a London was conjured for a word a rule wanted")

    def test_a_new_answer_replaces_the_old_one(self):
        with serving():
            self.rule("forecast", [_call(results={"conditions": "state:here"})])
            self.attempt("forecast london")
            self.attempt("forecast lisbon")
        states = verbs.states(self.room1)
        self.assertIn("sunny", states)
        self.assertNotIn("rain", states)

    def test_the_room_reads_the_verb_and_not_the_answer(self):
        with serving():
            self.rule("forecast", [_call(results={"conditions": "state:here"})])
            _mine, theirs = self.attempt("forecast london")
        self.assertIn("consults the almanac", theirs)
        self.assertNotIn("12", theirs)


@tag("world")
class TextToldToWhoeverAsked(_AWorldWithWeather):

    def pubs(self):
        return [{"type": "call_tool", "tool": "weather.pubs",
                 "args": {"near": "word:direct"}, "results": {"text": "actor"}}]

    def test_a_player_reads_it_and_the_room_does_not(self):
        with serving():
            self.rule("find", self.pubs())
            mine, theirs = self.attempt("find london")
        self.assertIn("The Lamb", mine)
        self.assertNotIn("The Lamb", theirs)

    def test_a_character_has_it_labelled_and_remembers_it(self):
        from typeclasses.npcs import NPC

        npc = create_object(NPC, key="Mara", location=self.room1)
        with serving(), mock.patch("world.memory.remember") as remembered, \
                mock.patch.object(NPC, "_note_to_self") as noted:
            self.rule("find", self.pubs())
            self.attempt("find london", who=npc, sponsor=FakeSponsor())
        told = noted.call_args[0][0]
        self.assertIn("From outside the game, by weather.pubs", told)
        self.assertIn("The Lamb", told)
        memories = [call[0][1] for call in remembered.call_args_list]
        self.assertTrue(any("The Lamb" in line and "From outside the game" in line
                            for line in memories), memories)

    def test_it_can_become_a_description_instead(self):
        board = create_object("typeclasses.objects.Object", key="Board",
                              location=self.room1)
        with serving():
            self.rule("post", [{"type": "call_tool", "tool": "weather.pubs",
                                "args": {"near": "value:London"},
                                "results": {"text": "description:direct"}}])
            self.attempt("post board")
        self.assertIn("The Eagle", board.db.desc)


@tag("world")
class TheGateOnTheRoad(_AWorldWithWeather):

    def postcard(self):
        return [{"type": "call_tool", "tool": "weather.send_postcard",
                 "args": {"to": "value:Ana", "text": "value:hello"},
                 "results": {}}]

    def test_a_player_acting_outward_with_nobody_paying_is_refused(self):
        from tests.fixtures import weather_server

        with serving():
            self.rule("post", self.postcard())
            mine, _theirs = self.attempt("post", sponsor=FakeSponsor(key=""))
            self.assertEqual(weather_server.SENT, [])
        self.assertIn("paying", mine)

    def test_with_somebody_paying_it_is_sent_once_and_recorded(self):
        from tests.fixtures import weather_server

        with serving():
            self.rule("post", self.postcard())
            self.attempt("post", sponsor=FakeSponsor())
            self.assertEqual(weather_server.SENT, [("Ana", "hello")])
            recent = services.get("weather")["recent"]
        self.assertEqual(len(recent), 1)
        self.assertEqual(recent[0]["tool"], "send_postcard")
        self.assertEqual(recent[0]["actor"], self.char1.key)

    def test_a_player_looking_outward_needs_nobody_paying(self):
        with serving():
            self.rule("forecast", [_call(results={"conditions": "state:here"})])
            self.attempt("forecast london", sponsor=FakeSponsor(key=""))
        self.assertIn("rain", verbs.states(self.room1))

    def test_a_character_with_nobody_paying_reaches_nothing(self):
        from typeclasses.npcs import NPC

        npc = create_object(NPC, key="Mara", location=self.room1)
        with serving():
            self.rule("forecast", [_call(results={"conditions": "state:here"})])
            self.attempt("forecast london", who=npc, sponsor=FakeSponsor(key=""))
        self.assertNotIn("rain", verbs.states(self.room1))


@tag("world")
class WhenACallFails(_AWorldWithWeather):

    def test_nothing_in_the_batch_is_applied(self):
        with serving():
            self.rule("forecast", [
                {"type": "set_state", "role": "actor", "add": ["hopeful"]},
                {"type": "call_tool", "tool": "weather.flaky",
                 "args": {"why": "value:no"}, "results": {}}])
            mine, _theirs = self.attempt("forecast")
        self.assertNotIn("hopeful", verbs.states(self.char1))
        self.assertIn("said no", mine)

    def test_a_service_that_cannot_be_reached_says_so(self):
        with serving():
            self.rule("forecast", [_call(results={"conditions": "state:here"})])
            with mock.patch.object(services, "call", return_value=services.Answer(
                    error="refused", reached=False)):
                mine, _theirs = self.attempt("forecast london")
        self.assertIn("cannot be reached", mine)
        self.assertNotIn("rain", verbs.states(self.room1))

    def test_a_tool_that_changed_shape_is_not_called(self):
        with serving() as record:
            self.rule("forecast", [_call(results={"conditions": "state:here"})])
            record = services.get("weather")
            record["tools"]["forecast"]["fingerprint"] = "sha256:changed"
            services.put(record)
            mine, _theirs = self.attempt("forecast london")
        self.assertIn("not what this rule was written for", mine)


@tag("world")
class Asking(_AWorldWithWeather):

    def test_answers_in_brackets(self):
        with serving():
            self.rule("forecast", [_call(args={"city": "ask"},
                                         results={"conditions": "state:here"})])
            self.attempt("forecast [city=lisbon]")
        self.assertIn("sunny", verbs.states(self.room1))

    def test_nobody_to_ask_is_told_what_to_type(self):
        with serving():
            self.rule("forecast", [_call(args={"city": "ask"},
                                         results={"conditions": "state:here"})])
            mine, _theirs = self.attempt("forecast")
        self.assertIn("[city=...]", mine)
        self.assertNotIn("rain", verbs.states(self.room1))


@tag("world")
class RetryingOnlyWhatIsSafeToRepeat(_AWorldWithWeather):
    """§7.5: retrying an email sends it twice."""

    def retried(self, tool, args):
        seen = []
        real = services.call

        def recording(record, name, arguments, retry=False):
            seen.append(retry)
            return real(record, name, arguments, retry=retry)

        with serving():
            self.rule("go", [{"type": "call_tool", "tool": tool,
                              "args": args, "results": {}}])
            with mock.patch.object(services, "call", recording):
                self.attempt("go", sponsor=FakeSponsor())
        return seen

    def test_a_tool_that_says_nothing_is_never_sent_again(self):
        self.assertEqual(self.retried("weather.send_postcard",
                                      {"to": "value:Ana", "text": "value:hi"}),
                         [False])

    def test_one_that_says_it_is_idempotent_may_be(self):
        self.assertEqual(self.retried("weather.roll", {"sides": "value:4"}), [True])


# ---------------------------------------------------------------------------
# A person writing it: the effect form, and the add-action shortcut (§8)
# ---------------------------------------------------------------------------

@tag("world")
class ThroughTheRuleForm(GameTest):

    def setUp(self):
        super().setUp()
        self.root = self.room1
        self.root.db.is_world_root = True
        self.root.db.world_root = self.root

    def ctx(self, **draft):
        from world import menus

        return menus.Context(self.char1, world_root=self.root, draft=draft)

    def test_the_form_asks_for_the_tool_and_both_lists(self):
        from world.makers import rules

        with serving():
            keys = [item.key for item in
                    rules.NEW_EFFECT.items_for(self.ctx(type="call_tool"))]
        for key in ("tool", "args", "results"):
            self.assertIn(key, keys)

    def test_only_usable_tools_are_offered(self):
        from world.makers import rules

        with serving():
            offered = [value for value, _label in rules.tool_options(self.ctx())]
        self.assertIn("weather.forecast", offered)
        self.assertNotIn("weather.ledger", offered)

    def test_keeping_turns_the_lists_into_mappings(self):
        from world.makers import rules

        with serving():
            effect, said = rules.keep_effect(self.ctx(
                type="call_tool", tool="weather.forecast",
                args=[{"param": "city", "source": "word:direct"}],
                results=[{"field": "conditions", "target": "state:here"}]))
        self.assertEqual(effect["args"], {"city": "word:direct"})
        self.assertEqual(effect["results"], {"conditions": "state:here"})
        self.assertIn("weather.forecast", said)

    def test_a_call_that_cannot_be_made_is_refused_and_says_why(self):
        from world import menus
        from world.makers import rules

        with serving():
            with self.assertRaises(menus.Refuse) as refused:
                rules.keep_effect(self.ctx(type="call_tool",
                                           tool="weather.forecast", args=[],
                                           results=[]))
        self.assertIn("needs city", str(refused.exception))

    def test_a_source_is_written_from_the_sub_form(self):
        from world.makers import rules

        with serving():
            value, said = rules._keep_arg(self.ctx(param="city", source="word",
                                                   role="direct"))
        self.assertEqual(value, {"param": "city", "source": "word:direct"})
        self.assertIn("word typed", said)


@tag("world")
class TheAddActionShortcut(GameTest):

    def setUp(self):
        super().setUp()
        self.root = self.room1
        self.root.db.is_world_root = True
        self.root.db.world_root = self.root

    def test_declares_the_verb_and_writes_the_rule_that_calls_it(self):
        from world import menus
        from world.makers import doing

        with serving():
            ctx = menus.Context(self.char1, world_root=self.root, draft={
                "action": "forecast", "tool": "weather.forecast",
                "applies_to": [{"role": "direct", "access": "visible",
                                "optional": False}]})
            word, said = doing.keep_action(ctx)
        self.assertEqual(word, "forecast")
        spec = actions.spec(self.root, "forecast")
        self.assertEqual(spec["means"], "Gets today's forecast for a city.")
        rules = [r for r in R.all_rules(self.root)
                 if r.get("action") == "forecast"]
        self.assertEqual(len(rules), 1)
        effect = rules[0]["effects"][0]
        self.assertEqual(effect["tool"], "weather.forecast")
        self.assertEqual(effect["args"], {"city": "typed"})
        self.assertEqual(effect["results"], {"text": "actor"})
        self.assertIn("calls weather.forecast", said)


@tag("world")
class AVerbThatCallsAToolTakesWhatIsTyped(_AWorldWithWeather):
    """
    Found on the live server: `websearch fastfinge` opened a menu. The verb
    had been declared taking nothing, so the shortcut had set the search's
    query to be asked. A verb that calls a tool now takes what is typed after
    it, all of it.
    """

    def made(self):
        from world import menus
        from world.makers import doing

        ctx = menus.Context(self.char1, world_root=self.root, draft={
            "action": "websearch", "tool": "weather.search"})
        doing.keep_action(ctx)

    def test_with_no_parts_given_it_takes_something_said(self):
        with serving():
            self.made()
        spec = actions.spec(self.root, "websearch")
        self.assertEqual(spec["applies_to"],
                         [{"role": "direct", "access": "visible",
                           "optional": False}])

    def test_everything_typed_is_the_query_prepositions_and_all(self):
        with serving():
            self.made()
            mine, _theirs = self.attempt("websearch best muds in london")
        self.assertIn("best muds in london|None|None", mine)

    def test_no_menu_opens_for_one_word(self):
        with serving():
            self.made()
            mine, _theirs = self.attempt("websearch fastfinge")
        self.assertIn("fastfinge|None|None", mine)
        self.assertNotIn("[query=...]", mine)

    def test_alone_it_asks_what(self):
        with serving():
            self.made()
            mine, _theirs = self.attempt("websearch")
        self.assertIn("what", mine.lower())
        self.assertNotIn("|None|", mine)


@tag("world")
class TheFormAPlayerIsAsked(GameTest):
    """Built from the schema: an enum is a choice, a number a number."""

    def test_each_parameter_is_the_field_its_schema_says(self):
        from world import menus

        info = {"description": "Plans a trip.", "input": {"properties": {
            "city": {"type": "string"},
            "days": {"type": "integer", "minimum": 1, "maximum": 7},
            "units": {"enum": ["metric", "imperial"]},
            "rain_ok": {"type": "boolean"}}}}
        got = {}
        form = tool_calls.ask_form(["city", "days", "units", "rain_ok"], info,
                                   on_answered=got.update, on_quit=lambda: None)
        fields = {item.key: item for item in form.items_for(menus.Context(self.char1))
                  if isinstance(item, menus.Field)}
        self.assertEqual(fields["city"].kind, menus.TEXT)
        self.assertEqual(fields["days"].kind, menus.NUMBER)
        self.assertEqual(fields["days"].maximum, 7)
        self.assertEqual(fields["units"].kind, menus.CHOICE)
        self.assertEqual(fields["rain_ok"].kind, menus.BOOLEAN)

    def test_going_ahead_hands_the_answers_on_and_quitting_says_so(self):
        from world import menus

        info = {"input": {"properties": {"city": {"type": "string"}}}}
        got, quit = {}, []
        form = tool_calls.ask_form(["city"], info, on_answered=got.update,
                                   on_quit=lambda: quit.append(True))
        ctx = menus.Context(self.char1, draft={"city": "Lisbon"})
        go = next(item for item in form.items_for(ctx) if item.key == "go")
        go.run(ctx)
        form.on_close(ctx, "finished")
        self.assertEqual(got, {"city": "Lisbon"})
        self.assertEqual(quit, [])
        other = tool_calls.ask_form(["city"], info, on_answered=got.update,
                                    on_quit=lambda: quit.append(True))
        other.on_close(menus.Context(self.char1), "quit")
        self.assertEqual(quit, [True])


# ---------------------------------------------------------------------------
# A model writing it (§7.6)
# ---------------------------------------------------------------------------

@tag("world")
class AModelWritingACall(GameTest):

    def setUp(self):
        super().setUp()
        self.root = self.room1
        self.root.db.is_world_root = True
        self.root.db.world_root = self.root

    def reply(self, effect):
        return {"rules": [{"phase": "carry_out", "scope": "world",
                           "effects": [effect]}]}

    def validate(self, effect):
        from world import rule_gen

        offered = [("world", "everywhere", {"world": True})]
        return rule_gen.validate(self.reply(effect), offered, "sail", self.root)

    def test_a_call_that_can_be_made_is_kept(self):
        with serving():
            kept, said = self.validate(_call(results={"conditions": "state:here"}))
        self.assertEqual(len(kept), 1, said)

    def test_one_that_asks_is_sent_back(self):
        with serving():
            kept, said = self.validate(_call(args={"city": "ask"}))
        self.assertEqual(kept, [])
        self.assertTrue(any("cannot be asked" in line for line in said), said)

    def test_one_naming_no_tool_here_is_sent_back(self):
        with serving():
            kept, said = self.validate(_call("weather.hurricane"))
        self.assertEqual(kept, [])
        self.assertTrue(any("no tool" in line for line in said), said)

    def test_what_it_does_is_never_taken_from_the_model(self):
        with serving():
            kept, _said = self.validate(_call(does="Launches the missiles."))
            filed = R.add(self.root, kept[0])
        self.assertEqual(filed["effects"][0]["does"],
                         "Gets today's forecast for a city.")

    def test_nothing_becoming_true_may_call_out(self):
        """It would be a timer by another name."""
        from world import rule_gen

        with serving():
            kept, said = rule_gen.validate_becoming({"rules": [{
                "when": [{"subject": "here", "is": "dark"}],
                "effects": [_call()]}]}, self.root)
        self.assertEqual(kept, [])
        self.assertTrue(any("call_tool" in line for line in said), said)


@tag("world")
class WhatTheRuleLoopIsShown(GameTest):

    def setUp(self):
        super().setUp()
        self.root = self.room1
        self.root.db.is_world_root = True
        self.root.db.world_root = self.root

    def ctx(self):
        from world import toolbox as tb

        return tb.ToolContext(world_root=self.root, room=self.room1,
                              actor=self.char1)

    def test_nothing_about_tools_where_there_are_none(self):
        from world import lookups, rule_gen

        self.assertEqual(rule_gen._tools_said(), "")
        for tool in lookups.named(*rule_gen.TOOL_LOOKUPS):
            self.assertFalse(tool.offered(self.ctx()), tool.name)

    def test_with_a_service_both_are_there(self):
        from world import lookups, rule_gen

        with serving():
            self.assertIn("call_tool", rule_gen._tools_said())
            tools = {tool.name: tool for tool in lookups.named(*rule_gen.TOOL_LOOKUPS)}
            self.assertTrue(tools["list_tools"].offered(self.ctx()))
            heard = []
            tools["list_tools"].handler(self.ctx(), {}, heard.append)
            tools["show_tool"].handler(self.ctx(), {"tool": "weather.forecast"},
                                       heard.append)
            listed, shown = heard
        self.assertIn("weather.forecast", listed)
        self.assertNotIn("weather.ledger", listed)
        self.assertIn("conditions: one of sunny, rain, storm -- can be a condition",
                      shown)
        self.assertIn("high_c: number -- can be a figure", shown)

    def test_the_becomes_loop_is_never_offered_them(self):
        from world import rule_gen

        for name in rule_gen.TOOL_LOOKUPS:
            self.assertNotIn(name, rule_gen.LOOKUPS)


@tag("world")
class TheRuleLoopFilesACall(GameTest):
    """The whole loop, with the model's answer scripted: offered, sent, filed."""

    def setUp(self):
        super().setUp()
        self.root = self.room1
        self.root.db.is_world_root = True
        self.root.db.world_root = self.root

    def test_a_model_learning_a_verb_can_write_a_rule_that_checks_the_weather(self):
        from tests.support import finishing, replying
        from world import rule_gen

        kept = []
        with serving(), immediately(), replying(finishing(file_rules={"rules": [{
                "phase": "carry_out", "scope": "world", "name": "forecasting",
                "effects": [_call(results={"conditions": "state:here",
                                           "text": "actor"})]}]})) as recorder:
            rule_gen.learn(FakeSponsor(), self.root, "forecast", {}, self.char1,
                           on_success=kept.extend,
                           on_error=lambda err: self.fail(err))
            offered = [tool["function"]["name"] for tool in recorder.tools(0)]
            system = recorder.prompts[0][0]["content"]
        self.assertIn("list_tools", offered)
        self.assertIn("show_tool", offered)
        self.assertIn('"call_tool" asks a service', system)
        filed = [rule for rule in R.all_rules(self.root)
                 if rule.get("action") == "forecast"]
        self.assertEqual(len(filed), 1)
        self.assertEqual(filed[0]["effects"][0]["does"],
                         "Gets today's forecast for a city.")


# ---------------------------------------------------------------------------
# The planner (§9): promises, finding out, and once per goal
# ---------------------------------------------------------------------------

@tag("world")
class PlanningWithTheWeather(_AWorldWithWeather):
    """
    A character wants to sail; sailing needs fair weather here; a forecast
    can find out whether it is. Finding out is a step, never a promise.
    """

    def setUp(self):
        super().setUp()
        from typeclasses.npcs import NPC

        self.room1.key = "Harbour"
        self.boat = create_object("typeclasses.objects.Object", key="Boat",
                                  location=self.room1)
        self.npc = create_object(NPC, key="Mara", location=self.room1)
        actions.declare(self.root, "sail", applies_to=[{"role": "direct"}])
        R.add(self.root, R.blank(
            action="sail", phase=R.CHECK, scope={"world": True},
            name="only in fair weather",
            conditions=[{"subject": "here", "is": ["sunny"]}]))
        R.add(self.root, R.blank(
            action="sail", phase=R.CARRY_OUT, scope={"world": True},
            report="{actor} $pconj(sail).",
            effects=[{"type": "set_state", "role": "direct", "add": ["sailing"]}]))
        self.goal = [{"type": "state", "object": "Boat", "is": ["sailing"]}]
        self.npc.db.goal = self.goal

    def forecast_from(self, city):
        actions.declare(self.root, "forecast")
        R.add(self.root, R.blank(
            action="forecast", phase=R.CARRY_OUT, scope={"world": True},
            report="{actor} $pconj(look) at the sky.",
            effects=[_call(args={"city": f"value:{city}"},
                           results={"conditions": "state:here"})]))

    def move(self):
        from world import planner

        return planner.next_move(self.npc, self.root, self.goal)

    def test_it_checks_the_weather_first(self):
        with serving():
            self.forecast_from("Lisbon")
            self.assertEqual(self.move().action, "forecast")

    def test_and_sails_once_it_knows_it_is_fair(self):
        with serving():
            self.forecast_from("Lisbon")
            self.attempt("forecast", who=self.npc, sponsor=FakeSponsor())
            self.assertIn("sunny", verbs.states(self.room1))
            self.assertEqual(self.move().action, "sail Boat")

    def test_a_storm_means_waiting_not_asking_again_every_turn(self):
        with serving():
            self.forecast_from("Oslo")
            self.attempt("forecast", who=self.npc, sponsor=FakeSponsor())
            self.assertIn("storm", verbs.states(self.room1))
            move = self.move()
        self.assertIsNone(move.action)
        self.assertIsNotNone(move.wait, "a storm is a wait, not a dead end")
        self.assertLessEqual(move.wait, tool_calls.FIND_OUT_EVERY)

    def test_and_looks_again_once_the_wait_is_over(self):
        with serving():
            self.forecast_from("Oslo")
            self.attempt("forecast", who=self.npc, sponsor=FakeSponsor())
            held = dict(self.npc.db.goal_reaching)
            held["found_out"] = {key: when - tool_calls.FIND_OUT_EVERY - 1
                                 for key, when in held["found_out"].items()}
            self.npc.db.goal_reaching = held
            self.assertEqual(self.move().action, "forecast")

    def test_a_forecast_is_never_a_way_of_making_it_fair(self):
        """`call_tool` is not readable backwards: a wish for sun checks nothing."""
        from world import conditions

        effect = _call(results={"conditions": "state:here"})
        self.assertFalse(conditions.achieves(
            effect, {"subject": "here", "is": ["sunny"]}))

    def test_a_new_goal_starts_clean(self):
        with serving():
            self.forecast_from("Oslo")
            self.attempt("forecast", who=self.npc, sponsor=FakeSponsor())
            self.goal = [{"type": "state", "object": "Boat", "is": ["sailing"]},
                         {"type": "state", "object": "Boat", "lacks": ["wet"]}]
            self.npc.db.goal = self.goal
            self.assertEqual(self.move().action, "forecast")


@tag("world")
class ActingOutwardOncePerGoal(_AWorldWithWeather):

    def setUp(self):
        super().setUp()
        from typeclasses.npcs import NPC

        self.letter = create_object("typeclasses.objects.Object", key="Letter",
                                    location=self.room1)
        self.npc = create_object(NPC, key="Mara", location=self.room1)
        self.goal = [{"type": "state", "object": "Letter", "is": ["posted"]}]
        self.npc.db.goal = self.goal

    def post_rule(self, args):
        actions.declare(self.root, "post", applies_to=[{"role": "direct"}])
        R.add(self.root, R.blank(
            action="post", phase=R.CARRY_OUT, scope={"world": True},
            report="{actor} $pconj(post) it.",
            effects=[{"type": "call_tool", "tool": "weather.send_postcard",
                      "args": args, "results": {}},
                     {"type": "set_state", "role": "direct", "add": ["posted"]}]))

    def move(self):
        from world import planner

        return planner.next_move(self.npc, self.root, self.goal)

    def test_what_the_rule_promises_alongside_the_call_is_a_step(self):
        with serving():
            self.post_rule({"to": "value:Ana", "text": "value:hello"})
            self.assertEqual(self.move().action, "post Letter")

    def test_but_once_it_has_acted_for_this_goal_it_is_not_again(self):
        from tests.fixtures import weather_server

        with serving():
            self.post_rule({"to": "value:Ana", "text": "value:hello"})
            self.attempt("post letter", who=self.npc, sponsor=FakeSponsor())
            self.assertEqual(len(weather_server.SENT), 1)
            verbs.apply_states(self.letter, remove=["posted"], world_root=self.root)
            self.assertNotEqual(self.move().action, "post Letter")

    def test_a_call_that_asks_is_never_a_step(self):
        with serving():
            self.post_rule({"to": "ask", "text": "value:hello"})
            self.assertNotEqual(self.move().action, "post Letter")


# ---------------------------------------------------------------------------
# A world as a document: what it needs, and refusing without it (§10)
# ---------------------------------------------------------------------------

from tests.test_exchange import WorldTest  # noqa: E402


@tag("world")
class WhatAWorldNeeds(WorldTest):

    def forecasting(self, root):
        actions.declare(root, "forecast", applies_to=[{"role": "direct",
                                                       "optional": True}])
        return R.add(root, R.blank(
            action="forecast", phase=R.CARRY_OUT, scope={"world": True},
            name="forecasting", report="{actor} $pconj(look) up.",
            effects=[_call(results={"conditions": "state:here"})]))

    def test_a_rule_that_never_fired_is_still_needed(self):
        from world import exchange

        with serving() as record:
            root = self.world()
            self.forecasting(root)
            doc = exchange.document(root)
        self.assertEqual(doc["requires"]["services"], {
            "weather": {"forecast": record["tools"]["forecast"]["fingerprint"]}})

    def test_nothing_about_where_it_is_or_how_to_log_in(self):
        import json

        from world import exchange

        with serving(auth=services.KEY_AUTH, key="sk-should-never-travel",
                     url="http://secret.example/mcp"):
            root = self.world()
            self.forecasting(root)
            text = json.dumps(exchange.document(root))
        self.assertNotIn("sk-should-never-travel", text)
        self.assertNotIn("secret.example", text)

    def test_calls_change_nothing_about_it(self):
        from world import attempt as attempt_mod
        from world import exchange

        with serving():
            root = self.world()
            self.forecasting(root)
            before = exchange.document(root)["requires"]["services"]
            self.char1.move_to(root, quiet=True)
            with immediately():
                attempt_mod.attempt(self.char1, "forecast london",
                                    FakeSponsor(key=""),
                                    on_message=lambda *a, **k: None)
            after = exchange.document(root)["requires"]["services"]
        self.assertEqual(before, after)

    def test_a_world_with_no_calls_needs_nothing(self):
        from world import exchange

        root = self.world()
        self.assertEqual(exchange.document(root)["requires"]["services"], {})

    def test_it_comes_back_on_a_server_that_has_it(self):
        from world import exchange

        with serving():
            root = self.world()
            self.forecasting(root)
            doc = exchange.document(root)
            self.assertEqual(exchange.problems(doc), [])
            new = exchange.build(doc, None, self.char1)
            rules = [r for r in R.all_rules(new) if r.get("action") == "forecast"]
        self.assertEqual(rules[0]["effects"][0]["tool"], "weather.forecast")


@tag("world")
class RefusingAWorldThatCannotWork(WorldTest):
    """§10.3: refused, every problem named, and never a service added."""

    def document(self):
        from world import exchange

        with serving():
            root = self.world()
            actions.declare(root, "forecast")
            R.add(root, R.blank(action="forecast", phase=R.CARRY_OUT,
                                scope={"world": True}, name="forecasting",
                                effects=[_call(args={"city": "value:Oslo"})]))
            return exchange.document(root)

    def problems(self, doc):
        from world import exchange

        return exchange.problems(doc)

    def test_no_such_service(self):
        doc = self.document()
        said = self.problems(doc)
        self.assertTrue(any("does not have" in line for line in said), said)
        self.assertIsNone(services.get("weather"), "a world never adds one")

    def test_no_such_tool(self):
        doc = self.document()
        doc["requires"]["services"]["weather"] = {"hurricane": "sha256:x"}
        with serving():
            said = self.problems(doc)
        self.assertTrue(any("does not offer" in line for line in said), said)

    def test_a_tool_that_takes_different_arguments(self):
        doc = self.document()
        doc["requires"]["services"]["weather"]["forecast"] = "sha256:another"
        with serving():
            said = self.problems(doc)
        self.assertTrue(any("different arguments" in line for line in said), said)

    def test_a_tool_switched_off(self):
        doc = self.document()
        with serving() as record:
            record["tools"]["forecast"]["on"] = False
            services.put(record)
            said = self.problems(doc)
        self.assertTrue(any("switched off" in line for line in said), said)

    def test_and_with_all_of_it_nothing_is_said(self):
        doc = self.document()
        with serving():
            self.assertEqual(self.problems(doc), [])


@tag("world")
class DriftAtRunTime(_AWorldWithWeather):

    def test_rulecheck_names_a_rule_whose_tool_changed(self):
        from world import rulecheck

        with serving():
            filed = self.rule("forecast", [_call(results={"conditions": "state:here"})])
            record = services.get("weather")
            record["tools"]["forecast"]["fingerprint"] = "sha256:changed"
            services.put(record)
            findings = rulecheck.scan(rulecheck.of_world(self.root))
            said = rulecheck.report(findings)
        lost = findings["unreachable_calls"]
        self.assertEqual([(rule_id, tool) for rule_id, tool, _why in lost],
                         [(filed["id"], "weather.forecast")])
        self.assertIn("no longer has", said)

    def test_and_says_nothing_while_it_is_as_it_was(self):
        from world import rulecheck

        with serving():
            self.rule("forecast", [_call(results={"conditions": "state:here"})])
            findings = rulecheck.scan(rulecheck.of_world(self.root))
        self.assertEqual(findings["unreachable_calls"], [])


@tag("world")
class RulesetsThatCall(GameTest):

    def ruleset(self, phase="carry_out", source="word:direct"):
        return {"name": "weatherwise", "means": "Knows the weather.",
                "rules": [{"name": "forecasting", "phase": phase,
                           "action": "forecast",
                           "when": [{"subject": "here", "is": "dark"}]
                           if phase == "becomes" else [],
                           "effects": [_call(args={"city": source})]}]}

    def test_a_well_written_one_has_no_problems(self):
        from world import rulesets

        said = [line for line in rulesets.problems(self.ruleset())
                if "forecast" in line or "call" in line]
        self.assertEqual(said, [])

    def test_a_source_that_does_not_read(self):
        from world import rulesets

        said = rulesets.problems(self.ruleset(source="smell:direct"))
        self.assertTrue(any("does not read" in line for line in said), said)

    def test_calling_out_when_something_becomes_true(self):
        from world import rulesets

        said = rulesets.problems(self.ruleset(phase="becomes"))
        self.assertTrue(any("timer" in line for line in said), said)

    def test_switched_on_only_where_the_service_is(self):
        from world import rulesets

        with mock.patch.object(rulesets, "get", return_value=self.ruleset()):
            self.assertTrue(rulesets.services_lacking("weatherwise"))
            with serving():
                self.assertEqual(rulesets.services_lacking("weatherwise"), [])


@tag("world")
class OptionalArgumentsInARule(_AWorldWithWeather):
    """A rule may fill an `X | None` parameter, and is told why not otherwise."""

    def search(self, **args):
        return {"type": "call_tool", "tool": "weather.search",
                "args": {"query": "word:direct", **args},
                "results": {"text": "actor"}}

    def test_a_fixed_list_of_domains_reaches_the_tool(self):
        with serving():
            self.rule("search", [self.search(
                include_domains="value:github.com docs.python.org",
                time_relative="value:week")])
            mine, _theirs = self.attempt("search mud")
        self.assertIn("mud|['github.com', 'docs.python.org']|week", mine)

    def test_one_no_rule_can_give_is_refused_with_the_reason(self):
        with serving():
            said = tool_calls.complaints(self.search(tuning="value:x"))
        self.assertTrue(any("cannot be given by a rule" in line for line in said),
                        said)
