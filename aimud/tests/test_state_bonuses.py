"""
States that are worth something to a person's figures.

"Starving costs 3 strength" is said once, on `starving`, and `gear` sums it
from scratch beside whatever somebody carries: the cost arrives when the state
does and goes when it goes, with no accounting kept anywhere. See
docs/becoming-and-time.md 5.6.
"""

from django.test import tag

from tests.base import GameTest
from world import gear, traits, verbs


@tag("world")
class WhatAStateIsWorth(GameTest):

    def setUp(self):
        super().setUp()
        self.root = self.room1
        self.root.db.is_world_root = True
        self.room1.db.world_root = self.root
        for slug, figure in (("strength", 10), ("hunger", 50)):
            traits.adjust(self.char1, slug, set_to=figure,
                          world_root=self.root, announce=False)

    def strength(self):
        return traits.value(self.char1, "strength")

    def test_a_state_that_is_set_is_worth_its_bonus_while_it_lasts(self):
        verbs.register_state(self.root, "blessed", bonuses={"strength": 2})
        verbs.apply_states(self.char1, add=["blessed"], world_root=self.root)
        self.assertEqual(self.strength(), 12)
        verbs.apply_states(self.char1, remove=["blessed"],
                           world_root=self.root)
        self.assertEqual(self.strength(), 10)

    def test_a_derived_state_is_worth_its_bonus_while_it_holds(self):
        verbs.register_state(
            self.root, "starving", bonuses={"strength": -3},
            when=[{"subject": "direct", "trait": "hunger", "max": 10}])
        traits.adjust(self.char1, "hunger", set_to=5, world_root=self.root,
                      announce=False)
        self.assertEqual(self.strength(), 7)
        traits.adjust(self.char1, "hunger", set_to=40, world_root=self.root,
                      announce=False)
        self.assertEqual(self.strength(), 10)

    def test_where_the_figure_went_is_said(self):
        verbs.register_state(self.root, "blessed", bonuses={"strength": 2})
        verbs.apply_states(self.char1, add=["blessed"], world_root=self.root)
        self.assertEqual(gear.sources(self.char1, "strength"),
                         [("being blessed", 2.0)])
        self.assertEqual(gear.describe(self.char1, "strength"),
                         "being blessed +2")

    def test_only_numbers_are_kept(self):
        verbs.register_state(self.root, "cursed",
                             bonuses={"strength": "a lot", "luck": -1,
                                      "wit": 0})
        self.assertEqual(verbs.state_bonuses(self.root),
                         {"cursed": {"luck": -1.0}})

    def test_an_empty_map_takes_them_away(self):
        verbs.register_state(self.root, "blessed", bonuses={"strength": 2})
        verbs.set_bonuses(self.root, "blessed", {})
        self.assertEqual(verbs.state_bonuses(self.root), {})

    def test_a_state_worth_nothing_costs_one_lookup(self):
        """The ordinary case: no state here is worth anything."""
        verbs.register_state(self.root, "damp")
        verbs.apply_states(self.char1, add=["damp"], world_root=self.root)
        self.assertEqual(self.strength(), 10)
        self.assertEqual(gear.sources(self.char1, "strength"), [])
