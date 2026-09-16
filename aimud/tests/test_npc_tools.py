"""
A character's tools: what it is offered, and what happens when it uses them.

Phase 2 of docs/generator-tool-loops.md. Every argument that must name
something here is closed to what is here, and each tool is told what matters
about this moment -- whose things are, where they sit, the terms of a request
waiting on an answer -- because a description written once for every room is
a description filled in from whatever the model half-remembers.
"""

from unittest import mock

from django.test import tag
from evennia import create_object

from tests.base import GameTest
from tests.support import FakeSponsor, immediately, replying, tool_call, tool_reply
from world import effects, npc_gen, ownership, quests, token_lists, verbs


class _Scene(GameTest):
    """A world, a character in it, and a letter in an open tray."""

    def setUp(self):
        super().setUp()
        self.room1.db.world_root = self.room1
        self.room1.db.is_world_root = True
        self.room1.db.is_ai_room = True

        from typeclasses.npcs import NPC

        self.npc = create_object(NPC, key="Bram", location=self.room1)
        self.tray = create_object("typeclasses.objects.Object", key="tray",
                                  location=self.room1)
        self.letter = create_object("typeclasses.objects.Object",
                                    key="letter", location=self.tray)
        self.letter.db.relation = "in"

    def offered(self):
        return {tool["function"]["name"]: tool["function"]
                for tool in npc_gen._tools_for(self.npc, self.room1)}

    def choices(self, tool, argument):
        return self.offered()[tool]["parameters"]["properties"][argument].get(
            "enum")


@tag("world")
class WhatACharacterIsOffered(_Scene):
    characters = 2
    loose_objects = 2
    second_room = True

    def test_get_reaches_into_an_open_tray(self):
        self.assertIn("letter", self.choices("get", "object_name"))
        self.assertIn("letter (in tray, nobody's)",
                      self.offered()["get"]["description"])

    def test_get_says_whose_each_thing_is(self):
        ownership.set_owner(self.obj1, self.char1)
        self.assertIn(f"{self.obj1.key} ({ownership.owner_name(self.obj1)}'s)",
                      self.offered()["get"]["description"])

    def test_say_can_be_to_somebody_here(self):
        self.assertIn(self.char1.get_display_name(self.npc),
                      self.choices("say", "to"))

    def test_with_nobody_here_say_offers_nobody_to_say_it_to(self):
        for person in (self.char1, self.char2):
            person.location = self.room2
        say = self.offered()["say"]
        self.assertNotIn("to", say["parameters"]["properties"])
        self.assertNotIn("check_traits", self.offered())

    def test_sizing_up_needs_a_person_and_may_be_oneself(self):
        check = self.offered()["check_traits"]
        self.assertEqual(check["parameters"]["required"], ["person"])
        self.assertIn("myself",
                      check["parameters"]["properties"]["person"]["enum"])

    def test_an_offer_is_bounded_and_knows_what_there_is_to_give(self):
        offer = self.offered()["offer_quest"]
        deadline = offer["parameters"]["properties"]["time_limit_seconds"]
        self.assertEqual(deadline["minimum"], quests.MIN_TIME_LIMIT)
        self.assertEqual(deadline["maximum"], quests.MAX_TIME_LIMIT)
        self.assertIn("carrying nothing", offer["description"])

        self.obj2.location = self.npc
        self.assertIn(f"You are carrying {self.obj2.key}",
                      self.offered()["offer_quest"]["description"])

    def test_answering_a_request_is_told_its_terms(self):
        quests.offer(self.char1, self.npc, title="Fetch the obj",
                     description="bring me the obj",
                     conditions=[{"type": "holds", "object": self.obj1.key}],
                     reward=[{"type": "create_object",
                              "name": "a brass compass", "location": "actor"}],
                     time_limit=600)
        said = self.offered()["answer_quest"]["description"]
        self.assertIn("bring me the obj", said)
        self.assertIn("a brass compass", said)
        self.assertIn("within", said)

    def test_attempt_names_what_this_world_already_knows(self):
        self.room1.db.verb_rules = {"polish#thing": {"valid": True}}
        said = self.offered()["attempt"]["description"]
        self.assertIn("polish", said)
        self.assertIn("wear", said, "the verbs the game itself handles")

    def test_and_the_prompt_no_longer_carries_them(self):
        self.room1.db.verb_rules = {"polish#thing": {"valid": True}}
        got = []
        with immediately(), \
                replying(tool_reply(tool_call("say", message="Morning."))) as asked, \
                mock.patch("world.npc_gen._memory_inputs",
                           return_value=("(no prior events)", "bank", [], [])), \
                mock.patch("world.memory.recall_for_cues", return_value=[]), \
                mock.patch("world.memory.format_recalled", return_value=""):
            npc_gen.generate_npc_reaction(FakeSponsor(), self.npc, self.room1,
                                          on_success=got.append,
                                          on_error=got.append)
            npc_gen.generate_npc_idle(FakeSponsor(), self.npc, self.room1,
                                      on_success=got.append,
                                      on_error=got.append)
        self.assertEqual(got, [{"say": 1}] * 2)
        system = asked.prompts[0][0]["content"]
        self.assertNotIn("Actions this world already understands", system)
        self.assertIn("How do you respond?", asked.sent(0))
        self.assertIn("act of your own accord", asked.sent(1))
        names = {tool["function"]["name"] for tool in asked.tools(0)}
        self.assertIn("attempt", names)


