"""
What a world calls somebody, and what stops the register sprawling.

Two things are held still. A declaration must be **complete** -- there is no
later moment at which a missing reflexive gets filled in, so a half-set is
dropped rather than patched. And a set this world already keeps **folds**:
`register` answers with the slug in use, not the one it was handed, which is
the only thing that stops a generator declaring she/her once per character.
"""

from django.test import SimpleTestCase, tag
from evennia.utils.test_resources import EvenniaTest

from world import pronouns


def a_set(**overrides):
    """A complete declaration, for a world that has never met one."""
    entry = {
        "subject": "ze", "object": "zir", "adjective": "zir",
        "possessive": "zirs", "reflexive": "zirself", "plural": False,
        "means": "for somebody who goes by ze and zir",
    }
    entry.update(overrides)
    return entry


@tag("unit")
class WhatEveryWorldStartsWith(SimpleTestCase):

    def test_four_sets_before_anybody_has_said_anything(self):
        self.assertEqual(set(pronouns.vocabulary(None)),
                         {"he", "she", "they", "it"})

    def test_they_is_the_plural_one(self):
        """
        The field a model reliably gets wrong, and the reason this set is
        seeded rather than left to be invented: without it, every sentence
        about a they/them character reads "they picks up the sword".
        """
        self.assertTrue(pronouns.vocabulary(None)["they"]["plural"])
        self.assertFalse(pronouns.vocabulary(None)["she"]["plural"])

    def test_every_seeded_set_is_complete(self):
        for slug, entry in pronouns.SEEDED.items():
            for field in pronouns.REQUIRED:
                self.assertIn(field, entry, f"{slug} has no {field}")

    def test_a_set_nobody_named_is_they(self):
        self.assertEqual(pronouns.get(None, "")["subject"], "they")
        self.assertEqual(pronouns.get(None, "nonsense")["subject"], "they")


@tag("unit")
class ReadingADeclaration(SimpleTestCase):

    def test_a_complete_one_is_kept(self):
        entry, complaint = pronouns.clean(a_set())
        self.assertEqual(complaint, "")
        self.assertEqual(entry["reflexive"], "zirself")

    def test_a_missing_form_is_refused_rather_than_guessed(self):
        for field in pronouns.FORMS:
            broken = a_set()
            broken.pop(field)
            entry, complaint = pronouns.clean(broken)
            self.assertIsNone(entry, field)
            self.assertIn(field, complaint)

    def test_a_set_with_no_meaning_is_refused(self):
        """
        `means` is what `help ze` shows and what the next generator reads. A
        set with none is a word nobody can use correctly a second time.
        """
        entry, complaint = pronouns.clean(a_set(means="  "))
        self.assertIsNone(entry)

    def test_nonsense_is_refused_rather_than_raising(self):
        for junk in (None, "she/her", 7, []):
            entry, _ = pronouns.clean(junk)
            self.assertIsNone(entry, repr(junk))

    def test_a_settled_number_is_corrected_not_believed(self):
        """
        The same way DEFAULT_STATE_GROUP overrules a group a model declared:
        where the answer is already known, it is not a question.
        """
        entry, _ = pronouns.clean(a_set(subject="they", plural=False))
        self.assertTrue(entry["plural"])
        entry, _ = pronouns.clean(a_set(subject="she", plural=True))
        self.assertFalse(entry["plural"])

    def test_but_a_new_set_is_taken_at_its_word(self):
        entry, _ = pronouns.clean(a_set(plural=True))
        self.assertTrue(entry["plural"])


