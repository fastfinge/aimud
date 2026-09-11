"""
What English already knows, and the one thing it was being asked wrongly.

The tests that matter here are the ones about *senses*. Every verb relation is
only as right as the sense it starts from, and until now they all started from a
guess -- WordNet's frequency order, which is a 1990s newspaper corpus. The guess
sends `launch` through "set up or found" and hands a rule writer the world's
`open` rule as a starting point for launching a spacecraft.

Also here: that the whole module still answers neutrally with no corpus at all.
That is `lexicon.py`'s own promise -- "a missing dictionary makes the world
slightly clumsier. It must never make the world impossible" -- and it is the
kind of promise that quietly stops being true.
"""

from unittest import mock

from django.test import SimpleTestCase, tag

from world import lexicon


@tag("unit")
class NamingASense(SimpleTestCase):

    def test_a_synset_gives_up_its_word(self):
        self.assertEqual(lexicon.word_of("chest.n.02"), "chest")
        self.assertEqual(lexicon.word_of("body_part.n.01"), "body part")

    def test_a_bare_noun_is_its_own_word(self):
        self.assertEqual(lexicon.word_of("datapad"), "datapad")

    def test_nothing_is_nothing(self):
        for value in ("", None, "   "):
            self.assertEqual(lexicon.word_of(value), "")

    def test_a_sense_has_a_definition_and_a_bare_noun_does_not(self):
        self.assertIn("box", lexicon.definition("chest.n.02"))
        self.assertEqual(lexicon.definition("datapad"), "")
        self.assertEqual(lexicon.definition("no.such.n.99"), "")


@tag("unit")
class WhichSenseAVerbRelationStartsFrom(SimpleTestCase):
    """The bug this half of phase 1 exists to fix."""

    def test_a_bare_verb_is_guessed_and_the_guess_can_be_wrong(self):
        """
        Recorded rather than deplored: this is what the fallback does.

        `launch`'s commonest sense is `establish.v.01`, "set up or found",
        whose hypernym is `open.v.02`. So a rule writer asking what launching
        is a way of doing is told: opening.
        """
        self.assertEqual(lexicon.verb_ancestors("launch"), ["open", "propel"])

    def test_a_recorded_sense_answers_about_that_sense(self):
        self.assertNotIn("open", lexicon.verb_ancestors("launch.v.03"))
        self.assertEqual(lexicon.verb_ancestors("pry.v.01"), ["open"])

    def test_a_recorded_sense_drops_the_noise_the_guess_picks_up(self):
        """`pry` guessed reaches "be nosey", and so reaches `ask`."""
        self.assertIn("ask", lexicon.verb_ancestors("pry"))
        self.assertNotIn("ask", lexicon.verb_ancestors("pry.v.01"))

    def test_a_verb_is_never_offered_as_a_way_of_doing_itself(self):
        for verb in ("open", "wash", "launch.v.03"):
            self.assertNotIn(lexicon.word_of(verb),
                             lexicon.verb_ancestors(verb), verb)


@tag("unit")
class TheCausativePair(SimpleTestCase):
    """
    The transitive verb, beside the change it produces.

    `affordances.py` observes that "burn and burning are one idea correctly
    split across two registers" and nothing anywhere computed the link. This
    does, and the same-word answer is the finding rather than noise -- which is
    why `causes` keeps what `verb_ancestors` drops.
    """

    def test_a_verb_causes_its_own_intransitive(self):
        for verb in ("open", "close", "fill", "dry", "break"):
            self.assertEqual(lexicon.causes(verb), [verb], verb)

    def test_and_sometimes_causes_a_different_word(self):
        self.assertEqual(lexicon.causes("kill"), ["die"])
        self.assertEqual(lexicon.causes("ring"), ["sound"])

    def test_most_verbs_cause_nothing_in_particular(self):
        """1.6% of verb synsets have a cause. Silence is the usual answer."""
        for verb in ("read", "look", "smell", "listen"):
            self.assertEqual(lexicon.causes(verb), [], verb)

    def test_entailment_is_what_doing_it_involves(self):
        self.assertEqual(lexicon.entailments("snore"), ["sleep"])
        self.assertEqual(lexicon.entailments("soap"), ["wash"])

    def test_a_sparse_relation_may_look_past_the_commonest_senses(self):
        """
        Measured, and the reason `spread` is a parameter.

        `ring` -> `sound` lives below the first two senses of `ring`. With a
        dense relation looking that far would find answers about the wrong
        sense; with one on 1.6% of senses, a sense that has an answer at all is
        worth hearing.
        """
        self.assertEqual(lexicon.causes("ring"), ["sound"])
        self.assertEqual(lexicon.verb_ancestors("launch"), ["open", "propel"])


