"""
Rules that make somewhere new: digging, mining, building a shelter.

The gap the soak found. A rule could make a thing, move a thing, destroy a
thing and change where a way out led, and could not make anywhere to go. A
player who digs into a bank, mines a shaft, or walls himself a shelter out of
struts and heat-shield tile is plainly making a room, and nothing could say so.

**Nothing is generated when the effect fires.** A way out is opened and left
*pending*, and the room behind it is built by the ordinary generator the first
time anybody walks through -- the same machinery a world grows by, at the same
cost, at the same moment. Effects run synchronously and must stay free:
`create_object` builds from a spec the rule already holds for exactly that
reason, and a room that phoned a model mid-rule would make every dig cost
money whether or not anybody went and looked.

What makes it the *right* room is `why`, which becomes the exit's
`destination_hint` -- the field the room generator already reads to keep a
door's promise and the room behind it consistent.
"""

from django.test import SimpleTestCase, tag

from tests import test_phases
from world import effects, rulebooks as R
from world import coords, worldgen


class TheVocabulary(SimpleTestCase):

    def test_it_is_a_word_this_game_knows(self):
        self.assertIn("create_room", effects.VOCABULARY)

    def test_and_says_what_it_does_in_words(self):
        said = effects.say({"type": "create_room", "direction": "down",
                            "why": "dug out of the packed earth"})
        self.assertIn("down", said)
        self.assertIn("dug out", said)

    def test_it_is_not_read_backwards_and_says_why(self):
        """
        A decision on the record, which `docs/rulebooks-from-inform.md` 11.1
        asks for: a goal names a room, and the room this opens onto has no
        name until somebody walks into it.
        """
        self.assertFalse(effects.known("create_room")["backwards"])


@tag("world")
class DiggingAWay(test_phases.RunningTheAttempt):

    def setUp(self):
        super().setUp()
        coords.place(self.root, self.room1, (0, 0, 0))

    def dig(self, **fields):
        effect = {"type": "create_room"}
        effect.update(fields)
        R.add(self.root, R.blank(
            action="read", phase=R.CARRY_OUT, scope={"world": True},
            name="digging opens a way", effects=[effect]))

    def ways(self):
        return [obj for obj in self.room1.contents
                if getattr(obj, "destination", None) is not None]

    def test_a_rule_can_open_a_way(self):
        self.dig(direction="down", why="dug out of the packed earth")
        self.try_it("read book")
        self.assertEqual([w.key for w in self.ways()], ["down"])

    def test_and_the_room_behind_it_is_not_built_yet(self):
        """
        The whole of what keeps this free. It is built when somebody goes
        through, by the generator that builds every other room.
        """
        self.dig(direction="down", why="dug out of the packed earth")
        self.try_it("read book")
        way = self.ways()[0]
        self.assertTrue(way.db.pending_generation)
        self.assertIs(way.destination, self.room1)

    def test_the_reason_is_what_the_generator_will_read(self):
        """
        `destination_hint` is the field `generate_connected_room` already
        honours to keep a door's promise and the room behind it consistent.
        """
        self.dig(direction="down",
                 why="walled with strut and heat-shield tile")
        self.try_it("read book")
        self.assertEqual(self.ways()[0].db.destination_hint,
                         "walled with strut and heat-shield tile")

    def test_a_way_may_be_called_something_of_its_own(self):
        self.dig(direction="down", exit="burrow", why="dug out")
        self.assertNotIn("burrow", [w.key for w in self.ways()])
        self.try_it("read book")
        self.assertEqual([w.key for w in self.ways()], ["burrow"])

    def test_with_no_direction_named_any_free_one_will_do(self):
        self.dig(why="hacked through the undergrowth")
        self.try_it("read book")
        self.assertEqual(len(self.ways()), 1)

    def test_digging_where_there_is_already_a_way_does_nothing(self):
        """
        A rule about a shaft means the shaft. Digging down when down is
        already a staircase should fail rather than quietly dig sideways.
        """
        from typeclasses.exits import AIExit

        worldgen._make_exit(AIExit, "down", self.room1, self.room1,
                            pending=True)
        before = len(self.ways())
        self.dig(direction="down", why="dug out")
        self.try_it("read book")
        self.assertEqual(len(self.ways()), before)

    def test_a_room_with_no_coordinates_opens_nothing(self):
        """
        Free ground is read off the map. A room that never had a place on it
        cannot be dug out of, and saying so beats guessing.
        """
        self.root.attributes.remove("coord")
        self.dig(direction="down", why="dug out")
        self.try_it("read book")
        self.assertEqual(self.ways(), [])