@tag("world")
class AddingOne(EvenniaTest):

    def setUp(self):
        super().setUp()
        self.root = self.room1
        self.room1.db.world_root = self.root

    def test_a_new_set_is_learned(self):
        self.assertEqual(pronouns.register(self.root, a_set()), "ze")
        self.assertTrue(pronouns.known(self.root, "ze"))

    def test_and_the_seeded_ones_survive_it(self):
        pronouns.register(self.root, a_set())
        self.assertTrue(pronouns.known(self.root, "she"))

    def test_declaring_one_the_world_has_folds_onto_it(self):
        """
        The test that matters. Without it a generator declares she/her once
        per character and the register is a list of duplicates within a day.
        """
        before = len(pronouns.vocabulary(self.root))
        slug = pronouns.register(self.root, a_set(
            subject="she", object="her", adjective="her",
            possessive="hers", reflexive="herself",
            means="a second opinion about she"))
        self.assertEqual(slug, "she")
        self.assertEqual(len(pronouns.vocabulary(self.root)), before)

    def test_and_the_fold_keeps_the_original_meaning(self):
        pronouns.register(self.root, a_set(
            subject="she", object="her", adjective="her",
            possessive="hers", reflexive="herself", means="something else"))
        self.assertEqual(pronouns.get(self.root, "she")["means"],
                         pronouns.SEEDED["she"]["means"])

    def test_two_sets_may_share_a_form_that_is_not_the_subject(self):
        """
        "ze/her" beside "she/her" is how neopronoun sets genuinely work.
        Which was meant is a question for whoever resolves a pronoun, not for
        whoever stores one.
        """
        slug = pronouns.register(self.root, a_set(object="her"))
        self.assertEqual(slug, "ze")
        self.assertTrue(pronouns.known(self.root, "she"))

    def test_an_incomplete_declaration_changes_nothing(self):
        before = dict(pronouns.vocabulary(self.root))
        self.assertEqual(pronouns.register(self.root, {"subject": "ze"}), "")
        self.assertEqual(pronouns.vocabulary(self.root), before)


@tag("world")
class WhoGoesByWhat(EvenniaTest):

    def setUp(self):
        super().setUp()
        self.root = self.room1
        self.room1.db.world_root = self.root

    def test_a_character_nobody_asked_goes_by_they(self):
        self.assertEqual(pronouns.of(self.char1)["subject"], "they")

    def test_and_can_be_told_otherwise(self):
        self.assertEqual(pronouns.give(self.char1, "she"), "she")
        self.assertEqual(pronouns.of(self.char1)["object"], "her")

    def test_but_not_told_a_set_this_world_does_not_keep(self):
        """
        The discipline `npc_gen` already applies to traits. The way to add a
        set is `register`, and refusing here is how that gets said.
        """
        self.assertEqual(pronouns.give(self.char1, "ze"), "")
        self.assertEqual(pronouns.of(self.char1)["subject"], "they")

    def test_a_set_registered_first_can_then_be_given(self):
        pronouns.register(self.root, a_set())
        self.assertEqual(pronouns.give(self.char1, "ze"), "ze")
        self.assertEqual(pronouns.of(self.char1)["reflexive"], "zirself")


@tag("unit")
class SayingWhatAWorldKeeps(SimpleTestCase):

    def test_a_set_reads_as_somebody_would_say_it(self):
        self.assertEqual(pronouns.spelled(pronouns.SEEDED["she"]), "she/her/hers")

    def test_the_prompt_block_names_every_set(self):
        block = pronouns.vocabulary_block(None)
        for slug in pronouns.SEEDED:
            self.assertIn(slug, block)

    def test_and_tells_a_model_to_reuse_before_inventing(self):
        self.assertIn("declare a new set only", pronouns.vocabulary_block(None))


@tag("world")
class ReadingAboutThem(EvenniaTest):
    """
    A player meets a pronoun set in narration before they meet it anywhere
    else, so `help she` has to answer -- and so does `help hers`, which is the
    word somebody puzzled by "the sword is hers" will actually type.
    """

    def setUp(self):
        super().setUp()
        self.root = self.room1
        self.room1.db.world_root = self.root

    def topics(self):
        from commands.help_cmds import world_topics

        return world_topics(self.char1, self.root)

    def test_every_form_finds_the_entry(self):
        topics = self.topics()
        for form in ("she", "her", "hers", "herself"):
            self.assertIn(form, topics, form)

    def test_and_the_entry_says_how_it_reads(self):
        self.assertIn("picks up the sword", self.topics()["she"].entrytext)

    def test_a_plural_set_reads_with_a_plural_verb(self):
        text = self.topics()["they"].entrytext
        self.assertIn("they pick up the sword", text)
        self.assertNotIn("they picks up", text)

    def test_a_world_invented_set_is_documented_too(self):
        pronouns.register(self.root, a_set())
        topics = self.topics()
        self.assertIn("zirself", topics)
        self.assertIn("ze and zir", topics["ze"].entrytext)


