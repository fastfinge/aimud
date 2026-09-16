"""
Counting the rounds each job's conversations take, and reading them back.

Phase 3 of docs/generator-tool-loops.md. The budgets are set from these at the
soak, so what is added up, and what `rounds clear` leaves alone, is held still
here.
"""

from unittest import mock

from django.test import tag

from tests.base import GameCommandTest, GameTest
from commands.account_cmds import CmdRounds
from tests.support import FakeSponsor, immediately, replying, tool_call, tool_reply
from world import ledger, llm
from world import toolbox as tb
from world.model_params import ModelChoice
from world.sponsor import Sponsor


def loop(rounds=2, outcome="accepted", complaints=0, seconds=4.0, tools=None,
         limit=8):
    return {"rounds": rounds, "limit": limit, "outcome": outcome,
            "complaints": complaints, "seconds": seconds,
            "tools": tools or {}}


class _Paying:

    def paying(self):
        self.room1.db.world_root = self.room1
        self.sponsor = Sponsor(world_root=self.room1, account=self.account,
                               actor=self.char1)
        self.dialogue = ModelChoice("m", {}, job="dialogue")
        self.commands = ModelChoice("m", {}, job="commands")


@tag("world")
class AddingUpLoops(_Paying, GameTest):
    accounts = True

    def setUp(self):
        super().setUp()
        self.paying()

    def test_each_job_is_added_up(self):
        ledger.note_loop(self.sponsor, self.dialogue,
                         loop(rounds=2, tools={"examine": 1}))
        ledger.note_loop(self.sponsor, self.dialogue,
                         loop(rounds=3, outcome="forced", complaints=2,
                              tools={"examine": 2, "recall": 1}))
        row = ledger.loops(self.account)["dialogue"]
        self.assertEqual(row["loops"], 2)
        self.assertEqual(row["rounds"], 5)
        self.assertEqual(row["most_rounds"], 3)
        self.assertEqual(row["forced"], 1)
        self.assertEqual(row["complaints"], 2)
        self.assertEqual(row["tools"], {"examine": 3, "recall": 1})
        self.assertAlmostEqual(row["seconds"], 8.0)

    def test_and_each_world_on_its_own(self):
        ledger.note_loop(self.sponsor, self.commands, loop())
        self.assertEqual(
            ledger.loops(self.account, self.room1.id)["commands"]["loops"], 1)
        self.assertEqual(ledger.loops(self.account, 999999), {})

    def test_a_loop_nobody_paid_for_is_not_counted(self):
        ledger.note_loop(Sponsor(world_root=self.room1), self.dialogue, loop())
        self.assertEqual(ledger.loops(self.account), {})

    def test_clearing_them_leaves_what_was_spent(self):
        ledger.note(self.sponsor, self.dialogue,
                    {"prompt_tokens": 5, "completion_tokens": 2}, 1.0)
        ledger.note_loop(self.sponsor, self.dialogue, loop())
        ledger.forget_loops(self.account)
        self.assertEqual(ledger.loops(self.account), {})
        self.assertEqual(ledger.totals(self.account)["calls"], 1)

    def test_a_removed_world_takes_its_rounds_with_it(self):
        ledger.note_loop(self.sponsor, self.commands, loop())
        ledger.forget_world(self.account, self.room1.id)
        self.assertEqual(ledger.loops(self.account, self.room1.id), {})
        self.assertEqual(ledger.loops(self.account)["commands"]["loops"], 1)

    def test_nonsense_never_raises(self):
        ledger.note_loop(self.sponsor, self.dialogue, {"rounds": "many",
                                                       "tools": "none"})
        ledger.note_loop(None, self.dialogue, loop())


@tag("unit")
class ALoopReportsItself(GameTest):

    def test_converse_hands_its_figures_to_the_ledger(self):
        def answer(ctx, args, done):
            done(tb.accept(args.get("n")))

        box = tb.Toolbox([tb.Tool("answer", "", None, answer, finishes=True)])
        with immediately(), \
                replying(tool_reply(tool_call("answer", n=1))), \
                mock.patch("world.ledger.note_loop") as noted:
            llm.converse(FakeSponsor(), ModelChoice("m", job="quests"), [],
                         box, on_done=lambda value: None,
                         on_error=lambda why: None, rounds=4)
        figures = noted.call_args.args[2]
        self.assertEqual(figures["rounds"], 1)
        self.assertEqual(figures["limit"], 4)
        self.assertEqual(figures["outcome"], "accepted")
        self.assertEqual(figures["tools"], {"answer": 1})


@tag("world")
class TheRoundsCommand(_Paying, GameCommandTest):
    accounts = True

    def setUp(self):
        super().setUp()
        self.paying()

    def test_with_nothing_counted_it_says_so(self):
        self.assertIn("No conversations", self.call(CmdRounds(), ""))

    def test_one_line_per_job_with_the_count_first(self):
        ledger.note_loop(self.sponsor, self.dialogue, loop(rounds=2))
        ledger.note_loop(self.sponsor, self.dialogue,
                         loop(rounds=3, outcome="forced"))
        ledger.note_loop(self.sponsor, self.commands, loop(rounds=1))
        said = self.call(CmdRounds(), "")
        self.assertIn("dialogue: 2 conversations, 2.5 rounds on average, 3 at "
                      "most, budget 8, 1 made to answer, 4 seconds on average.",
                      said)
        self.assertLess(said.index("dialogue"), said.index("commands"))

    def test_one_job_in_full(self):
        ledger.note_loop(self.sponsor, self.dialogue,
                         loop(complaints=3, tools={"examine": 2, "recall": 1}))
        said = self.call(CmdRounds(), "dialogue")
        self.assertIn("3 answers sent back", said)
        self.assertIn("examine 2 times, recall 1 time", said)

    def test_a_job_nothing_has_counted(self):
        self.assertIn("No conversations have been counted for rooms",
                      self.call(CmdRounds(), "rooms"))

    def test_clear(self):
        ledger.note_loop(self.sponsor, self.dialogue, loop())
        self.call(CmdRounds(), "clear")
        self.assertEqual(ledger.loops(self.account), {})

    def test_a_world_number_that_does_not_exist(self):
        self.assertIn("Give a world's number",
                      self.call(CmdRounds(), "world 7"))
