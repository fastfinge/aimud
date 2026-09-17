"""
Writing becomes rules, and finding what is wrong with them.

A world is asked what running out of a figure means the first time somebody's
gauge actually runs out -- evidence the question matters -- and the answer is
held to what a becomes rule must be. The scan finds rules that demand a
condition and its opposite, rules waiting on a figure nothing moves, and
worked-out conditions that overlap. A rule added to what is already so says
what it holds for and can be applied once. And the planner follows a becomes
rule, so wanting somebody dead is wanting their health down. See
docs/becoming-and-time.md §10.
"""

from unittest import mock

from django.test import SimpleTestCase, tag

from tests.base import GameTest
from tests.support import (FakeSponsor, immediately, replying, tool_call,
                           tool_reply)
from world import becoming, planner, rule_gen, rulecheck, traits, verbs
from world import rulebooks as R


@tag("unit")
class HoldingAnAnswerToWhatABecomesRuleMustBe(SimpleTestCase):

    def keep(self, **rule):
        return rule_gen.validate_becoming({"rules": [rule]})

    def test_a_good_rule_is_kept(self):
        kept, complaints = self.keep(
            name="no health left is dead",
            when=[{"subject": "direct", "trait": "health", "max": 0}],
            effects=[{"type": "set_state", "role": "direct", "add": ["dead"]}],
            report="{direct} $pconj(collapse).")
        self.assertEqual(complaints, [])
        self.assertEqual(kept[0]["phase"], R.BECOMES)

    def test_one_that_watches_nothing_is_refused(self):
        kept, complaints = self.keep(name="?", when=[],
                                     effects=[{"type": "narrate"}])
        self.assertEqual(kept, [])
        self.assertTrue(complaints)

    def test_try_cannot_follow_from_something_becoming_true(self):
        kept, complaints = self.keep(
            name="x", when=[{"subject": "direct", "is": ["wet"]}],
            effects=[{"type": "try", "action": "shiver"}])
        self.assertEqual(kept, [])
        self.assertTrue(any("try" in c for c in complaints))

    def test_a_cause_nobody_asked_for_is_refused(self):
        kept, complaints = self.keep(
            name="renown", when=[{"subject": "direct", "trait": "health",
                                  "max": 0}],
            effects=[{"type": "set_trait", "role": "cause",
                      "trait": "renown", "change": 1}])
        self.assertEqual(kept, [])
        self.assertTrue(any("cause" in c for c in complaints))


@tag("unit")
class WhatTheScanFinds(SimpleTestCase):

    def registers(self, rules, vocabulary=None, trait_vocabulary=None):
        return {"verb_rules": {}, "rules": rules, "state_groups": {},
                "kind_specs": {}, "state_vocabulary": vocabulary or {},
                "trait_vocabulary": trait_vocabulary or {}}

    def test_a_condition_and_its_opposite_at_once(self):
        found = rulecheck.scan(self.registers({"r1": {
            "id": "r1", "phase": "check", "action": "open", "name": "never",
            "conditions": [{"subject": "direct", "is": ["locked"]},
                           {"subject": "direct", "lacks": ["locked"]}]}}))
        self.assertEqual(found["contradictory"], [("r1", "never")])

    def test_a_rule_waiting_on_a_figure_nothing_lowers(self):
        dying = {"id": "r1", "phase": "becomes", "name": "dying",
                 "when": [{"subject": "direct", "trait": "health",
                           "max": 0}],
                 "effects": [{"type": "set_state", "role": "direct",
                              "add": ["dead"]}]}
        found = rulecheck.scan(self.registers({"r1": dying}))
        self.assertEqual(found["never_becomes"], [("r1", "dying", "health")])
        hurting = {"id": "r2", "phase": "carry_out", "action": "stab",
                   "effects": [{"type": "set_trait", "role": "direct",
                                "trait": "health", "change": -5}]}
        found = rulecheck.scan(self.registers({"r1": dying, "r2": hurting}))
        self.assertEqual(found["never_becomes"], [])

    def test_a_drain_in_the_register_counts(self):
        dying = {"id": "r1", "phase": "becomes", "name": "starving",
                 "when": [{"subject": "direct", "trait": "hunger",
                           "max": 0}]}
        found = rulecheck.scan(self.registers(
            {"r1": dying}, trait_vocabulary={"hunger": {"rate": -0.1}}))
        self.assertEqual(found["never_becomes"], [])

    def test_bands_that_overlap(self):
        vocabulary = {
            "hungry": {"group": "hunger", "when": [
                {"subject": "direct", "trait": "hunger", "max": 30}]},
            "starving": {"group": "hunger", "when": [
                {"subject": "direct", "trait": "hunger", "max": 10}]},
            "fed": {"group": "hunger", "when": [
                {"subject": "direct", "trait": "hunger", "above": 30}]},
        }
        found = rulecheck.scan(self.registers({}, vocabulary))
        self.assertEqual(found["overlapping_bands"],
                         [("hunger", "starving", "hungry")])