@tag("world")
class WhatAGeneratedCharacterGoesBy(EvenniaTest):
    """
    The declaration channel, from the end a model writes to.

    A generator may add to the register -- otherwise it could only ever grow
    by a player typing into it, and a world that invents a hive-mind has no
    way to say how to refer to it. What keeps that safe is that a word merely
    *used* does nothing and a word *declared* arrives whole.
    """

    def setUp(self):
        super().setUp()
        self.root = self.room1
        self.room1.db.world_root = self.root

    def spawn(self, **fields):
        """What `_spawn` does with the pronoun half of a reply."""
        npc = self.char2
        wanted = str(fields.get("pronouns", "") or "").strip()
        declared = fields.get("new_pronoun_set")
        if declared:
            wanted = pronouns.register(self.root, declared) or wanted
        pronouns.give(npc, wanted, self.root)
        return npc

    def test_a_set_the_world_keeps_is_used_by_name(self):
        npc = self.spawn(pronouns="he")
        self.assertEqual(pronouns.of(npc, self.root)["object"], "him")

    def test_a_word_merely_used_does_nothing(self):
        """
        No declaration, so no register entry -- and the character falls back
        rather than carrying a word nobody else has.
        """
        npc = self.spawn(pronouns="ze")
        self.assertFalse(pronouns.known(self.root, "ze"))
        self.assertEqual(pronouns.of(npc, self.root)["subject"], "they")

    def test_a_word_declared_arrives_whole(self):
        npc = self.spawn(pronouns="ze", new_pronoun_set=a_set())
        self.assertTrue(pronouns.known(self.root, "ze"))
        self.assertEqual(pronouns.of(npc, self.root)["reflexive"], "zirself")

    def test_a_half_declaration_leaves_the_character_on_the_default(self):
        npc = self.spawn(pronouns="ze", new_pronoun_set={"subject": "ze"})
        self.assertFalse(pronouns.known(self.root, "ze"))
        self.assertEqual(pronouns.of(npc, self.root)["subject"], "they")

    def test_a_declaration_of_something_known_folds_and_is_still_given(self):
        """
        The case that would otherwise fill a register with duplicates: the
        model declares she/her for the fourth character, and gets she/her.
        """
        npc = self.spawn(pronouns="she", new_pronoun_set=a_set(
            subject="she", object="her", adjective="her",
            possessive="hers", reflexive="herself", means="again"))
        self.assertEqual(len(pronouns.vocabulary(self.root)), 4)
        self.assertEqual(pronouns.of(npc, self.root)["object"], "her")


@tag("world")
class WhatTheRegisterRecords(EvenniaTest):
    """
    An empty attribute is the useful answer, not a missing one.

    The seeded four are merged in by `vocabulary` and never written down, so
    what a world stores is exactly what it invented. A world that has met
    nobody the ordinary four did not cover records nothing -- which is what
    the corpus should say about it, and what four identical entries in every
    export would have hidden.
    """

    def setUp(self):
        super().setUp()
        self.root = self.room1
        self.room1.db.world_root = self.root

    def test_a_world_that_invented_nothing_stores_nothing(self):
        self.assertFalse(self.root.db.pronoun_sets)
        self.assertEqual(len(pronouns.vocabulary(self.root)), 4)

    def test_and_still_answers_for_every_seeded_set(self):
        self.assertEqual(pronouns.get(self.root, "she")["object"], "her")

    def test_inventing_one_records_only_that_one(self):
        pronouns.register(self.root, a_set())
        self.assertEqual(list(self.root.db.pronoun_sets), ["ze"])
        self.assertEqual(len(pronouns.vocabulary(self.root)), 5)

    def test_a_seeded_set_cannot_drift_from_the_code(self):
        """
        Merged rather than copied, so a world made a year ago answers with
        whatever `SEEDED` says today.
        """
        pronouns.register(self.root, a_set())
        self.assertEqual(pronouns.get(self.root, "they"),
                         dict(pronouns.SEEDED["they"]))
