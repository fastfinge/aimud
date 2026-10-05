"""
Memory's model calls on tools: the last part of phase 7 of
docs/archived/generator-tool-loops.md.

Distilling facts answers through `record_facts`. `remember` has no finish
tool -- a player is answered in prose -- and is offered `recall`, so a
question the first memories only half answer can be asked again in other
words.
"""

from unittest import mock

from django.test import tag

from tests.base import GameTest
from tests.support import FakeSponsor, finishing, immediately, replying
from world import fact_gen
from world import toolbox as tb


@tag("world")
class DistillingFacts(GameTest):

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
class WhoPaysForDistilling(GameTest):
    """
    The real `_account_for`, which every other test here replaces. It returned
    an account where a sponsor was wanted, and nothing here could see it.
    """

    accounts = True

    def setUp(self):
        super().setUp()
        from types import SimpleNamespace

        from world import sponsor

        self.room1.db.is_world_root = True
        self.room1.db.world_root = self.room1
        self.account.db.openrouter_api_key = "sk-test"
        sponsor.claim(self.room1, self.account)
        self.where = SimpleNamespace(bank=f"aimud-world-{self.room1.id}")

    def test_the_creator_pays_through_a_sponsor(self):
        found = fact_gen._account_for(self.where)
        self.assertEqual(found.payer, self.account)
        self.assertEqual(found.key(), "sk-test")

    def test_a_shared_world_waits_for_its_creator(self):
        self.room1.db.shared = True
        self.assertIsNone(fact_gen._account_for(self.where))

    def test_and_a_world_whose_maker_has_gone_is_nobody_else_s_to_pay_for(self):
        from types import SimpleNamespace

        self.account2.db.openrouter_api_key = "sk-somebody-else"
        self.assertIsNone(fact_gen._account_for(
            SimpleNamespace(bank="aimud-world-999999")))

    def test_a_bank_nobody_can_pay_for_does_not_stop_the_rest(self):
        from types import SimpleNamespace

        stored = []

        def distillable(where, callback):
            callback(["I helped Bram mend the well."], 7)

        def store_facts(where, facts, through, on_done=None):
            stored.append(where.bank)
            if on_done:
                on_done(len(facts))

        unpaid = SimpleNamespace(bank="aimud-world-999999")
        with immediately(),                 replying(finishing(record_facts={"facts": ["Bram is grateful"]})),                 mock.patch("world.activity.quiet_enough_for_heavy_work",
                           return_value=True),                 mock.patch("world.memory.distillable", distillable),                 mock.patch("world.memory.store_facts", store_facts),                 mock.patch.object(fact_gen, "_world_of",
                                  return_value=self.room1):
            fact_gen.distil(banks=[unpaid, self.where])
        self.assertEqual(stored, [self.where.bank])


@tag("world")
class Remembering(GameTest):

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
