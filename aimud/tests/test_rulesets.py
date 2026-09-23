"""
Rulesets: bundles of rules a world is built with, chosen rather than assumed.

Three things are tested here and they fail in different ways.

The **loader** fails loudly -- a bad document is refused and logged -- and that
is the easy half. The **seeding** fails quietly, which is why most of this file
is about it: a ruleset whose rules are seeded twice, or whose old edition is
left standing beside the new one, is a world that behaves almost right.

And the acceptance test for the whole of it is `NothingChangedForADefaultWorld`:
a world that takes the defaults and nothing else must behave exactly as it did
when `standard_rules.py` held the list in Python.
"""

import json
import os
import tempfile

from django.test import SimpleTestCase, tag

from tests.base import GameTest
from world import rulebooks as R
from world import rulesets, standard_rules


class ADocument(SimpleTestCase):
    """What the validator refuses, and why each one matters."""

    def doc(self, **fields):
        base = {"name": "trial", "version": 1, "means": "for testing",
                "requires": [], "conflicts": []}
        base.update(fields)
        return base

    def test_a_good_one_has_nothing_wrong_with_it(self):
        self.assertEqual(rulesets.problems(self.doc(), known={}), [])

    def test_it_must_say_what_it_is_for(self):
        """
        The line the menu shows. A ruleset nobody can describe is one nobody
        can choose on purpose.
        """
        self.assertIn("does not say what it is for",
                      " ".join(rulesets.problems(self.doc(means=""), known={})))

    def test_it_must_have_a_plain_name(self):
        wrong = rulesets.problems(self.doc(name="not a name!"), known={})
        self.assertTrue(wrong)

    def test_a_rule_with_no_phase_this_game_runs_is_refused(self):
        wrong = rulesets.problems(self.doc(rules=[
            {"name": "x", "phase": "whenever"}]), known={})
        self.assertIn("phase", " ".join(wrong))

    def test_a_rule_with_no_name_is_refused(self):
        """A rule is a name to anybody reading `rules`, and to `_decisions`."""
        wrong = rulesets.problems(self.doc(rules=[
            {"name": "", "phase": "check"}]), known={})
        self.assertIn("no name", " ".join(wrong))

    def test_a_condition_this_game_cannot_test_is_refused(self):
        wrong = rulesets.problems(self.doc(rules=[
            {"name": "x", "phase": "check",
             "conditions": [{"subject": "actor", "holds": {"count": 99}}]}]),
            known={})
        self.assertIn("not one this game can test", " ".join(wrong))

    def test_a_figure_the_ruleset_never_registers_is_refused(self):
        """
        The failure this exists for is silence. A rule asking about a figure
        nothing registers simply never gathers, and nobody sees an error.
        """
        wrong = rulesets.problems(self.doc(
            attributes=[{"slug": "health"}],
            rules=[{"name": "x", "phase": "check",
                    "conditions": [{"subject": "actor", "trait": "vigour",
                                    "max": 0}]}]), known={})
        self.assertIn("vigour", " ".join(wrong))

    def test_but_one_a_required_ruleset_registers_is_fine(self):
        upstream = self.doc(name="base", attributes=[{"slug": "health"}])
        doc = self.doc(name="on_top", requires=["base"],
                       attributes=[{"slug": "spirit"}],
                       rules=[{"name": "x", "phase": "check",
                               "conditions": [{"subject": "actor",
                                               "trait": "health", "max": 0}]}])
        self.assertEqual(rulesets.problems(doc, known={"base": upstream}), [])


class WhatShipsWithTheGame(SimpleTestCase):

    def test_the_default_one_is_a_default(self):
        self.assertIn(rulesets.DEFAULT, rulesets.defaults())

    def test_death_is_not(self):
        """A world gets it by asking; that is the whole point of rulesets."""
        self.assertNotIn("death", rulesets.defaults())

    def test_every_one_that_ships_loads(self):
        """
        Guards against a ruleset being shipped that no world can ever use.
        A refused document is logged and dropped, so without this the only
        symptom is the menu being one entry shorter than the directory.
        """
        names = set(rulesets.available())
        on_disk = {entry[:-len(".json")]
                   for entry in os.listdir(rulesets.BUILTIN_DIR)
                   if entry.endswith(".json")}
        self.assertEqual(on_disk - names, set())

    def test_death_needs_the_default_and_says_so(self):
        wanted, wrong = rulesets.resolve(["death"])
        self.assertEqual(wrong, [])
        self.assertEqual(wanted, [rulesets.DEFAULT, "death"],
                         "what is required must be seeded first")

    def test_asking_for_one_that_does_not_exist_is_reported(self):
        _wanted, wrong = rulesets.resolve(["gravity"])
        self.assertTrue(wrong)


