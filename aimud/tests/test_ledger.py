"""
Counting what was spent, before anything is wired up to spend it.

The arithmetic and the trimming, tested on their own. What a real reply's
`usage` block looks like is `world.llm`'s problem and is held still there; what
is here is that a total only ever goes up, that the tail stays short, and that
a ledger cannot break the turn that was waiting on the call it is recording.
"""

from django.test import tag

from tests.base import GameTest
from world import ledger
from world.model_params import ModelChoice
from world.sponsor import Sponsor


def usage(prompt=10, completion=5):
    return {"prompt_tokens": prompt, "completion_tokens": completion}


@tag("world")
class WhatACallCost(GameTest):
    accounts = True

    def setUp(self):
        super().setUp()
        self.root = self.room1
        self.room1.db.world_root = self.root
        self.model = ModelChoice("test/model", {}, job="commands")
        self.sponsor = Sponsor(world_root=self.root, account=self.account,
                               actor=self.char1)

    def test_a_call_is_counted(self):
        ledger.note(self.sponsor, self.model, usage())
        totals = ledger.totals(self.account)
        self.assertEqual(totals["calls"], 1)
        self.assertEqual(totals["prompt"], 10)
        self.assertEqual(totals["completion"], 5)

    def test_totals_accumulate(self):
        for _ in range(3):
            ledger.note(self.sponsor, self.model, usage())
        self.assertEqual(ledger.totals(self.account)["calls"], 3)
        self.assertEqual(ledger.totals(self.account)["prompt"], 30)

    def test_it_says_what_the_call_was_for(self):
        """
        The job rides on the model choice, which is the only place it is known.
        Without it every entry would say a model was used, which nobody needs
        telling.
        """
        ledger.note(self.sponsor, self.model, usage())
        self.assertEqual(
            ledger.totals(self.account)["by_job"]["commands"]["calls"], 1)

    def test_and_which_world_it_was_for(self):
        ledger.note(self.sponsor, self.model, usage())
        by_world = ledger.totals(self.account)["by_world"]
        self.assertEqual(by_world[str(self.root.id)]["prompt"], 10)

    def test_and_who_caused_it(self):
        """
        The field that only matters once worlds are shared, and the only one
        that cannot be recovered afterwards.
        """
        ledger.note(self.sponsor, self.model, usage())
        self.assertEqual(ledger.recent(self.account)[0]["actor"],
                         self.char1.key)

    def test_a_call_nobody_paid_for_is_not_recorded(self):
        """A sponsor with no account never reached a service to begin with."""
        ledger.note(Sponsor(world_root=self.root), self.model, usage())
        self.assertEqual(ledger.totals(self.account)["calls"], 0)

    def test_the_tail_stays_short(self):
        for _ in range(ledger.RECENT + 10):
            ledger.note(self.sponsor, self.model, usage())
        self.assertEqual(len(ledger.recent(self.account)), ledger.RECENT)
        self.assertEqual(ledger.totals(self.account)["calls"],
                         ledger.RECENT + 10)

    def test_recent_is_newest_first(self):
        ledger.note(self.sponsor, ModelChoice("a", job="first"), usage())
        ledger.note(self.sponsor, ModelChoice("b", job="second"), usage())
        self.assertEqual(ledger.recent(self.account)[0]["job"], "second")

    def test_a_provider_that_names_its_tokens_differently_still_counts(self):
        ledger.note(self.sponsor, self.model,
                    {"input_tokens": 7, "output_tokens": 3})
        self.assertEqual(ledger.totals(self.account)["prompt"], 7)

    def test_a_reply_with_no_usage_is_still_a_call(self):
        """
        The count is what an audit reads first, and a provider that reports no
        tokens must not make calls invisible.
        """
        ledger.note(self.sponsor, self.model, None)
        self.assertEqual(ledger.totals(self.account)["calls"], 1)
        self.assertEqual(ledger.totals(self.account)["prompt"], 0)

    def test_it_never_raises(self):
        """
        The money is already spent by the time this runs. Losing the record is
        bad; losing the answer the player was waiting for is worse.
        """
        ledger.note(self.sponsor, self.model, "not a usage block")
        ledger.note(None, self.model, usage())

    def test_removing_a_world_keeps_the_lifetime_total(self):
        """
        Money spent is spent. A figure that goes down when a world is deleted
        is a figure nobody can reconcile against a bill.
        """
        ledger.note(self.sponsor, self.model, usage())
        ledger.forget_world(self.account, self.root.id)
        totals = ledger.totals(self.account)
        self.assertEqual(totals["calls"], 1)
        self.assertNotIn(str(self.root.id), totals["by_world"])
        self.assertEqual(ledger.recent(self.account), [])

    def test_an_account_that_has_spent_nothing_reads_as_zero(self):
        totals = ledger.totals(self.account)
        self.assertEqual(totals["calls"], 0)
        self.assertEqual(totals["by_job"], {})
        self.assertEqual(totals["seconds"], 0.0)
        self.assertEqual(totals["timed"], 0)


@tag("world")
class HowLongACallTook(GameTest):
    """
    Seconds per call, per job and per world.

    What a player actually waited, which the tool-loop plan's soak compares
    against a baseline taken before anything changed.
    """

    accounts = True

    def setUp(self):
        super().setUp()
        self.root = self.room1
        self.room1.db.world_root = self.root
        self.model = ModelChoice("test/model", {}, job="commands")
        self.sponsor = Sponsor(world_root=self.root, account=self.account,
                               actor=self.char1)

    def test_the_time_is_added_up_everywhere_the_tokens_are(self):
        ledger.note(self.sponsor, self.model, usage(), 1.5)
        ledger.note(self.sponsor, self.model, usage(), 2.25)
        totals = ledger.totals(self.account)
        self.assertAlmostEqual(totals["seconds"], 3.75)
        self.assertEqual(totals["timed"], 2)
        self.assertAlmostEqual(totals["by_job"]["commands"]["seconds"], 3.75)
        self.assertEqual(totals["by_job"]["commands"]["timed"], 2)
        self.assertAlmostEqual(
            totals["by_world"][str(self.root.id)]["seconds"], 3.75)

    def test_a_call_nobody_timed_counts_but_adds_no_time(self):
        """
        An average is the seconds over the timed calls. An untimed call counted
        as zero would make every figure look faster than it was.
        """
        ledger.note(self.sponsor, self.model, usage())
        ledger.note(self.sponsor, self.model, usage(), 2.0)
        totals = ledger.totals(self.account)
        self.assertEqual(totals["calls"], 2)
        self.assertEqual(totals["timed"], 1)
        self.assertAlmostEqual(totals["seconds"], 2.0)

    def test_the_recent_entry_says_how_long(self):
        ledger.note(self.sponsor, self.model, usage(), 0.4567)
        ledger.note(self.sponsor, self.model, usage())
        newest, older = ledger.recent(self.account)[:2]
        self.assertIsNone(newest["seconds"])
        self.assertEqual(older["seconds"], 0.457)

    def test_nonsense_for_a_time_is_no_time_at_all(self):
        ledger.note(self.sponsor, self.model, usage(), "soon")
        ledger.note(self.sponsor, self.model, usage(), -3)
        ledger.note(self.sponsor, self.model, usage(), float("nan"))
        totals = ledger.totals(self.account)
        self.assertEqual(totals["calls"], 3)
        self.assertEqual(totals["timed"], 0)
        self.assertEqual(totals["seconds"], 0.0)