@tag("unit")
class OfferingSensesToChooseFrom(SimpleTestCase):

    def test_the_menu_is_capped(self):
        listed = lexicon.verb_senses("break")
        self.assertEqual(len(listed), 5)
        self.assertTrue(all(len(pair) == 2 for pair in listed))

    def test_the_right_answer_is_usually_in_the_menu(self):
        """Not first -- `launch.v.03` is third -- but present, which is enough."""
        names = [name for name, _definition in lexicon.verb_senses("launch")]
        self.assertIn("launch.v.03", names)
        self.assertNotEqual(names[0], "launch.v.03")

    def test_a_verb_with_one_sense_is_settled_and_not_asked_about(self):
        self.assertEqual(lexicon.settled_sense("power"), "power.v.01")
        self.assertEqual(lexicon.verb_sense_prompt("power"), "")

    def test_a_verb_with_several_senses_is_asked_about_and_not_settled(self):
        self.assertEqual(lexicon.settled_sense("launch"), "")
        prompt = lexicon.verb_sense_prompt("launch")
        self.assertIn("launch.v.03", prompt)
        self.assertIn("maiden voyage", prompt)

    def test_a_verb_nobody_has_heard_of_is_neither(self):
        """
        And they are harder to find than expected, which is the point.

        This test first used `scry`, on the assumption that a fantasy verb
        would be absent. WordNet has `scry.v.01`, and `hex`, and `teleport`,
        and `defenestrate`. The genuinely absent ones are `respawn` and
        `hyperjump` -- which is the asymmetry the plan rests on: worlds invent
        nouns constantly and verbs almost never, because players type verbs
        and players type English.
        """
        for verb in ("respawn", "hyperjump"):
            self.assertEqual(lexicon.settled_sense(verb), "", verb)
            self.assertEqual(lexicon.verb_sense_prompt(verb), "", verb)

    def test_the_fantasy_verbs_one_would_expect_to_be_missing_are_not(self):
        for verb in ("scry", "hex", "teleport", "defenestrate"):
            self.assertTrue(lexicon.settled_sense(verb), verb)


@tag("unit")
class WithNoDictionaryAtAll(SimpleTestCase):
    """
    The module's own promise, tested rather than trusted.

    "A missing dictionary makes the world slightly clumsier. It must never make
    the world impossible." Every new function has to keep that, and the way to
    be sure is to take the corpus away.
    """

    def setUp(self):
        self.no_corpus = mock.patch.object(lexicon, "_wordnet",
                                           lambda: None)

    def test_every_verb_relation_answers_emptily(self):
        with self.no_corpus:
            self.assertFalse(lexicon.available())
            self.assertEqual(lexicon.verb_ancestors("open"), [])
            self.assertEqual(lexicon.causes("open"), [])
            self.assertEqual(lexicon.entailments("snore"), [])
            self.assertEqual(lexicon.verb_senses("open"), [])
            self.assertEqual(lexicon.verb_sense_prompt("open"), "")
            self.assertEqual(lexicon.settled_sense("power"), "")

    def test_and_so_do_the_sense_readers(self):
        with self.no_corpus:
            self.assertEqual(lexicon.definition("chest.n.02"), "")
            self.assertEqual(lexicon.ancestors("chest.n.02"), frozenset())
            self.assertEqual(lexicon.senses("chest"), [])
            # `word_of` needs no corpus and must go on working regardless: a
            # kind still has to be able to say its own name.
            self.assertEqual(lexicon.word_of("chest.n.02"), "chest")
