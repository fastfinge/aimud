"""
The grammar, held still.

One reader replaced six modules' worth of half-knowledge about what a noun
phrase looks like, and three lists of words to ignore that had already drifted
apart. These are the phrases that made the drift matter, plus the ones each of
those modules was written for in the first place -- so that the next person to
add something to the grammar finds out here rather than in play.

The distinction the whole module turns on: `.plain` is the phrase with its
determiners gone, which is what the game matches names against, while `.thing`
is what is left once the grammar has been taken off as well. "the second
wrench" is "second wrench" to the first and "wrench" to the second, and an
object really can be called "Second Wrench".
"""

from django.test import SimpleTestCase, tag

from world import nounphrase as np


@tag("unit")
class ReadingAPhrase(SimpleTestCase):

    def test_nothing_reads_as_nothing(self):
        for phrase in ("", None, "   "):
            read = np.read(phrase)
            self.assertEqual(read.plain, "")
            self.assertEqual(read.head, "")

    def test_determiners_carry_nothing(self):
        for phrase in ("the ball", "a ball", "some ball", "those balls"):
            self.assertNotIn("the", np.read(phrase).plain.split())

    def test_the_head_is_the_last_word(self):
        """
        Wrong about English in general and right about every name this game
        generates: a Slate Chalkboard is a board, a Cardboard Nametag a nametag.
        """
        read = np.read("stained slate chalkboard")
        self.assertEqual(read.head, "chalkboard")
        self.assertEqual(read.modifiers, ["stained", "slate"])


@tag("unit")
class Counting(SimpleTestCase):

    def test_an_ordinal_is_taken_off(self):
        self.assertEqual(np.read("the second wrench").ordinal, 2)
        self.assertEqual(np.read("the second wrench").thing, "wrench")

    def test_last_counts_from_the_other_end(self):
        self.assertEqual(np.read("last wrench").ordinal, -1)

    def test_other_means_second(self):
        self.assertEqual(np.read("the other wrench").ordinal, 2)

    def test_a_bare_number_word_is_a_name(self):
        """
        "get first" is somebody naming a thing called first, not an empty
        request for the first of nothing.
        """
        self.assertEqual(np.read("first").ordinal, 0)
        self.assertEqual(np.read("first").head, "first")

    def test_counted_answers_the_way_ordinal_always_did(self):
        self.assertEqual(np.read("the second wrench").counted, (2, "wrench"))
        self.assertEqual(np.read("wrench").counted, (0, "wrench"))


@tag("unit")
class Quantifiers(SimpleTestCase):

    def test_all_on_its_own_leaves_nothing_to_narrow_by(self):
        for word in ("all", "everything", "the lot"):
            read = np.read(word)
            self.assertTrue(read.means_everything, word)
            self.assertEqual(read.thing, "", word)

    def test_every_wrench_is_a_narrowing(self):
        read = np.read("every wrench")
        self.assertTrue(read.means_everything)
        self.assertEqual(read.thing, "wrench")

    def test_people_are_told_from_things(self):
        self.assertTrue(np.read("everyone").about_people)
        self.assertFalse(np.read("everything").about_people)

    def test_a_partitive_of_is_not_a_possessive_one(self):
        """
        The bug this ordering exists for. "all of her machines" is a quantifier
        over a possessive; read as the inversion that turns "the back of her
        hand" into a hand, the "all" is lost and a bulk action becomes one.
        """
        read = np.read("all of her machines")
        self.assertTrue(read.means_everything)
        self.assertIs(read.possessor, np.THIRD_PERSON)
        self.assertEqual(read.thing, "machines")


@tag("unit")
class Possession(SimpleTestCase):

    def test_a_pronoun_says_whose(self):
        self.assertIs(np.read("her ball").possessor, np.THIRD_PERSON)
        self.assertIs(np.read("my ball").possessor, np.SPEAKER)
        self.assertEqual(np.read("her ball").thing, "ball")

    def test_an_apostrophe_names_them(self):
        self.assertEqual(np.read("Jessica's ball").possessor, "jessica")
        self.assertEqual(np.read("Jessica's ball").thing, "ball")

    def test_a_trailing_apostrophe_counts(self):
        self.assertEqual(np.read("Ris' badge").possessor, "ris")

    def test_nobody_claimed_anything(self):
        self.assertIsNone(np.read("the ball").possessor)
        self.assertFalse(np.read("the ball").stated_possessor)

    def test_of_turns_a_phrase_around_only_for_an_owner(self):
        self.assertEqual(np.read("the back of her hand").thing, "hand")
        self.assertEqual(np.read("chest of drawers").head, "drawers")

    def test_my_ball_is_a_ball_for_matching_purposes(self):
        """
        Which ball is `.possessor`'s question. What it *is* is a ball, and the
        three lists this module replaced all agreed on that much.
        """
        self.assertEqual(np.read("my ball").plain, "ball")

    def test_but_a_bare_pronoun_is_not_nothing(self):
        """
        "mine" standing alone is a thing being named, not a determiner in
        front of one -- and dropping it leaves nothing to match at all.
        """
        self.assertEqual(np.read("mine").plain, "mine")


@tag("unit")
class ThePlainViewIsNotTheThing(SimpleTestCase):
    """
    The line between this phase and the next, and the reason `.plain` still
    carries what the grammar has already accounted for.
    """

    def test_plain_keeps_the_count_and_the_thing_does_not(self):
        read = np.read("the second wrench")
        self.assertEqual(read.plain, "second wrench")
        self.assertEqual(read.thing, "wrench")

    def test_plain_keeps_a_written_possessive(self):
        self.assertEqual(np.read("jessica's ball").plain, "jessica's ball")
        self.assertEqual(np.read("jessica's ball").thing, "ball")


@tag("unit")
class WhatNoSearchCanFind(SimpleTestCase):

    def test_the_room_and_the_speaker(self):
        self.assertTrue(np.read("here").is_here)
        self.assertTrue(np.read("the room").is_here)
        self.assertTrue(np.read("myself").is_self)
        self.assertFalse(np.read("the ball").is_self)


@tag("unit")
class WordsAWorldAddedItself(SimpleTestCase):
    """
    Nothing overrides anything yet. The seam is tested anyway, because the
    first thing that will use it is the next phase: a world that invents a
    pronoun set has invented a possessive adjective with it.
    """

    class FakeWorld:
        class db:
            extra_possessives = ["zir"]
            extra_quantifiers = ["yon"]

    def test_english_alone_by_default(self):
        self.assertEqual(np.tables()["possessives"], np.POSSESSIVES)

    def test_a_world_may_teach_it_a_word(self):
        found = np.tables(self.FakeWorld)["possessives"]
        self.assertIn("zir", found)
        self.assertIn("her", found)

    def test_and_the_reader_uses_it(self):
        read = np.read("zir sword", world_root=self.FakeWorld)
        self.assertEqual(read.thing, "sword")
        self.assertEqual(read.possessor_words, "zir")
        self.assertIs(read.possessor, np.THIRD_PERSON)

    def test_a_world_cannot_unteach_one(self):
        """
        Additive only. These are English rather than furniture, and a world
        that takes "the" away is a world nobody can type in.
        """
        self.assertTrue(np.DETERMINERS <= np.tables(self.FakeWorld)["determiners"])
