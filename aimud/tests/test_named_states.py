"""
A thing is in the conditions its name says it is in.

Found in playtesting. A "Wax-Sealed Glass Vial" was made before its world knew
`sealed` as a condition; the rule later written for unsealing introduced the
word and required it, and the vial was refused for not being sealed. The name
cannot be repaired, but the state can.
"""

from django.test import tag

from tests.base import GameTest
from world import attempt as attempt_mod
from world import clothing, verbs


@tag("world")
class WhatTheNameSays(GameTest):

    def setUp(self):
        super().setUp()
        self.root = self.room1
        self.room1.db.world_root = self.root
        self.room1.db.is_world_root = True

    def make(self, name):
        return clothing.create({"name": name, "description": "A thing."},
                               location=self.room1)

    def test_made_in_a_world_that_knows_the_condition(self):
        verbs.register_state(self.root, "sealed", means="shut with a seal",
                             group="seal_status")
        vial = self.make("Wax-Sealed Glass Vial")
        self.assertIn("sealed", verbs.states(vial))

    def test_a_condition_learned_later_is_adopted_before_the_next_check(self):
        """The bug as it was found, through the door the check rules use."""
        vial = self.make("Wax-Sealed Glass Vial")
        self.assertNotIn("sealed", verbs.states(vial))
        verbs.register_state(self.root, "sealed", means="shut with a seal",
                             group="seal_status")
        attempt_mod.permitted(self.char1, "unseal", {"direct": vial})
        self.assertIn("sealed", verbs.states(vial))

    def test_once_taken_away_it_stays_away(self):
        verbs.register_state(self.root, "sealed", means="shut with a seal",
                             group="seal_status")
        vial = self.make("Wax-Sealed Glass Vial")
        verbs.apply_states(vial, remove=["sealed"], world_root=self.root,
                           announce=False)
        self.assertEqual(verbs.adopt_named_states(vial, self.root), [])
        self.assertNotIn("sealed", verbs.states(vial))

    def test_a_name_with_no_condition_in_it_changes_nothing(self):
        verbs.register_state(self.root, "sealed", means="shut with a seal",
                             group="seal_status")
        vial = self.make("Green Glass Vial")
        self.assertEqual(verbs.states(vial), set())

    def test_a_condition_that_belongs_to_people_is_not_given_to_a_thing(self):
        """A sleeping bag is not asleep."""
        verbs.register_group(self.root, "restraint", prevents_moving=True)
        verbs.register_state(self.root, "bound", means="tied up",
                             group="restraint")
        ledger = self.make("Bound Ledger")
        self.assertNotIn("bound", verbs.states(ledger))

    def test_a_persons_name_is_not_a_claim_about_them(self):
        self.char1.key = "Wet Char"
        self.assertEqual(verbs.adopt_named_states(self.char1, self.root), [])