@tag("world")
class WhatACharacterDoes(_Scene):

    def test_it_takes_the_letter_out_of_the_tray(self):
        self.npc._execute_one("get", {"object_name": "letter"}, self.room1)
        self.assertIs(self.letter.location, self.npc)

    def test_saying_something_to_somebody_addresses_them(self):
        with mock.patch.object(self.npc, "_notify_other_npcs") as told:
            self.npc._execute_one("say", {"message": "Pass the salt.",
                                          "to": self.char1.key}, self.room1)
        addressed = told.call_args.kwargs["addressed"]
        self.assertIn(f"#{self.char1.id}", [entry[1] for entry in addressed])

    def test_no_more_than_three_things_in_one_turn(self):
        done = []
        with mock.patch.object(self.npc, "_execute_one",
                               lambda name, *args: done.append(name)):
            self.npc._execute_tool_calls(
                [{"name": "say", "args": {}}] * 5
                + [{"name": "check_traits", "args": {}}])
        self.assertEqual(done, ["say", "say", "say", "check_traits"])
        self.assertFalse(self.npc.ndb.reacting)


@tag("world")
class ChangingAThing(_Scene):
    """`modify`, held to the rules every generated name is held to."""

    loose_objects = 1

    def modify(self, **args):
        self.npc._execute_one("modify", {"object_name": self.obj1.key, **args},
                              self.room1)

    def last_note(self):
        return (self.npc.db.action_history or [{}])[-1].get("text", "")

    def test_a_name_that_carries_a_condition_is_refused(self):
        verbs.register_state(self.room1, "tarnished", means="dulled with age")
        before = self.obj1.key
        self.modify(new_name="tarnished key")
        self.assertEqual(self.obj1.key, before)
        self.assertIn("tarnished", self.last_note())

    def test_a_description_asking_for_a_list_nobody_keeps_is_refused(self):
        self.modify(new_description="It smells of {smell}.")
        self.assertNotIn("{smell}", self.obj1.db.desc or "")
        self.assertIn("{smell}", self.last_note())

    def test_but_one_this_world_keeps_is_fine(self):
        token_lists.register(self.room1, "smell", {
            "means": "what a thing smells of", "entries": ["tar", "brine"]})
        self.modify(new_description="It smells of {smell}.")
        self.assertEqual(self.obj1.db.desc, "It smells of {smell}.")

    def test_a_check_rule_saying_no_is_honoured(self):
        before = self.obj1.key
        with mock.patch("world.attempt.permitted",
                        return_value="You may not change that."):
            self.modify(new_name="brass key")
        self.assertEqual(self.obj1.key, before)
        self.assertIn("may not change that", self.last_note())

    def test_nothing_to_change_it_to_changes_nothing(self):
        before = self.obj1.key
        self.modify()
        self.assertEqual(self.obj1.key, before)

    def test_a_rename_is_seen_and_the_old_name_still_finds_it(self):
        old = self.obj1.key
        heard = []
        self.char1.msg = lambda text="", **kwargs: heard.append(str(text))
        self.modify(new_name="brass key")

        self.assertEqual(self.obj1.key, "brass key")
        self.assertIn(old.lower(), self.obj1.aliases.all())
        self.assertTrue(any("brass key" in line for line in heard), heard)
        self.assertIn("brass key", self.last_note())

    def test_a_rules_effect_is_held_to_the_same_naming_rule(self):
        verbs.register_state(self.room1, "tarnished", means="dulled with age")
        before = self.obj1.key
        effects.apply(self.char1, self.room1,
                      [{"type": "modify_object", "name": self.obj1.key,
                        "new_name": "tarnished key"}],
                      world_root=self.room1)
        self.assertEqual(self.obj1.key, before)

    def test_and_one_that_passes_still_changes_the_thing(self):
        effects.apply(self.char1, self.room1,
                      [{"type": "modify_object", "name": self.obj1.key,
                        "new_name": "brass key"}],
                      world_root=self.room1)
        self.assertEqual(self.obj1.key, "brass key")


