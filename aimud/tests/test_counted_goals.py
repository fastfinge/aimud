"""
Planning towards a number of something.

A want could name a thing or a sort of thing, and now it may say how many. The
counting itself is `world.quantity` and is tested there; what is tested here is
the half that goes wrong quietly -- whether a character can actually *advance*
such a want, one apple at a time.

The trap this closes: `goals._world_objects` looks in the actor's own hands
first, so somebody wanting three apples and holding one was handed back the
apple they were already holding. There is no step that gets you a thing you
have, so the want looked unreachable and was given up on after a few turns.
Nothing failed loudly; the character simply stopped wanting apples.
"""

from django.test import tag

from tests.base import GameTest
from world import conditions as C
from world import goals, planner


@tag("world")
class CollectingThree(GameTest):

    def setUp(self):
        super().setUp()
        self.root = self.room1
        self.root.db.is_world_root = True
        self.room1.db.world_root = self.root
        self.goal = {"type": "holds", "kind": "apple.n.01", "count": 3}

    def apples(self, how_many, where=None):
        from evennia import create_object

        made = []
        for index in range(how_many):
            obj = create_object("typeclasses.objects.Object",
                                key=f"apple {index + 1}",
                                location=where or self.room1)
            obj.db.kinds = ["apple.n.01"]
            made.append(obj)
        return made

    def met(self):
        ctx = C.context(actor=self.char1, world_root=self.root)
        return all(C.evaluate(part, ctx) for part in C.from_goal(self.goal))

    def step(self):
        return planner._for_condition(self.char1, self.root, self.goal)[0]

    def test_a_counted_want_is_not_met_by_one(self):
        self.apples(3)
        self.assertFalse(self.met())

    def test_each_apple_in_hand_leaves_a_step_for_the_next(self):
        """
        The whole of it: three apples, three steps, and the want met only at
        the end. Each round takes the step the planner offers, which is what
        an idling character does with it.
        """
        apples = self.apples(3)
        for taken in range(3):
            self.assertFalse(self.met(), f"met after only {taken}")
            said = self.step()
            self.assertIsNotNone(said, f"no step with {taken} in hand")
            self.assertTrue(said.startswith("get "), said)
            # Whatever it named, it must not be one already in hand.
            wanted = said[len("get "):]
            obj = next(a for a in apples if a.key == wanted)
            self.assertIsNot(obj.location, self.char1,
                             "planned to get an apple already held")
            obj.move_to(self.char1, quiet=True)
        self.assertTrue(self.met())
        self.assertIsNone(self.step(), "still planning once the want is met")

    def test_a_want_with_nothing_left_to_find_offers_no_step(self):
        """
        Two apples in a world and a want for three. The honest answer is no
        step -- which the goal above notices and spends its patience on --
        rather than a step towards something already held.
        """
        for apple in self.apples(2):
            apple.move_to(self.char1, quiet=True)
        self.assertFalse(self.met())
        self.assertIsNone(self.step())

    def test_an_uncounted_want_still_takes_the_nearest(self):
        """
        Skipping what already counts must not change the ordinary case. With
        nothing in hand, nothing is skipped, and the nearest apple is still
        the answer.
        """
        self.apples(1, where=self.char1.location)
        step = planner._for_condition(
            self.char1, self.root, {"type": "holds", "kind": "apple.n.01"})[0]
        self.assertEqual(step, "get apple 1")

    def test_carrying_a_garment_still_advances_wearing_it(self):
        """
        A `worn` want skips only what is already on. A coat in hand is a step
        towards wearing it -- find it, pick it up, put it on -- so it must not
        be skipped as though it already counted.
        """
        from evennia import create_object

        coat = create_object("typeclasses.objects.Object", key="grey coat",
                             location=self.char1)
        coat.db.kinds = ["coat.n.01"]
        step = planner._for_condition(
            self.char1, self.root, {"type": "worn", "kind": "coat.n.01"})[0]
        self.assertEqual(step, "wear grey coat")

    def test_skipping_is_asked_of_the_search_itself(self):
        """`find_of_kind` is where it lives, so anything else planning gets it."""
        held, loose = self.apples(1, where=self.char1), self.apples(1)
        found = goals.find_of_kind(self.root, self.char1, "apple.n.01",
                                   skip=held)
        self.assertIs(found, loose[0])
