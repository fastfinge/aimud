"""
The second lexicon, and the contract that lets it be optional.

`NothingDependsOnIt` is the class to read, and it is the ground rule of the whole
phase: every lookup answers neutrally when there is no corpus, and a fresh install
has none. Nothing in phases 1-11 may come to depend on this, so the test that it
can be absent is worth more than any test of what it knows.

The builder is tested against a committed sample of real edges -- twenty-odd lines
of the corpus's own TSV, including the rows that must be thrown away -- so the
parsing and the index are covered without fetching a gigabyte.
"""

import os
import tempfile

from django.test import SimpleTestCase, tag
from evennia.utils.test_resources import EvenniaTest

from tests.support import FIXTURES
from world import anatomy, commonsense, lexicon, verbs

SAMPLE = FIXTURES / "conceptnet-sample.tsv"


def sample_lines():
    with open(SAMPLE, encoding="utf-8") as handle:
        return list(handle)


class WithSampleCorpus(SimpleTestCase):
    """A real index, built from the committed sample, in a temporary file."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._dir = tempfile.mkdtemp(prefix="aimud-conceptnet-")
        cls._path = os.path.join(cls._dir, "conceptnet.sqlite3")
        cls.edges = commonsense.build_from(sample_lines(), path=cls._path)
        cls._real = commonsense.PATH
        commonsense.PATH = cls._path
        commonsense.forget()

    @classmethod
    def tearDownClass(cls):
        commonsense.forget()
        commonsense.PATH = cls._real
        try:
            os.remove(cls._path)
            os.rmdir(cls._dir)
        except OSError:
            pass
        super().tearDownClass()


@tag("unit")
class NothingDependsOnIt(SimpleTestCase):
    """
    The ground rule. A fresh install has no corpus, and that is a normal state
    rather than a failure -- so every lookup has to answer neutrally, and so does
    everything that consults one.
    """

    def setUp(self):
        self._real = commonsense.PATH
        commonsense.PATH = os.path.join(tempfile.gettempdir(),
                                        "aimud-no-such-corpus.sqlite3")
        commonsense.forget()

    def tearDown(self):
        commonsense.PATH = self._real
        commonsense.forget()

    def test_it_says_it_is_not_there(self):
        self.assertFalse(commonsense.available())
        self.assertEqual(commonsense.size(), (0, 0))

    def test_every_lookup_answers_empty(self):
        for call in (commonsense.opposites, commonsense.parts_of,
                     commonsense.kinds_of, commonsense.ways_to,
                     commonsense.can_be_done_to):
            self.assertEqual(call("open"), [], call.__name__)
        self.assertEqual(commonsense.forward("open", "IsA"), [])
        self.assertEqual(commonsense.backward("open", "IsA"), [])
        self.assertEqual(commonsense.both_ways("open", "Antonym"), [])
        self.assertFalse(commonsense.is_part_of_anything("wing"))

    def test_the_anatomy_list_still_answers_for_itself(self):
        """
        The hand-written list is not a fallback; it is the first answer. It is
        also fuller than its own docstring's complaint suggests -- wings,
        mandibles and beaks are all in it -- so the part used here is one that
        genuinely is not.
        """
        self.assertTrue(anatomy.is_part("hand"))
        self.assertTrue(anatomy.is_part("mandible"))
        self.assertFalse(anatomy.is_part("thorax"))

    def test_an_anchor_menu_is_still_offered(self):
        said = lexicon.anchor_prompt("datapad")
        self.assertIn("not a word the dictionary knows", said)
        self.assertNotIn("guess rather than a fact", said)

    def test_and_suggests_nothing(self):
        self.assertEqual(lexicon.suggested_anchors("datapad"), [])


@tag("unit")
class ReadingTheCorpusFormat(SimpleTestCase):
    """Against the corpus's own TSV, including the rows that must be dropped."""

    def edges(self):
        return list(commonsense.read_edges(sample_lines()))

    def test_the_kept_relations_come_through(self):
        found = {(start, relation, end)
                 for start, relation, end, _weight in self.edges()}
        self.assertIn(("open", "DistinctFrom", "closed"), found)
        self.assertIn(("wing", "PartOf", "bird"), found)
        self.assertIn(("bird", "HasA", "beak"), found)
        self.assertIn(("take_off", "MannerOf", "leave"), found)

    def test_relations_this_game_never_asks_about_are_dropped(self):
        """
        Everything else in the corpus is WordNet re-exported -- which this game
        has, with senses -- or about language rather than the world.
        """
        relations = {relation for _s, relation, _e, _w in self.edges()}
        self.assertNotIn("Synonym", relations)
        self.assertNotIn("FormOf", relations)

    def test_other_languages_are_dropped(self):
        words = {start for start, _r, _e, _w in self.edges()}
        self.assertNotIn("ouvert", words)

    def test_a_weight_below_the_floor_is_dropped(self):
        """Where a single contributor's typo lives."""
        words = {start for start, _r, _e, _w in self.edges()}
        self.assertNotIn("flimsy", words)

    def test_the_weight_is_read_off_the_metadata(self):
        weights = {(start, end): weight
                   for start, _r, end, weight in self.edges()}
        self.assertEqual(weights[("bird", "beak")], 2.5)

    def test_a_malformed_line_is_skipped_rather_than_fatal(self):
        found = list(commonsense.read_edges([
            "nonsense", "", "a\tb", "\t".join(["x", "/r/IsA", "/c/en/a",
                                               "/c/en/b", "not json"])]))
        self.assertEqual(found, [("a", "IsA", "b", 1.0)])


