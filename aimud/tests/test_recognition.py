"""
Names read back out of speech: who was meant, and who was spoken to.

The acceptance table is the plan's, and its worst rows are the ones that
must find nothing. A false mention becomes an annotation that recall trusts,
so an NPC called Hope must not be named by "I hope so", somebody in another
room must not be named at all, and two Tams must cancel each other out.
"""

from unittest import mock

from django.test import SimpleTestCase, tag
from evennia import create_object

from tests.base import GameTest
from world import recognition, referents


@tag("world")
class Hearing(GameTest):
    characters = 2
    loose_objects = 1
    second_room = True

    def setUp(self):
        super().setUp()
        self.room1.db.world_root = self.room1
        self.speaker = self.char1
        self.speaker.key = "Samuel"
        self.raldor = self.char2
        self.raldor.key = "Raldor"
        self.lamp = self.obj1
        self.lamp.key = "lamp"
        referents.clear(self.speaker)

    def npc(self, key, room=None):
        from typeclasses.npcs import NPC

        made = create_object(NPC, key=key, location=room or self.room1)
        made.db.is_npc = True
        return made

    def heard(self, text, **kwargs):
        return recognition.recognise(text, speaker=self.speaker,
                                     room=self.room1, **kwargs)

    def only(self, text, **kwargs):
        found = self.heard(text, **kwargs)
        self.assertEqual(len(found), 1, found)
        return found[0]

    def test_a_greeting_addresses(self):
        mention = self.only("Hello, Raldor.")
        self.assertIs(mention.ref, self.raldor)
        self.assertTrue(mention.addressed)
        self.assertEqual(mention.confidence, recognition.FULL_NAME)

    def test_every_way_of_being_spoken_to(self):
        for text in ("Raldor, come here.", "Is that you, Raldor?",
                     "Thanks Raldor!", "Oh hey, Raldor, sit down."):
            with self.subTest(text=text):
                self.assertTrue(self.only(text).addressed)

    def test_talking_about_somebody_only_mentions_them(self):
        for text in ("I think Raldor took it.", "Raldor took it.",
                     "Tell Raldor I said hi"):
            with self.subTest(text=text):
                self.assertFalse(self.only(text).addressed)

    def test_the_speaker_is_never_a_mention(self):
        self.assertEqual(self.heard("Samuel bows."), [])

    def test_a_thing_can_be_mentioned_but_not_spoken_to(self):
        mention = self.only("Pass me the lamp!")
        self.assertIs(mention.ref, self.lamp)
        self.assertFalse(mention.addressed)

    def test_a_name_that_is_a_word_needs_a_capital(self):
        hope = self.npc("Hope")
        self.assertEqual(self.heard("I hope so."), [])
        self.assertEqual(self.heard("Hope you are well."), [])
        mention = self.only("Hope, come here.")
        self.assertIs(mention.ref, hope)
        self.assertTrue(mention.addressed)
        self.assertEqual(mention.confidence, recognition.COMMON_WORD)

    def test_one_word_of_a_name_answers_for_it(self):
        barnaby = self.npc("Barnaby Royston")
        mention = self.only("Barnaby, a pint.")
        self.assertIs(mention.ref, barnaby)
        self.assertEqual(mention.confidence, recognition.PART_NAME)

    def test_but_the_whole_name_is_surer(self):
        self.npc("Barnaby Royston")
        self.assertEqual(self.only("I saw Barnaby Royston.").confidence,
                         recognition.FULL_NAME)

    def test_two_people_answering_to_one_word_name_neither(self):
        self.npc("Tam Ash")
        self.npc("Tam Birch")
        self.assertEqual(self.heard("Tam, over here."), [])

    def test_somebody_elsewhere_is_not_named(self):
        zorvath = self.npc("Zorvath", room=self.room2)
        self.assertEqual(self.heard("Zorvath was here."), [])
        referents.note(self.speaker, zorvath, self.room1)
        self.assertIs(self.only("Zorvath was here.").ref, zorvath)

    def test_a_whisper_addresses_its_listener_whatever_it_says(self):
        mention = self.only("psst", targets=[self.raldor])
        self.assertTrue(mention.addressed)
        self.assertEqual(mention.confidence, recognition.BOUND)

    def test_the_memory_shape(self):
        found = self.heard("Hello, Raldor. Is the lamp lit?")
        self.assertEqual(
            sorted(recognition.about(found)),
            sorted([("Raldor", f"#{self.raldor.id}", recognition.FULL_NAME),
                    ("lamp", f"#{self.lamp.id}", recognition.FULL_NAME)]))
        self.assertEqual(recognition.addressed(found),
                         [("Raldor", f"#{self.raldor.id}", recognition.FULL_NAME)])


