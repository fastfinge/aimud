"""
Quests and goals on finish tools: the second part of phase 7 of
docs/generator-tool-loops.md.

A request becomes a quest, and a want becomes a goal, through `write_quest`
and `write_goal`. What `goals.sanitise` used to drop after the answer was
taken -- leaving a quest that could never be finished, logged and forgotten --
is sent back instead, and so is a trait nothing measures.
"""

from django.test import tag
from evennia import create_object
from evennia.utils.test_resources import EvenniaTest

from tests.support import (FakeSponsor, finishing, immediately, replying,
                           tool_call, tool_reply)
from world import quest_gen, traits

KEY = [{"type": "holds", "object": "brass key"}]
QUEST = {"title": "Fetch the key", "goal": KEY, "reward": [],
         "punishment": []}


def _offered(recorder, index, name):
    for schema in recorder.tools(index) or ():
        if schema["function"]["name"] == name:
            return schema["function"]
    return None


def _results(recorder, index):
    return "\n".join(message["content"]
                     for message in recorder.tool_results(index))


class _World(EvenniaTest):

    def setUp(self):
        super().setUp()
        from typeclasses.npcs import NPC

        self.root = self.room1
        self.root.db.world_root = self.root
        self.root.db.is_world_root = True
        self.bram = create_object(NPC, key="Bram", location=self.root)

    def quest(self, *replies):
        got, failed = [], []
        with immediately(), replying(*replies) as recorder:
            quest_gen.formalise(FakeSponsor(), self.bram, self.char1,
                                "fetch me the key", "a coin", "",
                                on_success=got.append, on_error=failed.append)
        self.assertEqual(failed, [])
        return (got[0] if got else None), recorder

    def goal(self, *replies):
        got, failed = [], []
        with immediately(), replying(*replies) as recorder:
            quest_gen.formalise_goal(FakeSponsor(), self.bram,
                                     "to have the key",
                                     on_success=got.append,
                                     on_error=failed.append)
        self.assertEqual(failed, [])
        return (got[0] if got else None), recorder


@tag("world")
class WritingAQuest(_World):

    def test_a_request_becomes_a_quest(self):
        got, recorder = self.quest(finishing(write_quest=QUEST))
        self.assertEqual(got["title"], "Fetch the key")
        self.assertEqual(got["goal"], KEY)
        self.assertEqual(recorder.count, 1)

    def test_a_goal_nothing_can_test_is_sent_back(self):
        got, recorder = self.quest(
            tool_reply(tool_call("write_quest", **dict(
                QUEST, goal=[{"type": "impress", "object": "Bram"}]))),
            tool_reply(tool_call("write_quest", **QUEST)))
        self.assertIn("cannot be tested", _results(recorder, 1))
        self.assertEqual(got["goal"], KEY)

    def test_a_quest_with_no_goal_is_sent_back(self):
        _got, recorder = self.quest(
            tool_reply(tool_call("write_quest", **dict(QUEST, goal=[]))),
            tool_reply(tool_call("write_quest", **QUEST)))
        self.assertIn("at least one condition", _results(recorder, 1))

    def test_a_trait_nothing_measures_is_sent_back(self):
        _got, recorder = self.quest(
            tool_reply(tool_call("write_quest", **dict(
                QUEST, goal=[{"type": "trait", "trait": "zorbitude",
                              "min": 3}]))),
            tool_reply(tool_call("write_quest", **QUEST)))
        self.assertIn("zorbitude", _results(recorder, 1))

    def test_a_reward_nothing_can_apply_is_sent_back(self):
        _got, recorder = self.quest(
            tool_reply(tool_call("write_quest", **dict(
                QUEST, reward=[{"type": "bestow_luck"},
                               {"type": "set_trait", "role": "actor",
                                "trait": "zorbitude", "change": 2}]))),
            tool_reply(tool_call("write_quest", **QUEST)))
        said = _results(recorder, 1)
        self.assertIn("bestow_luck", said)
        self.assertIn("zorbitude", said)

    def test_rounds_out_offers_the_last_quest_as_it_stands(self):
        untestable = dict(QUEST, goal=[{"type": "impress", "object": "Bram"}])
        got, recorder = self.quest(finishing(write_quest=untestable))
        self.assertEqual(recorder.count, quest_gen.QUEST_ROUNDS)
        self.assertEqual(got["goal"], untestable["goal"])

    def test_the_trait_register_is_looked_up_rather_than_pasted_in(self):
        traits.register(self.root, "zorbcraft", means="the craft of zorbs")
        _got, recorder = self.quest(finishing(write_quest=QUEST))
        self.assertIsNotNone(_offered(recorder, 0, "list_traits"))
        self.assertNotIn("the craft of zorbs", recorder.sent(0))


@tag("world")
class WritingAGoal(_World):

    def test_a_want_becomes_conditions(self):
        got, _recorder = self.goal(finishing(write_goal={"goal": KEY}))
        self.assertEqual(got, KEY)

    def test_nothing_that_can_be_put_this_way_is_a_real_answer(self):
        got, recorder = self.goal(finishing(write_goal={"goal": []}))
        self.assertEqual(got, [])
        self.assertEqual(recorder.count, 1)

    def test_a_condition_nothing_can_test_is_sent_back(self):
        got, recorder = self.goal(
            tool_reply(tool_call("write_goal", goal=KEY + [{"type": "dance"}])),
            tool_reply(tool_call("write_goal", goal=KEY)))
        self.assertIn("1 of the goal's conditions cannot be tested",
                      _results(recorder, 1))
        self.assertEqual(got, KEY)