@tag("unit")
class TheIndex(WithSampleCorpus):
    """Built from the sample, queried the way a caller would."""

    def test_it_was_built(self):
        self.assertTrue(commonsense.available())
        self.assertGreater(self.edges, 10)
        edges, _megabytes = commonsense.size()
        self.assertEqual(edges, self.edges)

    def test_a_relation_reads_forward(self):
        self.assertIn("bird", commonsense.forward("wing", "PartOf"))

    def test_and_backward(self):
        self.assertIn("wing", commonsense.backward("bird", "PartOf"))

    def test_a_symmetric_relation_is_found_from_either_end(self):
        """
        The corpus records whichever way round the contributor typed it, so
        asking one way finds half the answers.
        """
        self.assertIn("dry", commonsense.both_ways("wet", "Antonym"))
        self.assertIn("wet", commonsense.both_ways("dry", "Antonym"))

    def test_a_word_it_has_never_heard_of_answers_empty(self):
        self.assertEqual(commonsense.opposites("blaster"), [])

    def test_a_relation_outside_the_kept_list_is_refused(self):
        self.assertEqual(commonsense.forward("begin", "Synonym"), [])

    def test_phrases_are_spelled_the_way_the_corpus_does(self):
        self.assertIn("leave", commonsense.ways_to("take off"),
                      "a space is an underscore in there")

    def test_and_come_back_as_english(self):
        self.assertIn("tying things", commonsense.forward("rope", "UsedFor"))

    def test_answers_come_back_strongest_first(self):
        found = commonsense.parts_of("bird")
        self.assertEqual(found[0], "beak", "weight 2.5 before weight 2.0")

    def test_a_half_built_index_is_never_believed(self):
        """
        Moved into place only once complete, so an interrupted build leaves
        nothing for `available()` to find and trust.
        """
        self.assertFalse(os.path.exists(f"{commonsense.PATH}.building"))


@tag("unit")
class TheFreeUses(WithSampleCorpus):

    def test_opposites_read_both_relations(self):
        self.assertIn("closed", commonsense.opposites("open"))
        self.assertIn("dry", commonsense.opposites("wet"))
        self.assertIn("unlit", commonsense.opposites("lit"))

    def test_a_word_is_never_its_own_opposite(self):
        self.assertNotIn("open", commonsense.opposites("open"))

    def test_parts_read_both_relations(self):
        found = commonsense.parts_of("beetle")
        self.assertIn("mandible", found)
        self.assertIn("carapace", found)

    def test_a_part_is_recognised_as_one(self):
        self.assertTrue(commonsense.is_part_of_anything("mandible"))
        self.assertFalse(commonsense.is_part_of_anything("bread"))

    def test_kinds_are_words_and_never_senses(self):
        """
        The property that disqualifies this corpus from grounding anything: its
        nodes are words. A caller wanting a kind has to fold them itself.
        """
        found = commonsense.kinds_of("chest")
        self.assertIn("container", found)
        self.assertNotIn("container.n.01", found)

    def test_what_can_be_done_to_a_thing_comes_back_as_verbs(self):
        """Its values are participles; `affordances.known_verb` folds them."""
        self.assertIn("eat", commonsense.can_be_done_to("bread"))
        self.assertIn("burn", commonsense.can_be_done_to("paper"))


@tag("unit")
class WhatTheAnchorMenuSuggests(WithSampleCorpus):
    """
    WordNet cannot help with the words section 7 is about, by definition. This
    corpus sometimes can, being crowdsourced -- and the answer is folded back into
    real senses, because a kind is a synset.
    """

    def test_an_invented_noun_gets_a_suggestion(self):
        self.assertIn("device.n.01", lexicon.suggested_anchors("datapad"))

    def test_the_suggestion_is_a_sense_and_not_a_word(self):
        for name in lexicon.suggested_anchors("datapad"):
            self.assertIn(".n.", name)

    def test_a_noun_nothing_has_heard_of_gets_none(self):
        self.assertEqual(lexicon.suggested_anchors("zorblaxian"), [])

    def test_the_prompt_marks_it_as_a_guess(self):
        said = lexicon.anchor_prompt("datapad")
        self.assertIn("guess rather than a fact", said)
        self.assertIn("device.n.01", said)

    def test_and_the_menu_is_still_there(self):
        """The suggestion pre-fills; it does not replace."""
        said = lexicon.anchor_prompt("datapad")
        self.assertIn("whichever of these", said)


