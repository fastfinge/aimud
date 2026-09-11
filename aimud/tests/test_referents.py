"""
"greet Jessica" and then "hug her".

The phase a player would actually notice. What is held still here is mostly
about what the game refuses to do: a pronoun is never conjured, never guessed
at when two people answer to it, and never swept into a bulk action on the
strength of a word list.
"""

from django.test import tag
from evennia.utils.test_resources import EvenniaTest

from world import bulk, choosing, pronouns, referents, verbs


@tag("world")
class Remembering(EvenniaTest):

    def setUp(self):
        super().setUp()
        self.root = self.room1
        self.room1.db.world_root = self.root
        referents.clear(self.char1)

    def test_a_person_answers_to_the_set_they_go_by(self):
        pronouns.give(self.char2, "she", self.root)
        self.assertIn("her", referents.forms_of(self.char2, self.root))

    def test_a_character_nobody_asked_answers_to_them(self):
        self.assertIn("them", referents.forms_of(self.char2, self.root))

    def test_a_thing_answers_to_it(self):
        self.assertEqual(referents.forms_of(self.obj1, self.root), {"it"})

    def test_binding_something_remembers_it(self):
        verbs.bind_all(self.char1, {"direct": self.obj1.key})
        self.assertIs(referents.recall(self.char1, "it"), self.obj1)

    def test_and_what_sort_of_thing_it_was(self):
        from world import kinds

        kinds.ensure_person(self.char2)
        referents.note(self.char1, self.char2, self.root)
        self.assertTrue(referents.last_kind(self.char1))

    def test_the_direct_object_wins_where_two_roles_share_a_word(self):
        """
        "put the lamp on the shelf" leaves "it" meaning the lamp, because
        "now light it" means the lamp.
        """
        referents.note_all(self.char1,
                           {"target": self.obj2, "direct": self.obj1},
                           self.root)
        self.assertIs(referents.recall(self.char1, "it"), self.obj1)

    def test_nothing_survives_a_reload(self):
        """
        The table is ndb on purpose: "get it" after a restart should mean
        nothing rather than something from last week.
        """
        referents.note(self.char1, self.obj1, self.root)
        referents.clear(self.char1)
        self.assertIsNone(referents.recall(self.char1, "it"))


@tag("world")
class ResolvingOne(EvenniaTest):

    def setUp(self):
        super().setUp()
        self.root = self.room1
        self.room1.db.world_root = self.root
        referents.clear(self.char1)
        pronouns.give(self.char2, "she", self.root)

    def test_one_person_answering_needs_no_asking(self):
        found, question = verbs.resolve_pronoun(self.char1, "her")
        self.assertIs(found, self.char2)
        self.assertIsNone(question)

    def test_and_binds_through_the_ordinary_door(self):
        self.assertIs(verbs.bind(self.char1, "her"), self.char2)

    def test_a_word_nothing_answers_to_binds_nothing(self):
        self.assertIsNone(verbs.bind(self.char1, "him"))

    def test_and_is_never_conjured(self):
        """
        The reason the pronoun branch sits before the search rather than
        after it. What the search does not find is offered up to be invented,
        and an object called "her" is the worst answer available.
        """
        bound, unbound, questions = verbs.bind_all(
            self.char1, {"direct": "him"})
        self.assertEqual(bound, {})
        self.assertIn("direct", unbound)
        self.assertEqual(questions, [])

    def test_two_people_answering_is_asked_rather_than_guessed(self):
        other = self.create_character("Britney")
        other.location = self.room1
        pronouns.give(other, "she", self.root)

        found, question = verbs.resolve_pronoun(self.char1, "her")
        self.assertIsNone(found)
        self.assertIn("Britney", question)

    def test_unless_one_of_them_was_just_referred_to(self):
        """
        The whole point: "greet Jessica" then "hug her" reaches Jessica even
        in a crowded room.
        """
        other = self.create_character("Britney")
        other.location = self.room1
        pronouns.give(other, "she", self.root)

        referents.note(self.char1, self.char2, self.root)
        found, question = verbs.resolve_pronoun(self.char1, "her")
        self.assertIs(found, self.char2)
        self.assertIsNone(question)

    def test_a_memory_of_somebody_who_has_left_does_not_count(self):
        other = self.create_character("Britney")
        other.location = self.room1
        pronouns.give(other, "she", self.root)

        referents.note(self.char1, self.char2, self.root)
        self.char2.location = self.room2
        found, _question = verbs.resolve_pronoun(self.char1, "her")
        self.assertIs(found, other)

    def create_character(self, key):
        from evennia import create_object
        from typeclasses.characters import Character

        return create_object(Character, key=key, location=self.room1)