class AuthoringTest(GameTest):
    loose_objects = 1

    def setUp(self):
        super().setUp()
        becoming.forget_waiting()
        self.root = self.room1
        self.root.db.is_world_root = True
        self.room1.db.world_root = self.root

    def tearDown(self):
        becoming.forget_waiting()
        super().tearDown()


@tag("world")
class AskingWhatRunningOutMeans(AuthoringTest):

    def setUp(self):
        super().setUp()
        traits.register(self.root, "health", trait_type="gauge", base=10)

    def run_out(self):
        traits.adjust(self.char1, "health", set_to=10, world_root=self.root,
                      announce=False)
        traits.adjust(self.char1, "health", set_to=0, world_root=self.root,
                      announce=False)

    def test_the_first_time_a_gauge_runs_out_the_world_is_asked(self):
        with mock.patch.object(rule_gen, "learn_becoming") as asked, \
                mock.patch("world.sponsor.Sponsor.answers",
                           new_callable=mock.PropertyMock,
                           return_value=True):
            self.run_out()
        self.assertEqual(asked.call_count, 1)
        self.assertEqual(asked.call_args.args[2], "health")

    def test_not_where_nobody_pays(self):
        with mock.patch.object(rule_gen, "learn_becoming") as asked:
            self.run_out()
        asked.assert_not_called()

    def test_not_where_a_rule_already_watches_it(self):
        R.add(self.root, R.blank(
            phase=R.BECOMES, name="dying",
            when=[{"subject": "direct", "trait": "health", "max": 0}],
            effects=[{"type": "set_state", "role": "direct",
                      "add": ["dead"]}]))
        with mock.patch.object(rule_gen, "learn_becoming") as asked, \
                mock.patch("world.sponsor.Sponsor.answers",
                           new_callable=mock.PropertyMock,
                           return_value=True):
            self.run_out()
        asked.assert_not_called()

    def test_the_answer_is_filed_and_the_question_not_asked_again(self):
        answer = tool_reply(tool_call(
            "file_becoming", rules=[{
                "name": "no health left is dead",
                "when": [{"subject": "direct", "trait": "health", "max": 0}],
                "effects": [{"type": "set_state", "role": "direct",
                             "add": ["dead"]}],
                "report": "{direct} $pconj(collapse)."}]))
        filed = []
        with immediately(), replying(answer):
            rule_gen.learn_becoming(FakeSponsor(), self.root, "health",
                                    filed.extend)
        self.assertEqual([r["name"] for r in filed],
                         ["no health left is dead"])
        self.assertTrue(traits.known(self.root, "health")
                        .get(rule_gen.ASKED_BECOMING))


@tag("world")
class ARuleAddedToWhatIsAlreadySo(AuthoringTest):

    def test_it_says_what_it_holds_for_and_can_be_applied_once(self):
        traits.adjust(self.char1, "health", set_to=0, world_root=self.root,
                      announce=False)
        rule = R.add(self.root, R.blank(
            phase=R.BECOMES, name="dying",
            when=[{"subject": "direct", "trait": "health", "max": 0}],
            effects=[{"type": "set_state", "role": "direct",
                      "add": ["dead"]}]))
        self.assertEqual(
            becoming.already_true(self.root, rule, [self.char1]),
            [self.char1])
        becoming.apply_once(self.root, rule["id"], [self.char1])
        self.assertIn("dead", verbs.states(self.char1))


@tag("world")
class BandsFromAFiguresOwnWords(AuthoringTest):

    def test_descs_become_worked_out_states(self):
        traits.register(self.root, "hunger", descs={0: "starving",
                                                    10: "hungry", 30: "fed"})
        derived = verbs.derived_states(self.root)
        self.assertEqual({"starving", "hungry", "fed"} & set(derived),
                         {"starving", "hungry", "fed"})
        traits.adjust(self.char1, "hunger", set_to=15, world_root=self.root,
                      announce=False)
        held = verbs.implied_states(self.char1)
        self.assertIn("hungry", held)
        self.assertNotIn("starving", held)
        self.assertNotIn("fed", held)


@tag("world")
class PlanningThroughABecomesRule(AuthoringTest):

    def test_wanting_it_is_wanting_what_it_watches(self):
        self.obj1.key = "anvil"
        R.add(self.root, R.blank(
            phase=R.BECOMES, name="a burdened person is slowed",
            when=[{"subject": "direct", "holds": ["anvil"]}],
            effects=[{"type": "set_state", "role": "direct",
                      "add": ["slowed"]}]))
        action, _key, _condition = planner.plan_for(
            self.char1, self.root,
            [{"type": "state", "object": self.char1.key,
              "is": ["slowed"]}])
        self.assertEqual(action, "get anvil")