class ReadingADirectory(SimpleTestCase):
    """Loading, with a directory of this test's own."""

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(rulesets.available, True)

    def write(self, name, doc):
        with open(os.path.join(self.dir, f"{name}.json"), "w",
                  encoding="utf-8") as handle:
            json.dump(doc, handle)

    def load(self):
        from unittest import mock

        with mock.patch.object(rulesets, "directories",
                               return_value=[rulesets.BUILTIN_DIR, self.dir]):
            return rulesets.available(reload=True)

    def test_a_local_ruleset_is_offered_beside_the_built_in_ones(self):
        self.write("weather", {"name": "weather", "version": 1,
                               "means": "it rains"})
        self.assertIn("weather", self.load())

    def test_a_local_one_replaces_a_built_in_one_of_the_same_name(self):
        """How a server runs its own idea of death without patching the game."""
        self.write("death", {"name": "death", "version": 9,
                             "means": "our own idea of it"})
        self.assertEqual(self.load()["death"]["version"], 9)

    def test_a_broken_one_is_dropped_rather_than_half_applied(self):
        self.write("broken", {"name": "broken", "version": 1, "means": "x",
                              "rules": [{"name": "y", "phase": "nonsense"}]})
        self.assertNotIn("broken", self.load())

    def test_and_does_not_take_the_good_ones_with_it(self):
        self.write("broken", {"name": "broken"})
        self.assertIn(rulesets.DEFAULT, self.load())


@tag("world")
class SeedingAWorld(GameTest):

    def setUp(self):
        super().setUp()
        self.root = self.room1
        self.root.db.is_world_root = True
        self.room1.db.world_root = self.root

    def names(self):
        return [rule["name"] for rule in R.all_rules(self.root)]

    def test_a_world_gets_the_defaults_when_nobody_says_otherwise(self):
        rulesets.seed(self.root)
        self.assertEqual(rulesets.chosen(self.root), [rulesets.DEFAULT])
        self.assertIn("you must be able to act", self.names())

    def test_seeding_twice_adds_nothing(self):
        rulesets.seed(self.root)
        before = len(R.all_rules(self.root))
        self.assertEqual(rulesets.seed(self.root), [])
        self.assertEqual(len(R.all_rules(self.root)), before)

    def test_asking_for_one_brings_in_what_it_requires(self):
        rulesets.seed(self.root, ["death"])
        self.assertEqual(rulesets.chosen(self.root),
                         sorted([rulesets.DEFAULT, "death"]))

    def test_a_world_without_death_has_none_of_its_rules(self):
        rulesets.seed(self.root)
        self.assertNotIn("no health left is dead", self.names())

    def test_and_one_with_it_has_them(self):
        rulesets.seed(self.root, ["death"])
        self.assertIn("no health left is dead", self.names())

    def test_taking_one_away_suspends_its_rules_rather_than_deleting_them(self):
        """
        The opposite of what `_retire` does, and for the opposite reason: a
        world may have built on these, and deleting them would take that work
        with it silently.
        """
        rulesets.seed(self.root, ["death"])
        rulesets.forget(self.root, "death")
        rule = next(r for r in R.all_rules(self.root)
                    if r["name"] == "no health left is dead")
        self.assertFalse(rule["listed"])
        self.assertNotIn("death", rulesets.chosen(self.root))

    def test_and_putting_it_back_puts_them_back(self):
        rulesets.seed(self.root, ["death"])
        rulesets.forget(self.root, "death")
        rulesets.seed(self.root, ["death"])
        rule = next(r for r in R.all_rules(self.root)
                    if r["name"] == "no health left is dead")
        self.assertTrue(rule["listed"])

    def test_what_a_world_wrote_for_itself_is_never_touched(self):
        rulesets.seed(self.root, ["death"])
        R.add(self.root, R.blank(action="read", phase=R.CHECK,
                                 name="a rule this world wrote"))
        rulesets.forget(self.root, "death")
        mine = next(r for r in R.all_rules(self.root)
                    if r["name"] == "a rule this world wrote")
        self.assertTrue(mine["listed"])


