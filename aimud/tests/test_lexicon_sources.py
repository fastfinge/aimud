"""
Words from the dictionaries, chosen and kept like a world list's.

`$hyponym(sword.n.01)` is some sort of sword and `$found_at(galley)` is
something lying in a galley, with no model asked. Both lexicons are optional,
so the test that matters most is the one without them: every call says its
`else`, and a world with no corpus is clumsier rather than broken.

ConceptNet is tested against the committed sample, which holds exactly one
edge for each relation used here -- so a pick is certain, and what is being
tested is the path to it rather than the luck of the seed.
"""

import os
import tempfile
from unittest import mock

from django.test import SimpleTestCase, tag
from evennia.utils.test_resources import EvenniaTest

from tests.test_commonsense import WithSampleCorpus
from world import commonsense, lexicon, token_lists, tokens


def said(template, context=None):
    return tokens.text(template, context or tokens.Context())


@tag("unit")
class WordNet(SimpleTestCase):

    def test_the_sorts_of_a_sword(self):
        found = lexicon.hyponyms("sword.n.01")
        self.assertIn("rapier", found)
        self.assertIn("fencing sword", found)

    def test_the_parts_of_a_sword(self):
        self.assertIn("hilt", lexicon.parts("sword.n.01"))

    def test_nothing_for_what_is_not_a_sense(self):
        self.assertEqual(lexicon.hyponyms("nonsense.n.99"), [])
        self.assertEqual(lexicon.parts(""), [])

    def test_a_call_says_one_of_them(self):
        self.assertIn(said("$hyponym(sword.n.01)"),
                      lexicon.hyponyms("sword.n.01"))
        self.assertIn(said("$part_of(sword.n.01)"), lexicon.parts("sword.n.01"))

    def test_a_plain_word_that_settles_is_its_sense(self):
        self.assertIn(said("$hyponym(sword)"), lexicon.hyponyms("sword.n.01"))

    def test_a_sense_with_nothing_beneath_it_says_its_else(self):
        self.assertEqual(said("$hyponym(nonsense.n.99, else=a blade)"),
                         "a blade")

    def test_without_wordnet_every_call_says_its_else(self):
        with mock.patch.object(lexicon, "_wordnet", lambda: None):
            self.assertEqual(said("$hyponym(sword.n.01, else=a blade)"),
                             "a blade")
            self.assertEqual(said("$part_of(sword.n.01, else=a hilt)"),
                             "a hilt")

    def test_every_call_is_reserved_and_answered(self):
        self.assertEqual(set(tokens.SOURCE_CALLS), set(token_lists.SOURCES))
        for name in tokens.SOURCE_CALLS:
            self.assertIn(name, tokens.RESERVED_CALLS)


@tag("unit")
class ConceptNet(WithSampleCorpus):

    def test_something_found_in_a_galley(self):
        self.assertEqual(said("$found_at(galley, else=a crate)"), "pot")

    def test_something_used_for_a_job(self):
        self.assertEqual(said("$used_for(tying things)"), "rope")

    def test_what_a_thing_is_a_sort_of(self):
        self.assertEqual(said("$kind_of(bread)"), "food")

    def test_a_place_nobody_wrote_about_says_its_else(self):
        self.assertEqual(said("$found_at(the moon, else=dust)"), "dust")

    def test_what_passes_as_a_word(self):
        self.assertTrue(token_lists.plausible("pot"))
        self.assertTrue(token_lists.plausible("old rope"))
        self.assertFalse(token_lists.plausible("cook"), "a person")
        self.assertFalse(token_lists.plausible("xqzzy"), "no dictionary knows it")
        self.assertFalse(token_lists.plausible("a thing somebody once typed"))

    def test_without_wordnet_nothing_passes(self):
        with mock.patch.object(lexicon, "_wordnet", lambda: None):
            self.assertEqual(said("$found_at(galley, else=a crate)"), "a crate")


@tag("unit")
class NoCorpusAtAll(SimpleTestCase):

    def setUp(self):
        self._real = commonsense.PATH
        commonsense.PATH = os.path.join(tempfile.gettempdir(),
                                        "aimud-no-such-corpus.sqlite3")
        commonsense.forget()

    def tearDown(self):
        commonsense.PATH = self._real
        commonsense.forget()

    def test_every_conceptnet_call_says_its_else(self):
        for template in ("$found_at(galley, else=a crate)",
                         "$used_for(cooking, else=a crate)",
                         "$kind_of(bread, else=a crate)"):
            self.assertEqual(said(template), "a crate", template)

    def test_and_with_no_else_says_nothing(self):
        self.assertEqual(said("A $found_at(galley) here."), "A  here.")


@tag("world")
class KeptLikeAList(EvenniaTest):

    def setUp(self):
        super().setUp()
        self.room1.db.world_root = self.room1
        self.room1.db.is_world_root = True

    def test_a_thing_keeps_its_sort_of_sword(self):
        context = lambda: tokens.Context(about=self.obj1, world_root=self.room1)
        first = said("A $hyponym(sword.n.01) hangs here.", context())
        for _ in range(3):
            self.assertEqual(said("A $hyponym(sword.n.01) hangs here.",
                                  context()), first)
        self.assertIn("hyponym:sword.n.01", self.obj1.db.token_choices)

    def test_a_label_is_a_second_choice(self):
        context = tokens.Context(about=self.obj1, world_root=self.room1)
        said("$hyponym(sword.n.01) and $hyponym(sword.n.01, as=spare)", context)
        self.assertEqual(set(self.obj1.db.token_choices),
                         {"hyponym:sword.n.01", "hyponym:sword.n.01#spare"})

    def test_a_list_may_draw_on_a_dictionary(self):
        self.assertEqual(token_lists.register(self.room1, "blade", {
            "means": "a blade on a wall",
            "entries": ["$hyponym(sword.n.01, else=sword)"]}), "blade")
        self.assertIn(said("{blade}", tokens.Context(world_root=self.room1)),
                      lexicon.hyponyms("sword.n.01"))

    def test_and_no_list_may_take_a_dictionary_calls_name(self):
        for name in tokens.SOURCE_CALLS:
            self.assertEqual(token_lists.register(self.room1, name, {
                "means": "x", "entries": ["y"]}), "", name)
