"""
How a thing is in the state it is in.

A state is a word from a closed vocabulary, and that is what makes it worth
having: groupable, exclusive, testable, countable, answerable-to as an alias.
What it cannot be is particular. A coat is `worn` the way every coat is worn,
and "slung over one arm" had nowhere to live.

`world.clothing` had somewhere for it -- `db.wearstyle` -- and that was the
last piece of storage clothes had that no other ruleset could have had. A
sword held point-down, a lantern raised high, a fire burning low all want the
same thing. So a state may carry a phrase, and `world.gear` is the second user
rather than a hypothetical one.

Three rules keep a style from becoming a second vocabulary nobody can test,
and each has a test here: it dies with its state, it may not name a state, and
nothing tests it.
"""

from django.test import SimpleTestCase, tag

from tests.base import GameTest
from world import clothing, gear, rulesets, verbs


@tag("world")
class AStyleRidesOnAState(GameTest):
    loose_objects = 1

    def setUp(self):
        super().setUp()
        self.root = self.room1
        self.root.db.is_world_root = True
        self.room1.db.world_root = self.root
        rulesets.seed(self.root)
        self.thing = self.obj1

    def test_it_is_kept_against_the_state_it_is_about(self):
        verbs.apply_states(self.thing, add=["burning"], world_root=self.root)
        verbs.set_style(self.thing, "burning", "low and smoky", self.root)
        self.assertEqual(verbs.style_of(self.thing, "burning"),
                         "low and smoky")
        self.assertEqual(verbs.style_of(self.thing, "wet"), "")

    def test_and_dies_with_it(self):
        """
        The rule that keeps it honest. Otherwise a coat goes on being "slung
        over one arm" while folded in a drawer.
        """
        verbs.apply_states(self.thing, add=["burning"], world_root=self.root)
        verbs.set_style(self.thing, "burning", "low and smoky", self.root)
        verbs.apply_states(self.thing, remove=["burning"],
                           world_root=self.root)
        self.assertEqual(verbs.style_of(self.thing, "burning"), "")

    def test_including_when_an_exclusive_group_ends_it(self):
        """Nobody removed anything by hand here; the group did."""
        verbs.register_state(self.root, "lit", group="lighting")
        verbs.register_state(self.root, "unlit", group="lighting")
        verbs.apply_states(self.thing, add=["lit"], world_root=self.root)
        verbs.set_style(self.thing, "lit", "guttering", self.root)
        verbs.apply_states(self.thing, add=["unlit"], world_root=self.root)
        self.assertEqual(verbs.style_of(self.thing, "lit"), "")

    def test_an_empty_style_takes_the_phrase_away(self):
        verbs.apply_states(self.thing, add=["burning"], world_root=self.root)
        verbs.set_style(self.thing, "burning", "low", self.root)
        verbs.set_style(self.thing, "burning", "", self.root)
        self.assertEqual(verbs.styles(self.thing), {})


@tag("world")
class AStyleMayNotNameAState(GameTest):
    """
    The same line `name_contradicts_states` draws, for the same reason: a
    world that writes "burning" into a style has said something no rule can
    read and nothing can undo. If it matters, it is a state.
    """

    loose_objects = 1

    def setUp(self):
        super().setUp()
        self.root = self.room1
        self.root.db.is_world_root = True
        self.room1.db.world_root = self.root
        verbs.register_state(self.root, "burning")

    def test_a_phrase_naming_one_is_refused(self):
        wrong = verbs.style_complaints("burning at one end", self.root)
        self.assertTrue(wrong)
        self.assertIn("burning", wrong[0])

    def test_and_setting_it_leaves_the_plain_state_behind(self):
        """The safe outcome: less said, never something false said."""
        verbs.apply_states(self.obj1, add=["worn"], world_root=self.root)
        self.assertEqual(
            verbs.set_style(self.obj1, "worn", "burning at one end",
                            self.root), "")
        self.assertEqual(verbs.style_of(self.obj1, "worn"), "")

    def test_a_phrase_naming_nothing_registered_is_fine(self):
        self.assertEqual(
            verbs.style_complaints("slung over one arm", self.root), [])

    def test_and_one_that_runs_on_is_not(self):
        wrong = verbs.style_complaints("x" * (verbs.STYLE_MAXLENGTH + 1),
                                       self.root)
        self.assertTrue(wrong)


@tag("world")
class WhoUsesIt(GameTest):
    """Two rulesets, which is the point of having made it general."""

    loose_objects = 1

    def setUp(self):
        super().setUp()
        self.root = self.room1
        self.root.db.is_world_root = True
        self.room1.db.world_root = self.root
        rulesets.seed(self.root)
        self.thing = self.obj1
        self.thing.move_to(self.char1, quiet=True)

    def test_clothing(self):
        self.thing.db.affordances = {"wear": True}
        clothing.put_on(self.char1, self.thing, wearstyle="slung over one arm")
        self.assertEqual(verbs.style_of(self.thing, clothing.WORN),
                         "slung over one arm")
        self.assertIn("slung over one arm",
                      clothing.describe_outfit(self.char1))

    def test_wielding(self):
        self.thing.db.affordances = {"wield": True}
        gear.wield(self.char1, self.thing, style="point-down")
        self.assertEqual(gear.wield_style(self.thing), "point-down")

    def test_and_a_rule_can_set_one(self):
        """
        Which is what makes this a ruleset's to use rather than a mechanic's.
        """
        from world import effects

        effects.apply(self.char1, self.room1, [
            {"type": "set_state", "role": "direct", "add": ["burning"],
             "styles": {"burning": "low and smoky"}}],
            bound={"direct": self.thing}, world_root=self.root)
        self.assertEqual(verbs.style_of(self.thing, "burning"),
                         "low and smoky")

    def test_a_thing_reads_with_its_style(self):
        verbs.apply_states(self.thing, add=["burning"], world_root=self.root)
        verbs.set_style(self.thing, "burning", "low and smoky", self.root)
        self.assertIn("low and smoky", verbs.condition(self.thing))


class NothingTestsIt(SimpleTestCase):

    def test_there_is_no_style_predicate(self):
        """
        Deliberately. A substring match against open text is the bug
        `world.quantity` exists to have fixed, and re-inventing it here would
        be worse for having been done on purpose. What has to be testable is
        a state; a style only has to read well.
        """
        from world import conditions

        self.assertNotIn("style", conditions.PREDICATES)