@tag("world")
class AGroupSeededFromOpposites(EvenniaTest):
    """
    `DistinctFrom` is definitionally what a state group is, so the ordinary pairs
    -- open/closed, locked/unlocked -- should not have to be declared by hand.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._dir = tempfile.mkdtemp(prefix="aimud-conceptnet-")
        cls._path = os.path.join(cls._dir, "conceptnet.sqlite3")
        commonsense.build_from(sample_lines(), path=cls._path)
        cls._real = commonsense.PATH
        commonsense.PATH = cls._path
        commonsense.forget()

    @classmethod
    def tearDownClass(cls):
        commonsense.forget()
        commonsense.PATH = cls._real
        try:
            os.remove(cls._path)
            os.rmdir(cls._dir)
        except OSError:
            pass
        super().tearDownClass()

    def setUp(self):
        super().setUp()
        self.root = self.room1
        self.root.db.is_world_root = True

    # A pair WordNet has never heard of, so that what is being measured is this
    # corpus and not the three tests that run before it. Invented words are also
    # the honest case: 7.1 predicts this corpus is good on ordinary nouns and
    # poor on exactly the genre vocabulary a generated world invents, and a
    # fixture is the only place the mechanism can be tested on one.
    MINE, YOURS = "gravlocked", "gravfree"

    def test_a_state_joins_the_group_its_opposite_is_in(self):
        verbs.register_state(self.root, self.MINE, means="held by the field",
                             group="gravity")
        verbs.register_state(self.root, self.YOURS, means="floating free")
        self.assertEqual(verbs.group_of(self.root, self.YOURS), "gravity")

    def test_a_group_somebody_declared_is_never_overruled(self):
        """
        Advisory and last, which is a narrower claim than it sounds.

        The three tests above this one -- spelling, WordNet opposites, WordNet
        synonyms -- *are* allowed to overrule a declared group, and have earned
        it: five worlds registered five separate groups for pairs that belonged
        together. This corpus is not allowed to, because its nodes are words
        rather than senses and 7.1 says it may never hold a position it can win
        from. So it fills a silence and nothing else.
        """
        verbs.register_state(self.root, self.MINE, means="held",
                             group="gravity")
        verbs.register_state(self.root, self.YOURS, means="floating",
                             group="my_own_idea")
        self.assertEqual(verbs.group_of(self.root, self.YOURS), "my_own_idea")

    def test_and_a_seeded_group_is_not_overruled_either(self):
        """`DEFAULT_STATE_GROUP` is the world's own first answer."""
        verbs.register_state(self.root, "wet", means="soaked")
        self.assertEqual(verbs.group_of(self.root, "wet"), "wetness")

    def test_a_state_whose_opposite_is_not_in_this_world_joins_nothing(self):
        """Evidence from this world, as everywhere else: the pair has to be here."""
        verbs.register_state(self.root, self.YOURS, means="floating free")
        self.assertFalse(verbs.group_of(self.root, self.YOURS))

    def test_wordnet_still_gets_the_first_word_where_it_has_one(self):
        """
        The ranking, from the other side. `locked`/`unlocked` are a WordNet
        antonym pair, so they are settled before this corpus is consulted -- and
        those three tests are allowed to overrule a declaration where this one
        is not.
        """
        verbs.register_state(self.root, "locked", means="shut",
                             group="fastening")
        verbs.register_state(self.root, "unlocked", means="open",
                             group="something_else")
        self.assertEqual(verbs.group_of(self.root, "unlocked"), "fastening")

    def test_and_a_word_the_corpus_has_no_opinion_on_joins_nothing(self):
        verbs.register_state(self.root, "powered", means="running")
        verbs.register_state(self.root, "blasted", means="shot at")
        self.assertFalse(verbs.group_of(self.root, "blasted"))


@tag("world")
class BodyPartsBeyondTheList(EvenniaTest):
    """
    `anatomy.PARTS` is about 120 hand-written nouns whose own comment admits the
    problem: a world with beetles and birds in it has mandibles and wings.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._dir = tempfile.mkdtemp(prefix="aimud-conceptnet-")
        cls._path = os.path.join(cls._dir, "conceptnet.sqlite3")
        commonsense.build_from(sample_lines(), path=cls._path)
        cls._real = commonsense.PATH
        commonsense.PATH = cls._path
        commonsense.forget()

    @classmethod
    def tearDownClass(cls):
        commonsense.forget()
        commonsense.PATH = cls._real
        try:
            os.remove(cls._path)
            os.rmdir(cls._dir)
        except OSError:
            pass
        super().tearDownClass()

    def test_a_part_the_list_never_thought_of_is_recognised(self):
        """
        Genuinely absent ones. The list already has wings and mandibles in it,
        which is worth knowing: the gap this fills is narrower than the comment
        in `anatomy.py` implies.
        """
        self.assertNotIn("thorax", anatomy.PARTS)
        self.assertNotIn("proboscis", anatomy.PARTS)
        self.assertTrue(anatomy.is_part("thorax"))
        self.assertTrue(anatomy.is_part("proboscis"))

    def test_the_hand_written_list_is_still_asked_first(self):
        self.assertTrue(anatomy.is_part("hand"))

    def test_and_an_ordinary_noun_is_still_not_a_body_part(self):
        self.assertFalse(anatomy.is_part("bread"))
        self.assertFalse(anatomy.is_part("datapad"))
