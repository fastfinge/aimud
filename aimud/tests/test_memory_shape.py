"""
Where a memory goes, and what it says when it gets there.

Two changes, and the second is the one with consequences. The text is written
from the event rather than from what somebody typed, because recall here is
hybrid -- embeddings plus full-text -- so "hug her" was not merely a vague
memory afterwards, it was an unfindable one: it will not match a cue of
"Jessica", and the regex fact extractor that runs on every write has `i`,
`her` and `she` in its stop list, so the sentence contributed nothing either.

And the banks are carved by world rather than by character, which is weaker
isolation -- a `WHERE` clause instead of a file -- bought deliberately, for
deletion with the world, for memories that belong to a world rather than to
one person in it, and for two players in one room.

Nothing here touches mnemosyne. The parts that do are threaded and would need
a real embedding stack; what is asserted is the shape handed to it.
"""

from unittest import mock

from django.test import tag
from evennia.utils.test_resources import EvenniaTest

from world import events, memory


@tag("world")
class WhereAMemoryLives(EvenniaTest):

    def setUp(self):
        super().setUp()
        self.root = self.room1
        self.room1.db.world_root = self.root

    def test_a_bank_is_a_world(self):
        self.assertEqual(memory.bank_for(self.root),
                         f"aimud-world-{self.root.id}")

    def test_a_session_is_a_character(self):
        self.assertEqual(memory.session_for(self.char1),
                         f"char-{self.char1.id}")

    def test_two_characters_in_one_world_share_a_bank(self):
        """
        The point of the carving. An innkeeper cannot hold one memory about
        two players whose memories are in different files.
        """
        one = memory.where_for(self.char1)
        two = memory.where_for(self.char2)
        self.assertEqual(one.bank, two.bank)
        self.assertNotEqual(one.session, two.session)

    def test_the_same_character_in_another_world_is_somewhere_else(self):
        """
        The bug this fixes. One player character plays many worlds and had one
        bank, with nothing filtering by world -- so memories of the haunted
        school were recallable aboard the freighter.
        """
        here = memory.where_for(self.char1)
        self.room2.db.world_root = self.room2
        self.char1.location = self.room2
        self.assertNotEqual(memory.where_for(self.char1).bank, here.bank)

    def test_somewhere_that_is_not_a_world_has_no_bank(self):
        self.room2.db.world_root = None
        self.char1.location = self.room2
        self.assertEqual(memory.where_for(self.char1).bank, "")

    def test_a_bank_from_the_old_carving_is_orphaned_by_definition(self):
        """
        Named for a character, which is a scheme this game no longer uses.
        Whatever is in it was written against the old carving and cannot be
        read back under the new one.
        """
        with mock.patch.object(memory, "_bank_names",
                               lambda: ["aimud-char-7", "aimud-world-99"]):
            stranded = memory.orphaned_banks()
        self.assertIn("aimud-char-7", stranded)

    def test_and_a_world_that_still_exists_is_not(self):
        with mock.patch.object(
                memory, "_bank_names",
                lambda: [f"aimud-world-{self.root.id}"]):
            self.assertEqual(memory.orphaned_banks(), [])

    def test_nothing_belonging_to_anybody_else_is_ever_touched(self):
        with mock.patch.object(memory, "_bank_names",
                               lambda: ["somebody-elses-notes"]):
            self.assertEqual(memory.orphaned_banks(), [])


@tag("world")
class WhatAMemorySays(EvenniaTest):

    def setUp(self):
        super().setUp()
        self.root = self.room1
        self.room1.db.world_root = self.root
        self.written = []

        def capture(character, text, kind="event", importance=0.5,
                    about=(), metadata=None):
            self.written.append(
                {"text": text, "about": list(about),
                 "metadata": dict(metadata or {})})

        self.capture = capture

    def remember(self, **overrides):
        from world import attempt

        fields = dict(actor=self.char1, room=self.room1, verb="hug",
                      roles={"direct": self.char2}, outcome="success")
        fields.update(overrides)
        event = events.Event(**fields)
        with mock.patch("world.memory.remember", self.capture):
            attempt._remember(self.char1, event, "You hug her.")
        return self.written[-1]

    def test_the_name_is_in_the_text_not_only_the_pronoun(self):
        """
        The whole reason this is written from the event. Somebody types "hug
        her"; what goes into a full-text index has to say Char2.
        """
        written = self.remember()
        self.assertIn(self.char2.key, written["text"])

    def test_no_constant_prefix_dilutes_every_row(self):
        """
        "I did: " was on every memory in the bank, so it discriminated nothing
        in either half of a hybrid search -- and led with a word the fact
        extractor's stop list drops, which made the sentence contribute no
        fact at all.
        """
        self.assertNotIn("I did:", self.remember()["text"])

    def test_what_it_was_about_is_stated_rather_than_extracted(self):
        """
        mnemosyne's own extractor is a capitalised-word regex whose stop list
        is `he she it they him her them`. We know who was involved because
        binding resolved them.
        """
        about = self.remember()["about"]
        self.assertIn((self.char2.key, f"#{self.char2.id}"), about)

    def test_including_by_id_so_a_rename_does_not_lose_it(self):
        refs = [ref for _name, ref in self.remember()["about"]]
        self.assertIn(f"#{self.char1.id}", refs)

    def test_the_metadata_carries_what_it_was_rather_than_what_it_read(self):
        written = self.remember()
        self.assertEqual(written["metadata"]["verb"], "hug")
        self.assertEqual(written["metadata"]["roles"]["direct"], self.char2.id)

    def test_a_contested_failure_does_not_read_as_a_victory(self):
        written = self.remember(verb="attack", outcome="failure",
                                contested=True)
        self.assertIn("failed", written["text"])

    def test_and_a_contested_success_says_so(self):
        written = self.remember(verb="attack", outcome="success",
                                contested=True)
        self.assertIn("succeeded", written["text"])
