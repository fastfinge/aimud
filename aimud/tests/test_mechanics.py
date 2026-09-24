"""
Which verbs the game answers for itself, and which a world may take back.

Four modules take verbs before any rule is consulted. Two of them are true of
every world there could be -- where a thing is, and whose it is -- and two are
decisions: `world.clothing` was taking `wear` and `cover` in a world with no
clothes in it, and `world.gear` was taking `wield` in one with nothing to
hold.

What is tested here is the switch, not the mechanics themselves: those are
`test_wearing` and `test_wielding`, and they go on passing because both
rulesets ship switched on. The point of the switch is that a world can say no.
"""

from django.test import SimpleTestCase, tag

from tests.base import GameTest
from world import clothing, mechanics, rulesets


class TheTable(SimpleTestCase):

    def test_only_what_ships_with_the_game_may_be_named(self):
        """
        The seam between a ruleset, which is data, and a plugin, which is
        code. A ruleset names a mechanic; it never supplies one.
        """
        self.assertTrue(mechanics.known("clothing"))
        self.assertFalse(mechanics.known("world.clothing"))
        self.assertFalse(mechanics.known("os.system"))

    def test_a_ruleset_naming_one_that_does_not_exist_is_refused(self):
        wrong = rulesets.problems(
            {"name": "trial", "version": 1, "means": "x",
             "mechanics": ["sorcery"]}, known={})
        self.assertIn("no mechanic called", " ".join(wrong))

    def test_the_two_nobody_may_switch_off_are_not_switchable(self):
        for name in ("ownership", "placement"):
            self.assertNotIn(name, mechanics.SWITCHABLE)

    def test_clothing_and_wielding_ship_switched_on(self):
        """
        Both are `default: true`, because on is the status quo: a world made
        before rulesets existed had them, and a reset must not take them away.
        What rulesets buy is the ability to say no, not a change of default.
        """
        for name in ("clothing", "wielding"):
            self.assertIn(name, rulesets.defaults())


@tag("world")
class SwitchingOneOff(GameTest):
    loose_objects = 1

    def setUp(self):
        super().setUp()
        self.root = self.room1
        self.root.db.is_world_root = True
        self.room1.db.world_root = self.root
        self.obj1.key = "coat"
        self.obj1.db.affordances = {"wear": True}
        self.obj1.move_to(self.char1, quiet=True)

    def names(self):
        return [name for name, _path, _parse
                in mechanics.enabled(self.root)]

    def test_a_world_that_chose_clothing_has_it(self):
        rulesets.seed(self.root)
        self.assertIn("clothing", self.names())

    def test_a_world_that_did_not_does_not(self):
        rulesets.seed(self.root, [rulesets.DEFAULT])
        self.assertNotIn("clothing", self.names())
        self.assertNotIn("wielding", self.names())

    def test_but_still_knows_where_things_are_and_whose_they_are(self):
        """Neither is a genre. Both stay on whatever a world chose."""
        rulesets.seed(self.root, [rulesets.DEFAULT])
        self.assertIn("ownership", self.names())
        self.assertIn("placement", self.names())

    def test_a_world_with_nothing_recorded_gets_everything(self):
        """
        One made before rulesets existed, or one part-way through being built.
        It had all four, and must go on having them.
        """
        self.assertEqual(rulesets.chosen(self.root), [])
        self.assertIn("clothing", self.names())

    def test_the_mechanic_takes_the_verb_when_it_is_on(self):
        rulesets.seed(self.root)
        said = []
        took = mechanics.handle(
            self.root, self.char1, "wear", {"verb": "wear", "roles": {}},
            {"direct": self.obj1},
            lambda actor_text, event=None: said.append(actor_text))
        self.assertTrue(took)
        self.assertTrue(clothing.is_worn(self.obj1))

    def test_and_hands_it_on_when_it_is_off(self):
        """
        Which is the whole point: with clothing off, `wear` is a word this
        world has not met yet, and goes on to be worked out like any other.
        """
        rulesets.seed(self.root, [rulesets.DEFAULT])
        said = []
        took = mechanics.handle(
            self.root, self.char1, "wear", {"verb": "wear", "roles": {}},
            {"direct": self.obj1},
            lambda actor_text, event=None: said.append(actor_text))
        self.assertFalse(took)
        self.assertFalse(clothing.is_worn(self.obj1))