@tag("world")
class WhatDeathBrings(GameTest):
    """The ruleset that exercises every section but kinds."""

    def setUp(self):
        super().setUp()
        self.root = self.room1
        self.root.db.is_world_root = True
        self.room1.db.world_root = self.root
        rulesets.seed(self.root, ["death"])

    def test_the_figure_it_is_about(self):
        from world import traits

        self.assertIn("health", traits.vocabulary(self.root))

    def test_the_actions_it_declares(self):
        from world import actions

        self.assertIsNotNone(actions.spec(self.root, "revive"))

    def test_reviving_happens_in_spite_of_being_unable_to_act(self):
        """
        `actions.GATES` exists for exactly this and had no shipped user. A
        world that kills somebody and cannot let them back has wasted the
        rule that killed them.
        """
        from world import actions

        self.assertTrue(actions.waives(self.root, "revive", "acting"))

    def test_the_spellings_it_folds(self):
        from world import verbs

        self.assertEqual(verbs.canonical_verb("resurrect", self.root),
                         "revive")

    def test_and_folds_them_only_for_a_world_that_chose_it(self):
        """Asked with no world, the word means nothing in particular."""
        from world import verbs

        self.assertEqual(verbs.canonical_verb("resurrect"), "resurrect")

    def test_a_ruleset_cannot_move_the_engine_underneath_itself(self):
        """
        The table in `world.verbs` is English that is true everywhere. A data
        file that could redefine `get` or `look` would be a ruleset rewriting
        the game.
        """
        from world import rulesets as R_mod
        from world import verbs

        R_mod._fold(self.root, {"word": "examine", "means": "destroy"})
        self.assertEqual(verbs.canonical_verb("examine", self.root), "look")

    def test_running_out_of_health_kills(self):
        """
        The rule `becoming.py`'s own docstring opens with as its example, and
        which no world was ever actually given.

        `settle` by hand because nothing is being attempted here: the pipeline
        settles where an operation ends, and a figure moved directly has no
        operation around it.
        """
        from world import becoming, traits, verbs

        traits.ensure(self.char1, "health", world_root=self.root)
        traits.adjust(self.char1, "health", set_to=0, world_root=self.root)
        becoming.settle()
        self.assertIn("dead", verbs.states(self.char1))

    def test_and_then_they_cannot_act(self):
        """Which is the whole of what the ruleset is for."""
        from world import becoming, traits, verbs

        traits.ensure(self.char1, "health", world_root=self.root)
        traits.adjust(self.char1, "health", set_to=0, world_root=self.root)
        becoming.settle()
        self.assertEqual(verbs.blocked(self.char1, "prevents_acting",
                                       self.root), "dead")

    def test_reviving_gives_them_their_life_back(self):
        from world import becoming, effects, traits, verbs

        traits.ensure(self.char1, "health", world_root=self.root)
        traits.adjust(self.char1, "health", set_to=0, world_root=self.root)
        becoming.settle()
        rule = next(r for r in R.all_rules(self.root)
                    if r["name"] == "reviving somebody gives them their life back")
        effects.apply(self.char1, self.room1, rule["effects"],
                      bound={"direct": self.char1}, world_root=self.root)
        becoming.settle()
        self.assertNotIn("dead", verbs.states(self.char1))
        self.assertEqual(traits.value(self.char1, "health"), 1)


@tag("world")
class NothingChangedForADefaultWorld(GameTest):
    """
    The acceptance test for the whole of step 4.

    A world that takes the defaults must hold exactly what `standard_rules.py`
    used to put in it, marked the way it used to be marked, because everything
    that reads a world's rules was written against that.
    """

    def setUp(self):
        super().setUp()
        self.root = self.room1
        self.root.db.is_world_root = True
        self.room1.db.world_root = self.root

    def test_the_same_rules_arrive(self):
        standard_rules.seed(self.root)
        got = {r["name"] for r in R.all_rules(self.root)}
        wanted = {r["name"]
                  for r in rulesets.get(rulesets.DEFAULT)["rules"]}
        self.assertEqual(wanted - got, set())

    def test_marked_the_way_they_were_marked(self):
        standard_rules.seed(self.root)
        for rule in R.all_rules(self.root):
            self.assertEqual(rule["source"], rulesets.STANDARD)
            self.assertTrue(standard_rules.is_standard(rule))

    def test_and_the_one_that_ships_suspended_still_does(self):
        standard_rules.seed(self.root)
        rule = next(r for r in R.all_rules(self.root)
                    if r["name"] == "you may not take what is not yours")
        self.assertFalse(rule["listed"])
