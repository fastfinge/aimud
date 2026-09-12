"""
"It" after the game's own commands, and pronouns for people who talk.

Two bugs found in play, both of the same shape: the referents table is
written by `verbs` and by `events`, and anything that reaches a player
WITHOUT going through either leaves the table untouched. So the next "it" or
"her" means whatever it meant before -- usually nothing.

* `get pipe` then `drop it` said "You aren't carrying it." `get` and `drop`
  are Evennia's own commands wearing a subclass, and neither noted what it
  had just acted on nor resolved a pronoun somebody typed.

* An NPC's speech and emotes go out through `msg_contents` from
  `_execute_one`, which is not an event, so twenty lines of Barnaby talking
  left "him" meaning nobody.
"""

from django.test import tag
from evennia.utils.test_resources import EvenniaCommandTest, EvenniaTest

from world import referents


class Stage:
    """A world root, so pronoun sets have somewhere to live."""

    def rooted(self):
        self.room1.db.world_root = self.room1
        self.room1.db.is_world_root = True
        referents.clear(self.char1)
        return self.room1


@tag("world")
class ItAfterGetAndDrop(EvenniaCommandTest, Stage):
    """
    The bug as it was reported: `get pipe`, `drop it`.

    `it` has to mean the pipe afterwards, and the only way it can is if
    picking something up is recorded the way every other verb's binding is.
    """

    def setUp(self):
        super().setUp()
        self.rooted()
        self.pipe = self.obj1
        self.pipe.key = "pipe"

    def test_getting_something_makes_it_it(self):
        from commands.look_take_cmds import CmdAIGet

        self.pipe.location = self.room1
        self.call(CmdAIGet(), "pipe")
        self.assertIs(referents.recall(self.char1, "it"), self.pipe)

    def test_and_then_dropping_it_works(self):
        """
        End to end, in the words that were typed. This is the report.
        """
        from commands.drop_cmds import CmdAIDrop
        from commands.look_take_cmds import CmdAIGet

        self.pipe.location = self.room1
        self.call(CmdAIGet(), "pipe")
        said = self.call(CmdAIDrop(), "it")
        self.assertNotIn("aren't carrying", said)
        self.assertIs(self.pipe.location, self.room1)

    def test_dropping_something_leaves_it_meaning_that(self):
        from commands.drop_cmds import CmdAIDrop

        self.pipe.location = self.char1
        self.call(CmdAIDrop(), "pipe")
        self.assertIs(referents.recall(self.char1, "it"), self.pipe)

    def test_a_pronoun_with_nothing_behind_it_is_refused_plainly(self):
        """
        Not a crash and not a guess: "it" meaning nothing is a sentence the
        player can act on.
        """
        from commands.drop_cmds import CmdAIDrop

        said = self.call(CmdAIDrop(), "it")
        self.assertTrue(said.strip())

    def test_them_works_for_a_plural_name(self):
        from commands.look_take_cmds import CmdAIGet

        self.pipe.key = "coins"
        self.pipe.location = self.room1
        self.call(CmdAIGet(), "coins")
        self.assertIs(referents.recall(self.char1, "them"), self.pipe)


@tag("world")
class PronounsForSomebodyTalking(EvenniaTest, Stage):
    """
    An NPC that says something has referred to itself.

    Twenty lines of Barnaby Royston pouring pints left "him" meaning nobody,
    because speech and emotes go out through `msg_contents` rather than as
    events. Whatever a player is shown, the table has to know about.
    """

    def setUp(self):
        super().setUp()
        self.rooted()
        from evennia import create_object
        from world import pronouns

        from typeclasses.npcs import NPC

        self.npc = create_object(NPC, key="Barnaby Royston",
                                 location=self.room1)
        self.npc.db.is_npc = True
        pronouns.give(self.npc, "he", self.room1)

    def speaks(self, tool, args):
        self.npc._execute_one(tool, args, self.room1)

    def test_saying_something_makes_the_speaker_him(self):
        self.speaks("say", {"message": "Welcome back."})
        self.assertIs(referents.recall(self.char1, "him"), self.npc)

    def test_an_emote_does_too(self):
        self.speaks("emote", {"action": "taps a thick finger on the bar top"})
        self.assertIs(referents.recall(self.char1, "him"), self.npc)

    def test_and_the_speaker_is_not_told_about_themselves(self):
        """
        A table is per viewer. An NPC's own "him" should not be set by its
        own talking -- it did not watch anybody do anything.
        """
        self.speaks("say", {"message": "Welcome back."})
        self.assertIsNone(referents.recall(self.npc, "him"))

    def test_nothing_said_notes_nothing(self):
        self.speaks("say", {"message": "   "})
        self.assertIsNone(referents.recall(self.char1, "him"))

    def test_an_npc_picking_something_up_makes_it_it(self):
        """
        An NPC acting on a thing has made that thing "it", the same as a
        player would -- "he" means Barnaby and "it" means the tankard.
        """
        self.obj1.key = "tankard"
        self.obj1.location = self.room1
        self.npc._execute_one("get", {"object_name": "tankard"}, self.room1)
        self.assertIs(referents.recall(self.char1, "it"), self.obj1)
        self.assertIs(referents.recall(self.char1, "him"), self.npc)

    def test_and_a_speaker_is_not_the_last_thing_referred_to(self):
        """
        "get all of them" after a barman talks must not mean barmen: what
        somebody said is not a thing that can be picked up.
        """
        self.speaks("say", {"message": "Welcome back."})
        self.assertIsNot(referents.last(self.char1), self.npc)


@tag("world")
class PronounsForAPlayerTalking(EvenniaTest, Stage):
    """
    The same gap on the player's side of it.

    A player who says something or poses is as much "her" afterwards as an
    NPC is, and by the same argument: neither goes through `events.render`,
    which was the only thing writing the table.
    """

    def setUp(self):
        super().setUp()
        self.rooted()
        from world import pronouns

        self.jessica = self.char1
        self.jessica.key = "Jessica"
        self.watcher = self.char2
        pronouns.give(self.jessica, "she", self.room1)
        referents.clear(self.watcher)

    def test_saying_something_makes_the_speaker_her(self):
        self.jessica.at_say("Evening, all.")
        self.assertIs(referents.recall(self.watcher, "her"), self.jessica)

    def test_a_pose_does_too(self):
        """Driven through the command, not through the helper it calls."""
        from commands.social_cmds import CmdAIEmote

        cmd = CmdAIEmote()
        cmd.caller = self.jessica
        cmd.args = " bows deeply."
        cmd.func()
        self.assertIs(referents.recall(self.watcher, "her"), self.jessica)

    def test_and_the_speaker_is_not_told_about_themselves(self):
        self.jessica.at_say("Evening, all.")
        self.assertIsNone(referents.recall(self.jessica, "her"))