_NO_MEMORY = (
    ("world.npc_gen._memory_inputs", ("(no prior events)", "bank", [], [])),
    ("world.memory.recall_for_cues", []),
    ("world.memory.format_recalled", ""),
)


@tag("world")
class ATurnThatGoesRound(_Scene):
    """
    Phase 3: a character's turn is a loop, so what it looks up it can act on
    at once, and what it is refused comes back as the tool's answer.
    """

    loose_objects = 1

    def turn(self, *replies, idle=False):
        from contextlib import ExitStack

        got = []
        with ExitStack() as stack:
            stack.enter_context(immediately())
            asked = stack.enter_context(replying(*replies))
            for target, value in _NO_MEMORY:
                stack.enter_context(mock.patch(target, return_value=value))
            begin = (npc_gen.generate_npc_idle if idle
                     else npc_gen.generate_npc_reaction)
            begin(FakeSponsor(), self.npc, self.room1,
                  on_success=got.append, on_error=got.append)
        return got, asked

    def said(self):
        return [entry.get("text") for entry in self.npc.db.action_history or []
                if entry.get("type") == "say"]

    def test_sizing_somebody_up_and_answering_them_is_one_turn(self):
        who = self.char1.get_display_name(self.npc)
        got, asked = self.turn(
            tool_reply(tool_call("check_traits", person=who)),
            tool_reply(tool_call("say", message="You look well.")))
        self.assertEqual(asked.count, 2)
        # Whatever sizing them up finds -- the test characters have nothing
        # measurable about them -- is what the model is told, straight away.
        self.assertEqual(asked.tool_results(1)[0]["content"],
                         self.npc._sized_up(who, self.room1))
        self.assertEqual(self.said(), ["You look well."])
        self.assertEqual(got, [{"check_traits": 1, "say": 1}])

    def test_a_turn_that_only_acts_is_one_call(self):
        _got, asked = self.turn(tool_reply(tool_call("say", message="Morning.")))
        self.assertEqual(asked.count, 1)
        self.assertEqual(self.said(), ["Morning."])

    def test_what_a_tool_was_refused_is_its_answer(self):
        verbs.register_state(self.room1, "tarnished", means="dulled with age")
        box = npc_gen._toolbox_for(self.npc, self.room1)
        got = []
        box.run(tool_call("modify", object_name=self.obj1.key,
                          new_name="tarnished key"), got.append)
        self.assertIn("tarnished", got[0])
        self.assertIsNone(self.npc.ndb.noticing)

    def test_three_things_a_turn_holds_across_rounds(self):
        box = npc_gen._toolbox_for(self.npc, self.room1)
        got = []
        for line in range(4):
            box.run(tool_call("say", message=f"line {line}"), got.append)
        self.assertIn("enough for one turn", got[3])
        self.assertEqual(len(self.said()), 3)

    def test_the_guard_is_released_when_the_turn_is_over(self):
        from contextlib import ExitStack

        with ExitStack() as stack:
            stack.enter_context(immediately())
            stack.enter_context(replying(tool_reply(tool_call("say",
                                                              message="Hm."))))
            for target, value in _NO_MEMORY:
                stack.enter_context(mock.patch(target, return_value=value))
            stack.enter_context(mock.patch.object(self.npc, "_sponsor",
                                                  return_value=FakeSponsor()))
            stack.enter_context(mock.patch("world.activity.npc_may_act",
                                           return_value=True))
            self.npc._trigger_reaction()
        self.assertFalse(self.npc.ndb.reacting)
        self.assertEqual(self.said(), ["Hm."])

    def test_a_character_may_look_things_up_as_well_as_act(self):
        """Phase 4: the first lookups a character is offered."""
        names = {tool.name for tool in
                 npc_gen._toolbox_for(self.npc, self.room1).tools}
        self.assertLessEqual({"examine", "list_known_verbs", "world_faults"},
                             names)
        with mock.patch("world.memory.available", return_value=False):
            names = {tool.name for tool in
                     npc_gen._toolbox_for(self.npc, self.room1).tools}
        self.assertNotIn("recall", names, "no memory to search, no tool")
