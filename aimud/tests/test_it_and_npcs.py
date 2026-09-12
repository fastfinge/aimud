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


@tag("world")
class WhatAnNpcDoesReadsPerWatcher(EvenniaTest, Stage):
    """
    The bug as it was reported: an NPC narrating itself by name forever.

        Olara Voss says, "See this? One pry, one pull."
        Olara Voss picks up forged iron crowbar.
        Olara Voss gives forged iron crowbar to Raldor.

    Two things are wrong with that and they are one thing. `get` and `give`
    built their own sentence, so no watcher could be shown "she" and the
    person being handed the crowbar could not be shown "you"; and speech
    established no centre, so even a rendered line afterwards had nothing to
    be a pronoun about. `_acted` fixes the first and `events.noticed` the
    second.

    Then the same report again, about the lines that were left:

        Garrick Pyre says, "Let's see what this ore can make."
        Garrick Pyre says, "Cold iron doesn't sing until it's burning."

    Speech and emotes were still sentences built here, so a speaker holding
    the floor for a dozen lines was named in full on every one of them. They
    are templates now too, which is also what makes "they say" possible for
    a they/them character.
    """

    def setUp(self):
        super().setUp()
        self.rooted()
        from evennia import create_object
        from world import pronouns

        from typeclasses.npcs import NPC

        self.olara = create_object(NPC, key="Olara Voss", location=self.room1)
        self.olara.db.is_npc = True
        pronouns.give(self.olara, "she", self.room1)
        self.crowbar = self.obj1
        self.crowbar.key = "crowbar"
        self.crowbar.location = self.room1
        self.raldor = self.char1
        self.raldor.key = "Raldor"
        self.watcher = self.char2
        for who in (self.raldor, self.watcher):
            referents.clear(who)
        self.heard = {}
        for who in (self.raldor, self.watcher):
            self.heard[who] = []
            who.msg = lambda text="", _who=who, **kw: \
                self.heard[_who].append(str(text))

    def does(self, tool, **args):
        self.olara._execute_one(tool, args, self.room1)

    def test_the_first_thing_she_does_names_her(self):
        """Nothing has been said yet, so there is no centre to carry."""
        self.does("get", object_name="crowbar")
        self.assertEqual(self.heard[self.watcher],
                         ["Olara Voss picks up the crowbar."])

    def test_but_after_she_has_spoken_she_is_she(self):
        self.does("say", message="See this? One pry, one pull.")
        self.does("get", object_name="crowbar")
        self.assertEqual(self.heard[self.watcher][-1],
                         "She picks up the crowbar.")

    def test_an_emote_carries_the_same_attention(self):
        self.does("emote", action="turns the crowbar over once")
        self.does("get", object_name="crowbar")
        self.assertEqual(self.heard[self.watcher][-1],
                         "She picks up the crowbar.")

    def test_whoever_is_handed_it_reads_you(self):
        self.does("get", object_name="crowbar")
        self.does("give", object_name="crowbar", recipient="Raldor")
        self.assertEqual(self.heard[self.raldor][-1],
                         "She gives the crowbar to you.")

    def test_and_everybody_else_reads_the_name(self):
        self.does("get", object_name="crowbar")
        self.does("give", object_name="crowbar", recipient="Raldor")
        self.assertEqual(self.heard[self.watcher][-1],
                         "She gives the crowbar to Raldor.")

    def test_the_thing_is_definite_and_no_slot_is_left_raw(self):
        """
        The two ways a template reaches a player wrong: an undetermined noun
        ("picks up crowbar") and a slot nothing filled ("{direct}").
        """
        self.does("get", object_name="crowbar")
        self.does("give", object_name="crowbar", recipient="Raldor")
        for lines in self.heard.values():
            for line in lines:
                self.assertNotIn("{", line)
                self.assertIn("the crowbar", line)

    def test_she_is_not_told_her_own_line(self):
        self.does("get", object_name="crowbar")
        self.assertIsNone(referents.recall(self.olara, "her"))

    def test_the_first_thing_she_says_names_her(self):
        self.does("say", message="Let's see what this ore can make.")
        self.assertEqual(
            self.heard[self.watcher],
            ['Olara Voss says, "|wLet\'s see what this ore can make.|n"'])

    def test_and_the_next_line_is_she(self):
        """The report: a speaker holding the floor, named on every line."""
        self.does("say", message="Cold iron doesn't sing until it's burning.")
        self.does("say", message="Now I can handle it right.")
        self.assertEqual(self.heard[self.watcher][-1],
                         'She says, "|wNow I can handle it right.|n"')

    def test_an_emote_reads_the_same_way(self):
        self.does("say", message="Watch this.")
        self.does("emote", action="grasps the tongs, testing the weight")
        self.assertEqual(self.heard[self.watcher][-1],
                         "She grasps the tongs, testing the weight")

    def test_and_its_verb_agrees_with_a_they_them_speaker(self):
        """
        What a hand-written sentence could never do: the emote comes back
        conjugated for one person, and has to read correctly for anybody.
        """
        from world import pronouns

        pronouns.give(self.olara, "they", self.room1)
        self.does("say", message="Watch this.")
        self.does("emote", action="grasps the tongs, testing the weight")
        self.assertEqual(self.heard[self.watcher][-1],
                         "They grasp the tongs, testing the weight")

    def test_a_they_them_speaker_says_rather_than_saying(self):
        self.does("say", message="Watch this.")
        from world import pronouns

        pronouns.give(self.olara, "they", self.room1)
        self.does("say", message="Now watch this.")
        self.assertEqual(self.heard[self.watcher][-1],
                         'They say, "|wNow watch this.|n"')

    def test_speech_still_makes_the_speaker_her(self):
        """
        The table the parser reads, which `events.noticed` used to write for
        this path and `render` writes now. "hug her" has to reach Olara.
        """
        self.does("say", message="Watch this.")
        self.assertIs(referents.recall(self.watcher, "her"), self.olara)
