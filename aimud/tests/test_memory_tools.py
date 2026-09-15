"""
Memory's model calls on tools: the last part of phase 7 of
docs/generator-tool-loops.md.

Distilling facts answers through `record_facts`. `remember` has no finish
tool -- a player is answered in prose -- and is offered `recall`, so a
question the first memories only half answer can be asked again in other
words.
"""

from unittest import mock

from django.test import tag
from evennia.utils.test_resources import EvenniaTest

from tests.support import FakeSponsor, finishing, immediately, replying
from world import fact_gen
from world import toolbox as tb


@tag("world")
class DistillingFacts(EvenniaTest):

    def test_too_many_facts_are_sent_back(self):
        tool = fact_gen.facts_tool()
        said = []
        tool.handler(tb.ToolContext(),
                     {"facts": [f"fact {n}" for n in range(fact_gen.MAX_FACTS + 1)]},
                     said.append)
        self.assertIsInstance(said[0], tb.Complaint)
        tool.handler(tb.ToolContext(), {"facts": ["Bram owes me a favour"]},
                     said.append)
        self.assertIsInstance(said[1], tb.Accepted)

    def test_a_stretch_of_summaries_becomes_what_they_know(self):
        stored = []

        def distillable(where, callback):
            callback(["I helped Bram mend the well, and he thanked me."], 7)

        def store_facts(where, facts, through, on_done=None):
            stored.append((facts, through))
            if on_done:
                on_done(len(facts))

        tallies = []
        with immediately(), \
                replying(finishing(record_facts={
                    "facts": ["Bram owes me a favour", "Bram owes me a favour"]})) \
                as recorder, \
                mock.patch("world.activity.quiet_enough_for_heavy_work",
                           return_value=True), \
                mock.patch("world.memory.distillable", distillable), \
                mock.patch("world.memory.store_facts", store_facts), \
                mock.patch.object(fact_gen, "_account_for",
                                  return_value=FakeSponsor()):
            fact_gen.distil(banks=["bram"], on_done=tallies.append)
        self.assertEqual(stored, [(["Bram owes me a favour"], 7)])
        self.assertEqual(tallies, [{"characters": 1, "facts": 1}])
        self.assertEqual(recorder.count, 1)


@tag("world")
class Remembering(EvenniaTest):

    def remember(self, question, *replies):
        from commands.memory_cmds import CmdRemember

        command = CmdRemember()
        command.caller = self.char1
        command.args = f" {question}"
        with immediately(), replying(*replies) as recorder, \
                mock.patch("commands.memory_cmds._sponsor_for",
                           return_value=FakeSponsor()), \
                mock.patch("world.memory.available", return_value=True), \
                mock.patch("world.memory.where_for", return_value="bank"), \
                mock.patch("world.memory.recall_rows_sync",
                           return_value=[{"text": "met Bram"}]), \
                mock.patch("world.memory.format_recalled",
                           return_value="- A week ago: you met Bram at the "
                                        "well."), \
                mock.patch.object(self.char1, "msg") as msg:
            command.func()
        said = "\n".join(str(call.args[0]) for call in msg.call_args_list
                         if call.args)
        return said, recorder

    def test_the_answer_is_prose_and_nothing_is_forced(self):
        said, recorder = self.remember(
            "have I met Bram?", "You met Bram at the well, a week ago.")
        self.assertIn("You met Bram at the well", said)
        self.assertIsNone(recorder.tool_choice(0))
        self.assertIn("you met Bram at the well", recorder.sent(0))
        self.assertFalse(self.char1.ndb.recalling)

    def test_a_failure_says_so_and_lets_go(self):
        from world import llm

        said, _recorder = self.remember("have I met Bram?",
                                        llm.LLMError("no route to host"))
        self.assertIn("cannot gather your thoughts", said)
        self.assertIn("no route to host", said)
        self.assertFalse(self.char1.ndb.recalling)
