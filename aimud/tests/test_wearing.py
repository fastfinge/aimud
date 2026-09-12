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
from evennia.utils.test_resources import EvenniaCommandTest

from world import clothing, referents


@tag("world")
class Wearing(EvenniaCommandTest):
    """A coat, a wearer, and somebody watching them."""

    def setUp(self):
        super().setUp()
        self.room1.db.world_root = self.room1
        self.room1.db.is_world_root = True
        self.coat = self.obj1
        self.coat.key = "coat"
        self.coat.location = self.char1
        self.coat.db.kinds = ["clothing"]
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
class GearWield(EvenniaCommandTest):
    """gear.wield has the identical fix."""

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