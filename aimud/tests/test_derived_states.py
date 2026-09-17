"""
States that are worked out rather than written.

"Starving" is hunger at 10 or less, said once, in the register. Nothing ever
writes it onto anybody, and everything that asks whether somebody is starving
gets the answer from the figure as it is now. See docs/becoming-and-time.md §5.
"""

from django.test import tag

from tests.base import GameTest
from world import conditions as C
from world import planner, rule_gen, rulecheck, traits, verbs


class DerivedStateTest(GameTest):
    loose_objects = 1

    def setUp(self):
        super().setUp()
        self.root = self.room1
        self.root.db.is_world_root = True
        self.room1.db.world_root = self.root
        traits.adjust(self.char1, "hunger", set_to=50, world_root=self.root,
                      announce=False)

    def starving(self, group=None):
        return verbs.register_state(
            self.root, "starving", means="so hungry it is hard to act",
            group=group,
            when=[{"subject": "direct", "trait": "hunger", "max": 10}])

    def hunger(self, figure):
        traits.adjust(self.char1, "hunger", set_to=figure,
                      world_root=self.root, announce=False)


@tag("world")
class WorkingItOut(DerivedStateTest):

    def test_it_holds_exactly_while_its_conditions_do(self):
        self.assertEqual(self.starving(), "starving")
        self.assertNotIn("starving", verbs.implied_states(self.char1))
        self.hunger(5)
        self.assertIn("starving", verbs.implied_states(self.char1))
        self.hunger(40)
        self.assertNotIn("starving", verbs.implied_states(self.char1))

    def test_it_is_never_written_down(self):
        self.starving()
        self.hunger(5)
        verbs.implied_states(self.char1)
        self.assertNotIn("starving", verbs.states(self.char1))

    def test_a_rule_asks_for_it_by_name(self):
        self.starving()
        ctx = C.context({}, self.char1, self.root)
        wants = {"subject": "actor", "is": ["starving"]}
        self.assertFalse(C.evaluate(wants, ctx))
        self.hunger(3)
        self.assertTrue(C.evaluate(wants, ctx))

    def test_a_definition_may_ask_about_another_derived_state(self):
        self.starving()
        verbs.register_state(self.root, "tired", when=[
            {"subject": "direct", "trait": "hunger", "max": 60}])
        verbs.register_state(self.root, "exhausted", when=[
            {"subject": "direct", "is": ["tired", "starving"]}])
        self.assertNotIn("exhausted", verbs.implied_states(self.char1))
        self.hunger(5)
        self.assertIn("exhausted", verbs.implied_states(self.char1))

    def test_it_is_said_when_somebody_looks(self):
        """Unlike `alive`, which would be noise under every character."""
        self.starving()
        self.hunger(5)
        self.assertIn("starving", verbs.condition(self.char1))
        self.assertNotIn("alive", verbs.condition(self.char1))


@tag("world")
class NeverWritten(DerivedStateTest):

    def test_setting_one_does_nothing(self):
        self.starving()
        verbs.apply_states(self.char1, add=["starving"], world_root=self.root)
        self.assertNotIn("starving", verbs.implied_states(self.char1))

    def test_nor_does_clearing_one(self):
        self.starving()
        self.hunger(5)
        verbs.apply_states(self.char1, remove=["starving"],
                           world_root=self.root)
        self.assertIn("starving", verbs.implied_states(self.char1))

    def test_a_generated_rule_that_writes_one_is_refused(self):
        self.starving()
        kept, complaints = rule_gen.validate(
            {"rules": [{"phase": "carry_out", "scope": "world",
                        "name": "fasting starves you",
                        "effects": [{"type": "set_state", "role": "actor",
                                     "add": ["starving"]}]}]},
            [("world", "everywhere", {"world": True})], "fast", self.root)
        self.assertEqual(kept, [])
        self.assertTrue(any("worked out" in c for c in complaints))

    def test_the_scan_reports_a_stored_rule_that_writes_one(self):
        self.starving()
        registers = rulecheck.of_world(self.root)
        registers["rules"] = {"r1": {
            "id": "r1", "phase": "carry_out", "action": "fast",
            "effects": [{"type": "set_state", "role": "actor",
                         "add": ["starving"]}]}}
        found = rulecheck.scan(registers)
        self.assertEqual(found["writes_derived"], [("fast#r1", ["starving"])])
        self.assertNotIn("starving", found["unsettable"])

    def test_the_state_tools_say_it_is_worked_out(self):
        self.starving()
        from world import toolbox as tb

        tools = {tool.name: tool for tool in verbs.lookup_tools()}
        said = []
        tools["show_state"].handler(
            tb.ToolContext(world_root=self.root), {"slug": "starving"},
            said.append)
        self.assertIn("worked out", str(said))


