"""
A character's emote, whatever shape the model wrote it in.

Found in the first soak of the tool-loop branch, all four from one world of
fairies:

    She She glides closer, wings trailing faint glitter.
    She wings fluttering in anticipation
    Melia Bounces over to Sampson and loops an arm through his, leaning in
    close enough that my pink gelatinous shoulder brushes his sleeve

Each is a model writing an emote in an ordinary shape -- its own pronoun in
front, a phrase with no verb, its name and the first person -- and the game
splicing it onto "{actor} " as though it were a bare verb.
"""

from django.test import SimpleTestCase, tag
from evennia import create_object

from tests.base import GameTest
from world import events


@tag("unit")
class ThePoseAsATemplate(SimpleTestCase):

    def test_a_bare_verb_is_what_it_always_was(self):
        self.assertEqual(events.pose("nods solemnly"), "{actor} nods solemnly")

    def test_a_pronoun_in_front_is_taken_off(self):
        self.assertEqual(
            events.pose("She glides closer, wings trailing faint glitter."),
            "{actor} glides closer, wings trailing faint glitter.")

    def test_a_phrase_about_a_part_of_them_is_theirs(self):
        self.assertEqual(events.pose("wings fluttering in anticipation"),
                         "{actor's} wings fluttering in anticipation")

    def test_a_possessive_in_front_is_theirs(self):
        self.assertEqual(events.pose("Her eyes narrow."),
                         "{actor's} eyes narrow.")

    def test_something_they_are_doing_is_something_they_are_doing(self):
        self.assertEqual(events.pose("smiling warmly"),
                         "{actor} $pconj(be) smiling warmly")

    def test_the_first_person_is_them(self):
        self.assertEqual(events.pose("tucks my hair behind my ear"),
                         "{actor} tucks {actor.adjective} hair behind "
                         "{actor.adjective} ear")

    def test_but_not_inside_what_they_say(self):
        self.assertEqual(events.pose('sighs, "my dear, my dear"'),
                         '{actor} sighs, "my dear, my dear"')

    def test_a_possessive_is_never_repaired_into_a_verb(self):
        self.assertEqual(events.repair("{actor's} eyes narrow."),
                         "{actor's} eyes narrow.")


@tag("world")
class WhatTheRoomReads(GameTest):

    def setUp(self):
        super().setUp()
        from typeclasses.npcs import NPC
        from world import pronouns

        self.root = self.room1
        self.root.db.world_root = self.root
        self.root.db.is_world_root = True
        self.melia = create_object(NPC, key="Melia", location=self.root)
        pronouns.give(self.melia, "she", self.root)

    def read(self, action):
        template = events.pose(action, self.melia, self.root)
        event = events.Event(actor=self.melia, room=self.root, verb="emote",
                             room_template=template)
        return events.render(events.repair(template), self.char1, event)

    def test_she_she(self):
        said = self.read("She glides closer, wings trailing faint glitter.")
        self.assertNotIn("She She", said)
        self.assertNotIn("she she", said.lower())
        self.assertIn("glides closer, wings trailing faint glitter", said)

    def test_she_wings(self):
        said = self.read("wings fluttering in anticipation")
        self.assertIn("wings fluttering in anticipation", said)
        self.assertNotIn("She wings", said)
        self.assertNotIn("Melia wings", said)

    def test_melia_bounces_with_my_shoulder(self):
        said = self.read("Melia Bounces over to Sampson and loops an arm "
                         "through his, leaning in close enough that my pink "
                         "gelatinous shoulder brushes his sleeve")
        self.assertIn("Melia bounces over to Sampson", said)
        self.assertNotIn("Melia Melia", said)
        self.assertNotIn("my pink", said)
        self.assertIn("her pink gelatinous shoulder", said)
