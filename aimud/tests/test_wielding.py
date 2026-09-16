"""
Taking something in hand, and the verb that had to ask permission.

`world.gear` takes the wielding verbs before an attempt reaches a model,
exactly as the clothing layer takes `wear`. It declined anything whose noun
this world does not think of as a thing to wield -- and that test was being
applied to every verb it owns, including the one that cannot mean anything
else.

Which is worse than it sounds, because a thing is wieldable only if its
kind's affordance map holds `wield`, and most kinds say nothing at all. The
taxonomy floor speaks for weapons and for nothing else, so a lantern, a
crowbar, a torch and a broom all come out of the generators with an empty map.
`wield the crowbar` therefore declined the mechanic and bought a model call to
invent a meaning for a word the game already answers -- and whatever the model
said, the crowbar was not in anybody's hand afterwards.

"Hold" is the verb that genuinely means two things: holding a sword is
wielding it and holding somebody's hand is not. That one still asks, which is
the whole reason the test exists.
"""

from django.test import tag
from evennia.utils.test_resources import EvenniaTest

from tests.support import FakeSponsor
from world import gear


@tag("world")
class Wielding(EvenniaTest):
    """A crowbar nobody ever said anything about, and a world to swing it in."""

    def setUp(self):
        super().setUp()
        self.room1.db.world_root = self.room1
        self.room1.db.is_world_root = True
        self.room1.db.world_description = "A ruined keep."
        self.crowbar = self.obj1
        self.crowbar.key = "crowbar"
        self.crowbar.location = self.char1
        # The state every generated tool is actually in: a kind the taxonomy
        # has no opinion about, so nothing ever wrote `wield` down.
        self.crowbar.db.affordances = {}

    def attempted(self, raw, actor=None):
        from world import attempt as attempt_mod

        said = []
        attempt_mod.attempt(
            actor or self.char1, raw, FakeSponsor(),
            on_message=lambda actor_text, room_text=None:
                said.append(actor_text or ""))
        return "\n".join(s for s in said if s)

    # -- the fix ------------------------------------------------------

    def test_wielding_a_thing_nobody_marked_wieldable(self):
        said = self.attempted("wield crowbar")
        self.assertTrue(self.crowbar.db.wielded, said)
        self.assertIn("in hand", said)

    def test_the_spellings_that_fold_onto_it(self):
        for spelling in ("brandish crowbar", "equip crowbar"):
            self.crowbar.attributes.remove("wielded")
            self.attempted(spelling)
            self.assertTrue(self.crowbar.db.wielded, spelling)

    def test_and_lowering_it_again(self):
        self.attempted("wield crowbar")
        said = self.attempted("unwield crowbar")
        self.assertFalse(self.crowbar.db.wielded)
        self.assertIn("lower", said.lower())

    # -- what still declines ------------------------------------------

    def test_hold_still_asks_about_the_noun(self):
        """
        The verb that means two things keeps its test. Nothing this world
        calls wieldable is named, so the attempt goes on to be learned as
        whatever holding a crowbar means here.
        """
        self.assertFalse(gear.handle(self.char1, "hold",
                                     {"direct": self.crowbar},
                                     lambda text, event=None: None))

    def test_and_holding_a_person_is_never_this(self):
        self.assertFalse(gear.handle(self.char1, "hold",
                                     {"direct": self.char2},
                                     lambda text, event=None: None))

    def test_but_hold_takes_a_thing_this_world_calls_wieldable(self):
        self.crowbar.db.affordances = {"wield": True}
        said = self.attempted("hold crowbar")
        self.assertTrue(self.crowbar.db.wielded, said)

    # -- the limits the mechanic already had --------------------------

    def test_what_you_are_not_carrying_cannot_be_taken_in_hand(self):
        self.crowbar.location = self.room1
        said = self.attempted("wield crowbar")
        self.assertFalse(self.crowbar.db.wielded)
        self.assertIn("not carrying", said.lower())

    def test_two_hands_and_no_more(self):
        from evennia import create_object

        held = []
        for name in ("mallet", "chisel", "wedge"):
            made = create_object("typeclasses.objects.Object", key=name,
                                 location=self.char1)
            made.db.affordances = {}
            held.append(made)
            self.attempted(f"wield {name}")
        self.assertEqual([obj for obj in held if obj.db.wielded], held[:2])
        self.assertFalse(held[2].db.wielded)