@tag("world")
class WhatIsRefused(DerivedStateTest):

    def test_a_cycle(self):
        verbs.register_state(self.root, "gloomy", when=[
            {"subject": "direct", "trait": "hunger", "max": 20}])
        self.assertEqual(verbs.register_state(self.root, "sulky", when=[
            {"subject": "direct", "is": ["gloomy"]}]), "sulky")
        # Now make gloomy depend on sulky, which depends on gloomy.
        self.assertEqual(verbs.register_state(self.root, "gloomy", when=[
            {"subject": "direct", "is": ["sulky"]}]), "")
        self.assertIn("trait", str(verbs.vocabulary(self.root)["gloomy"]))

    def test_a_word_that_is_already_set_rather_than_worked_out(self):
        verbs.register_state(self.root, "hungry")
        self.assertEqual(verbs.register_state(self.root, "hungry", when=[
            {"subject": "direct", "trait": "hunger", "max": 30}]), "")

    def test_a_definition_that_asks_nothing(self):
        self.assertEqual(verbs.register_state(self.root, "vague",
                                              when=[{"subject": "direct"}]),
                         "")

    def test_a_group_that_already_holds_states_that_are_set(self):
        """Posture's members are set by sitting and standing."""
        self.assertEqual(self.starving(group="posture"), "")

    def test_a_set_state_is_kept_out_of_a_derived_group(self):
        self.starving(group="hunger_level")
        slug = verbs.register_state(self.root, "peckish", group="hunger_level")
        self.assertEqual(slug, "peckish")
        self.assertEqual(verbs.group_of(self.root, "peckish"), None)


@tag("world")
class StoppingSomebody(DerivedStateTest):

    def test_a_derived_state_in_a_gating_group_stops_its_holder(self):
        verbs.register_group(self.root, "collapse", prevents_acting=True)
        verbs.register_state(self.root, "fainted", group="collapse", when=[
            {"subject": "direct", "trait": "hunger", "max": 0}])
        self.assertEqual(verbs.blocked(self.char1, "prevents_acting",
                                       self.root), "")
        self.hunger(0)
        self.assertEqual(verbs.blocked(self.char1, "prevents_acting",
                                       self.root), "fainted")

    def test_one_that_gates_nothing_is_not_even_asked(self):
        self.starving()
        self.hunger(0)
        self.assertEqual(verbs.derived_holds(self.char1, self.root, only=set()),
                         set())
        self.assertEqual(verbs._derived_gating(self.root, "prevents_acting"),
                         set())


@tag("world")
class PlanningTowardsOne(DerivedStateTest):

    def setUp(self):
        super().setUp()
        self.obj1.key = "anvil"
        verbs.register_state(self.root, "burdened", when=[
            {"subject": "direct", "holds": ["anvil"]}])

    def test_wanting_to_stop_being_one_is_undoing_its_definition(self):
        self.obj1.move_to(self.char1, quiet=True)
        action, _key, _condition = planner.plan_for(
            self.char1, self.root,
            [{"type": "state", "object": self.char1.key,
              "lacks": ["burdened"]}])
        self.assertEqual(action, "drop anvil")

    def test_wanting_to_be_one_is_making_its_definition_true(self):
        action, _key, _condition = planner.plan_for(
            self.char1, self.root,
            [{"type": "state", "object": self.char1.key,
              "is": ["burdened"]}])
        self.assertEqual(action, "get anvil")
