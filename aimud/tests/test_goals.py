"""
Goals, now that testing them is somebody else's job.

`goals` keeps its own shape -- a list of typed conditions, which is what a
model writes and what quests store -- and hands the testing to
`world.conditions`. These say the handover kept the behaviour, and pin one
thing it fixed on the way through.
"""

from django.test import tag
from evennia.utils.test_resources import EvenniaTest

from world import goals, verbs


@tag("world")
class TestingAGoal(EvenniaTest):

    def setUp(self):
        super().setUp()
        self.root = self.room1
        self.root.db.is_world_root = True
        self.room1.db.world_root = self.root
        self.room2.db.world_root = self.root

    def met(self, *conditions):
        return goals.satisfied(list(conditions), self.char1, self.root)

    def test_carrying_something(self):
        want = {"type": "holds", "object": "Obj"}
        self.assertFalse(self.met(want))
        self.obj1.move_to(self.char1, quiet=True)
        self.assertTrue(self.met(want))

    def test_a_thing_being_in_a_state(self):
        want = {"type": "state", "object": "Obj", "is": ["lit"]}
        self.assertFalse(self.met(want))
        verbs.apply_states(self.obj1, add=["lit"], world_root=self.root)
        self.assertTrue(self.met(want))

    def test_a_state_it_must_not_be_in(self):
        verbs.apply_states(self.obj1, add=["burning"], world_root=self.root)
        self.assertFalse(self.met({"type": "state", "object": "Obj",
                                   "lacks": ["burning"]}))

    def test_a_state_condition_carrying_both_halves_needs_both(self):
        """One goal condition, two conditions underneath, and all must hold."""
        want = {"type": "state", "object": "Obj",
                "is": ["lit"], "lacks": ["broken"]}
        verbs.apply_states(self.obj1, add=["lit", "broken"],
                           world_root=self.root)
        self.assertFalse(self.met(want))
        verbs.apply_states(self.obj1, remove=["broken"], world_root=self.root)
        self.assertTrue(self.met(want))

    def test_being_somewhere(self):
        self.room2.db.room_title = "The Library"
        want = {"type": "in_room", "room": "Library"}
        self.assertFalse(self.met(want))
        self.char1.move_to(self.room2, quiet=True)
        self.assertTrue(self.met(want))

    def test_wearing_something(self):
        self.obj1.move_to(self.char1, quiet=True)
        want = {"type": "worn", "object": "Obj"}
        self.assertFalse(self.met(want))
        self.obj1.db.worn = True
        self.assertTrue(self.met(want))

    def test_getting_rid_of_something(self):
        """
        Named distinctly on purpose. `find_object` matches on a substring, so
        a goal about "Obj" is satisfied by "Obj2" still being here -- which is
        its behaviour before this change and after it, and a trap worth
        knowing about when writing a test rather than a rule.
        """
        self.obj1.key = "Verdigris Lantern"
        want = {"type": "gone", "object": "Verdigris Lantern"}
        self.assertFalse(self.met(want))
        self.obj1.delete()
        self.assertTrue(self.met(want))

    def test_a_figure_reaching_a_number(self):
        from world import traits

        want = {"type": "trait", "trait": "stamina", "min": 10}
        traits.ensure(self.char1, "stamina", world_root=self.root, base=2)
        self.assertFalse(self.met(want))
        traits.adjust(self.char1, "stamina", set_to=20, world_root=self.root)
        self.assertTrue(self.met(want))

    def test_an_empty_goal_is_never_satisfied(self):
        self.assertFalse(goals.satisfied([], self.char1, self.root))

    def test_every_condition_has_to_hold(self):
        self.obj1.move_to(self.char1, quiet=True)
        self.assertFalse(self.met({"type": "holds", "object": "Obj"},
                                  {"type": "state", "object": "Obj",
                                   "is": ["lit"]}))

    def test_progress_reports_each_condition_in_order(self):
        self.obj1.move_to(self.char1, quiet=True)
        found = goals.progress(
            [{"type": "holds", "object": "Obj"},
             {"type": "state", "object": "Obj", "is": ["lit"]}],
            self.char1, self.root)
        self.assertEqual([met for met, _said in found], [True, False])
        self.assertTrue(all(said for _met, said in found))


@tag("world")
class SayingAGoal(EvenniaTest):

    def setUp(self):
        super().setUp()
        self.root = self.room1
        self.root.db.is_world_root = True
        self.room1.db.world_root = self.root

    def test_a_goal_reads_as_a_list_of_wants(self):
        said = goals.describe(
            [{"type": "holds", "object": "brass key"},
             {"type": "in_room", "room": "the Vault"}],
            self.char1, self.root)
        self.assertIn("brass key", said)
        self.assertIn("Vault", said)
        self.assertIn(", then ", said)

    def test_an_empty_goal_says_so(self):
        self.assertEqual(goals.describe([]), "nothing in particular")
        self.assertEqual(goals.describe(None), "nothing in particular")

    def test_a_goal_can_be_said_with_nobody_to_test_it_against(self):
        """
        Every NPC prompt calls it this way -- `goals.describe(npc.db.goal)` --
        and a goal about being somewhere used to reach `actor.location` on
        `None` and raise. It now reads as a plain statement.
        """
        said = goals.describe([{"type": "in_room", "room": "the Bridge"}])
        self.assertIn("Bridge", said)

    def test_and_so_can_every_other_sort_of_goal(self):
        for want in ({"type": "holds", "object": "brass key"},
                     {"type": "worn", "object": "grey coat"},
                     {"type": "state", "object": "lamp", "is": ["lit"]},
                     {"type": "trait", "trait": "stamina", "min": 5},
                     {"type": "gone", "object": "rat"},
                     {"type": "exists", "kind": "cake.n.01"},
                     {"type": "delivered", "object": "letter",
                      "to": "the steward"}):
            said = goals.describe([want])
            self.assertTrue(said, want)
            self.assertNotEqual(said, "nothing in particular", want)