@tag("world")
class WhereItGoes(GameTest):
    characters = 2

    def setUp(self):
        super().setUp()
        self.room1.db.world_root = self.room1
        self.char1.key = "Samuel"
        self.char2.key = "Raldor"

    def test_speech_is_remembered_with_who_it_was_about(self):
        from world.npc_gen import notify_npcs

        with mock.patch("world.memory.record_room_event") as recorded:
            notify_npcs(self.room1, "say", "Samuel", "Hello, Raldor.",
                        exclude=self.char1, actor=self.char1)
        kwargs = recorded.call_args.kwargs
        wanted = ("Raldor", f"#{self.char2.id}", recognition.FULL_NAME)
        self.assertEqual(kwargs["about"], [wanted])
        self.assertEqual(kwargs["addressed"], [wanted])

    def test_an_action_already_knows_who_it_was_about(self):
        from world.npc_gen import notify_npcs

        about = [("Raldor", f"#{self.char2.id}", 1.0)]
        with mock.patch("world.memory.record_room_event") as recorded:
            notify_npcs(self.room1, "action", "Samuel", "Samuel hugs Raldor.",
                        actor=self.char1, about=about)
        self.assertEqual(recorded.call_args.kwargs["about"], about)
        self.assertEqual(recorded.call_args.kwargs["addressed"], [])

    def heard_from(self, tool, args):
        """What every character's memory was handed when an NPC used a tool."""
        from typeclasses.npcs import NPC

        # No pronoun set given, so Barnaby goes by they/them -- and by name is
        # still one person: "Barnaby waves", not "Barnaby wave".
        barnaby = create_object(NPC, key="Barnaby", location=self.room1)
        barnaby.db.is_npc = True
        written = []

        def capture(character, text, kind="event", importance=0.5, about=(),
                    metadata=None, addressed=()):
            written.append({"who": character, "text": text, "kind": kind,
                            "about": list(about),
                            "addressed": list(addressed)})

        with mock.patch("world.memory.available", return_value=True), \
                mock.patch("world.memory.remember", capture):
            barnaby._execute_one(tool, args, self.room1)
        return [entry for entry in written if entry["who"] is self.char2]

    def test_a_player_remembers_what_an_npc_said(self):
        """
        The documented promise -- what a character has witnessed is written to
        their memory -- which NPC speech never kept: it told the other NPCs
        and nobody else.
        """
        heard = self.heard_from("say", {"message": "Hello, Raldor."})
        self.assertEqual(len(heard), 1, heard)
        self.assertEqual(heard[0]["text"], 'Barnaby said, "Hello, Raldor."')
        self.assertEqual(heard[0]["kind"], "witnessed")
        wanted = [("Raldor", f"#{self.char2.id}", recognition.FULL_NAME)]
        self.assertEqual(heard[0]["about"], wanted)
        self.assertEqual(heard[0]["addressed"], wanted)

    def test_and_what_an_npc_did(self):
        heard = self.heard_from("emote", {"action": "waves at Raldor"})
        self.assertEqual(len(heard), 1, heard)
        self.assertEqual(heard[0]["text"], "Barnaby waved at Raldor")

    def test_an_npc_knows_when_it_was_the_one_spoken_to(self):
        from typeclasses.npcs import NPC

        olara = create_object(NPC, key="Olara Voss", location=self.room1)
        self.assertTrue(olara.spoken_to([("Olara Voss", f"#{olara.id}", 0.8)]))
        self.assertFalse(olara.spoken_to([("Raldor", f"#{self.char2.id}", 0.8)]))
        self.assertFalse(olara.spoken_to([]))


@tag("unit")
class Annotations(SimpleTestCase):
    """What mnemosyne is handed, grouped by how sure each value is."""

    def test_each_kind_is_written_at_its_own_confidence(self):
        from world import memory

        calls = []

        class Store:
            def add_many(self, **kwargs):
                calls.append((kwargs["kind"], tuple(kwargs["values"]),
                              kwargs["confidence"]))

        with mock.patch("mnemosyne.core.annotations.AnnotationStore", Store):
            memory._annotate("m1",
                             [("Raldor", "#5", 0.8), ("lamp", "#6")],
                             addressed=[("Raldor", "#5", 0.8)])
        self.assertEqual(sorted(calls), sorted([
            ("mentions", ("Raldor",), 0.8), ("mentions", ("lamp",), 1.0),
            ("dbref", ("#5",), 0.8), ("dbref", ("#6",), 1.0),
            ("addressed", ("#5",), 0.8),
        ]))

    def test_the_old_two_field_shape_still_reads(self):
        from world import memory

        self.assertEqual(list(memory._confident([("Raldor", "#5")])),
                         [("Raldor", "#5", 1.0)])