@tag("world")
class WhatTheVerbRulesOut(EvenniaTest):
    """
    SHRDLU's one transferable idea: resolve to the most recent referent that
    the current verb could apply to, not the most recent full stop.
    """

    def setUp(self):
        super().setUp()
        self.root = self.room1
        self.room1.db.world_root = self.root
        referents.clear(self.char1)

    def test_a_kind_that_has_refused_the_verb_is_not_a_candidate(self):
        from world import kinds

        self.obj1.db.kinds = ["candle.n.01"]
        self.obj2.db.kinds = ["box.n.01"]
        kinds.admit(self.root, ["candle.n.01"], "open", False)

        found = verbs.pronoun_candidates(self.char1, "it", verb="open")
        self.assertIn(self.obj2, found)
        self.assertNotIn(self.obj1, found)

    def test_silence_is_not_a_refusal(self):
        """
        Only a definite no filters. A kind nobody has decided about stays in
        the running, because deciding it here is what a pronoun must not do.
        """
        self.obj1.db.kinds = ["candle.n.01"]
        found = verbs.pronoun_candidates(self.char1, "it", verb="open")
        self.assertIn(self.obj1, found)


@tag("world")
class AllOfThem(EvenniaTest):

    def setUp(self):
        super().setUp()
        self.root = self.room1
        self.room1.db.world_root = self.root
        referents.clear(self.char1)

    def test_them_means_whatever_them_last_meant(self):
        self.obj1.db.kinds = ["wrench.n.01"]
        self.obj2.db.kinds = ["wrench.n.01"]
        referents.note(self.char1, self.obj1, self.root)

        found = bulk.matching(self.char1, "get", "all of them")
        self.assertIn(self.obj2, found)

    def test_and_not_things_of_another_sort(self):
        self.obj1.db.kinds = ["wrench.n.01"]
        self.obj2.db.kinds = ["candle.n.01"]
        referents.note(self.char1, self.obj1, self.root)

        found = bulk.matching(self.char1, "get", "all of them")
        self.assertNotIn(self.obj2, found)

    def test_with_nothing_referred_to_it_sweeps_nothing(self):
        """
        An empty sort would sweep the whole room, which is the one answer
        worse than refusing.
        """
        self.assertEqual(bulk.matching(self.char1, "get", "all of them"), [])

    def test_everyone_still_means_the_people(self):
        self.assertTrue(bulk.split("everyone")[0])
        self.assertIn(self.char2, bulk.matching(self.char1, "greet", "everyone"))


@tag("unit")
class PuttingTheQuestion(EvenniaTest):
    """
    The seam, not the menu. Three more things on the roadmap want to ask a
    question and get an answer back, and the first one should not be written
    somewhere a menu cannot replace it.
    """

    def test_two_options_read_as_a_choice(self):
        self.assertEqual(choosing.phrase_options(["Jessica", "Britney"]),
                         "Jessica or Britney")

    def test_three_read_as_a_list(self):
        self.assertEqual(choosing.phrase_options(["A", "B", "C"]),
                         "A, B or C")

    def test_the_question_names_the_word_that_was_ambiguous(self):
        asked = choosing.question("her", ["Jessica", "Britney"])
        self.assertIn("her", asked)
        self.assertIn("Jessica or Britney", asked)

    def test_asking_nothing_is_not_asking(self):
        self.assertFalse(choosing.ask(self.char1, "her", []))
