"""
Wearing things, and being refused.

The bug: `_refuse` returned "" where an event goes, and `events.show` sent
that to `deliver`, which asked a string for its `.actor`. Every refusal path
and the success path both died on it, so `wear` crashed outright on every
path — completely dead.

The fix: `_refuse` returns `None` instead of `""`. `events.show` guards
`None` and not `""`, so the empty string no longer falls through to
`deliver`, which asked it for its `.actor` and died. Every refusal in the
module now works, and the success path through the same delivery also works.
"""

from django.test import tag

from tests.base import GameCommandTest
from world import clothing, referents


@tag("world")
class Wearing(GameCommandTest):
    """A coat, a wearer, and somebody watching them."""

    loose_objects = 1

    def setUp(self):
        super().setUp()
        self.room1.db.world_root = self.room1
        self.room1.db.is_world_root = True
        self.coat = self.obj1
        self.coat.key = "coat"
        self.coat.location = self.char1
        self.coat.db.kinds = ["clothing"]
        # What makes a thing wearable is the affordance and nothing else --
        # `clothing.wearable` reads `verbs.affordances`, which reads this map.
        # A kind of "clothing" and a `clothing_type` are how the coat is
        # ordered and limited once it is a garment; neither is what lets it
        # become one. `clothing.create` writes this for every coat the world
        # makes, from the kind, and a fixture that skips it has built an
        # object no amount of clothing_type will let anybody put on.
        self.coat.db.affordances = {"wear": True}
        self.coat.db.clothing_type = "outerwear"
        referents.clear(self.char1)

    # -- the fix ------------------------------------------------------

    def test_wearing_something_works_at_all(self):
        from commands.clothing_cmds import CmdWear

        said = self.call(CmdWear(), "coat")
        self.assertIn("put on", said)
        self.assertTrue(self.coat.db.worn)

    def test_and_a_refusal_is_a_sentence(self):
        """
        The original bug: `_refuse` returned "" and the command crashed on
        every path. Now it returns `None`, and `show` guards that.
        """
        from commands.clothing_cmds import CmdWear

        self.coat.db.affordances = {}
        self.coat.db.clothing_type = None
        self.coat.db.kinds = []
        said = self.call(CmdWear(), "coat")
        self.assertTrue(said.strip())
        self.assertFalse(self.coat.db.worn)

    def test_taking_it_off_works(self):
        from commands.clothing_cmds import CmdRemove, CmdWear

        self.call(CmdWear(), "coat")
        said = self.call(CmdRemove(), "coat")
        self.assertTrue(said.strip())
        self.assertFalse(self.coat.db.worn)

    def test_and_being_refused_the_removal_says_so(self):
        from commands.clothing_cmds import CmdRemove

        said = self.call(CmdRemove(), "coat")
        self.assertIn("not wearing", said)

    # -- pronouns -------------------------------------------------------

    def test_wearing_something_makes_it_it(self):
        from commands.clothing_cmds import CmdWear

        self.call(CmdWear(), "coat")
        self.assertIs(referents.recall(self.char1, "it"), self.coat)

    def test_and_remove_it_works_after_wearing_it(self):
        from commands.clothing_cmds import CmdRemove, CmdWear

        self.call(CmdWear(), "coat")
        said = self.call(CmdRemove(), "it")
        self.assertNotIn("not wearing", said)
        self.assertFalse(self.coat.db.worn)

    def test_a_pronoun_meaning_nothing_is_refused_plainly(self):
        from commands.clothing_cmds import CmdWear

        said = self.call(CmdWear(), "it")
        self.assertTrue(said.strip())


@tag("world")
class GearWield(GameCommandTest):
    """gear.wield has the identical fix."""

    loose_objects = 1

    def setUp(self):
        super().setUp()
        self.room1.db.world_root = self.room1
        self.sword = self.obj1
        self.sword.key = "sword"

    def test_a_refusal_from_gear_is_a_sentence(self):
        from world import gear

        self.sword.location = self.room1
        ok, actor_text, event = gear.wield(self.char1, self.sword)
        self.assertFalse(ok)
        self.assertTrue(actor_text)
        from world import events

        events.show(actor_text, event, self.char1)

@tag("world")
class HowMuchYouMayWear(GameCommandTest):
    """
    The limits, which are rules now rather than constants in a contrib.

    "One hat" and "no more than twenty things" say what sort of world this is
    -- one world's guard is buried under six coats and another's has a rule
    against hats indoors -- so they are check rules a world can read and
    change, asked through `attempt.permitted` the way `ownership` and
    `relations` already ask.
    """

    def setUp(self):
        super().setUp()
        self.root = self.room1
        self.room1.db.world_root = self.root
        self.room1.db.is_world_root = True
        from world import rulesets

        rulesets.seed(self.root)

    def hat(self, key="felt hat"):
        from evennia import create_object

        hat = create_object("typeclasses.objects.Object", key=key,
                            location=self.char1)
        hat.db.kinds = ["hat.n.01"]
        hat.db.affordances = {"wear": True}
        hat.db.clothing_type = "hat"
        return hat

    def test_one_hat_goes_on(self):
        worn, said, _event = clothing.put_on(self.char1, self.hat())
        self.assertTrue(worn, said)

    def test_a_second_hat_is_refused_by_the_rule(self):
        clothing.put_on(self.char1, self.hat("straw hat"))
        worn, said, _event = clothing.put_on(self.char1, self.hat("felt hat"))
        self.assertFalse(worn)
        self.assertIn("hat", said.lower())

    def test_and_a_world_that_suspends_the_rule_may_wear_both(self):
        """
        Which is the whole point of the limits being rules: a world says
        otherwise by suspending one, and nothing has to be patched.
        """
        from world import rulebooks

        rule = next(r for r in rulebooks.all_rules(self.root)
                    if r["name"] == "you may wear only one hat")
        rulebooks.set_listed(self.root, rule["id"], False)
        clothing.put_on(self.char1, self.hat("straw hat"))
        worn, said, _event = clothing.put_on(self.char1, self.hat("felt hat"))
        self.assertTrue(worn, said)

    def test_the_refusals_that_are_the_mechanic_stay_in_the_mechanic(self):
        """
        A thing you are not holding, or already have on, is not a limit
        anybody would want to change.
        """
        from evennia import create_object

        loose = create_object("typeclasses.objects.Object", key="cloak",
                              location=self.room1)
        loose.db.affordances = {"wear": True}
        worn, said, _event = clothing.put_on(self.char1, loose)
        self.assertFalse(worn)
        self.assertIn("holding", said)
