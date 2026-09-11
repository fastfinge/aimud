"""
Kinds, and the anchor that gives an invented noun somewhere to hang.

`kinds.py` said all along that a noun no dictionary has heard of "keeps its
bare noun as a kind and is anchored under the nearest real synset, so a
greatsword still lands somewhere closed". It was not implemented:
`lexicon.ancestors("datapad")` is empty, so the kind had no taxonomy above it,
took no floor from it, pruned against nothing, and could never be reached by a
rule filed against a sort of thing.

That is survivable while affordances are a hint. It is fatal once the taxonomy
becomes the index every rule is filed under, which is what the rulebook change
makes it -- and for a space game the invented nouns are most of the vocabulary.
"""

from unittest import mock

from django.test import SimpleTestCase, tag

from world import kinds, lexicon


class FakeRoot:
    """A world root, as far as `kind_specs` is concerned."""

    def __init__(self, specs=None):
        self.db = mock.Mock(kind_specs=dict(specs or {}))


@tag("unit")
class KnowingWhenAnAnchorIsWanted(SimpleTestCase):

    def test_a_word_no_dictionary_knows_wants_one(self):
        for kind in ("datapad", "holodeck", "hyperdrive"):
            self.assertTrue(kinds.needs_anchor(kind), kind)

    def test_a_real_sense_knows_its_own_ancestry_and_must_not_be_given_one(self):
        for kind in ("chest.n.02", "book.n.01", "sword.n.01"):
            self.assertFalse(kinds.needs_anchor(kind), kind)

    def test_a_word_the_dictionary_can_settle_by_itself_wants_none(self):
        """40 of the 58 settled kinds are this case, and cost nothing."""
        for kind in ("bottle", "book", "broom", "flyer"):
            self.assertFalse(kinds.needs_anchor(kind), kind)
            self.assertIn(".n.", kinds.canonical(kind), kind)

    def test_a_word_whose_senses_disagree_wants_a_choice_and_not_an_anchor(self):
        """
        Three states, three different answers, and only one is an anchor.

        `key` and `cup` arrive ungrounded but have senses, and which sense is
        meant is a fact about the room -- so a generator that can see the room
        is asked, by `lexicon.sense_prompt`. An anchor would be answering a
        question nobody asked.
        """
        for kind in ("key", "cup", "chest"):
            self.assertFalse(kinds.needs_anchor(kind), kind)
            self.assertTrue(lexicon.sense_prompt(kind), kind)

    def test_nothing_wants_nothing(self):
        self.assertFalse(kinds.needs_anchor(""))
        self.assertFalse(kinds.needs_anchor(None))


@tag("unit")
class FollowingTheAnchor(SimpleTestCase):

    def test_grounding_a_kind_gives_it_the_ancestry_it_never_had(self):
        """
        The measurement that made this half of phase 1 bigger than planned.

        Of 58 kinds the exported worlds had settled, 7 had any ancestry at
        all: the rest were bare words. Not the invented ones -- `bottle`,
        `book` and `broom`. Grounding takes it to 45 of 56, for nothing.
        """
        self.assertEqual(kinds.canonical("bottle"), "bottle.n.01")
        self.assertTrue(kinds.ancestors(None, "bottle"))
        self.assertEqual(kinds.floor(None, "book"), {"read": True})

    def test_an_unanchored_invented_kind_has_no_ancestry_at_all(self):
        """The state of things before this, and the reason for it."""
        self.assertEqual(kinds.ancestors(None, "datapad"), frozenset())
        self.assertEqual(kinds.floor(None, "datapad"), {})

    def test_an_anchored_kind_walks_through_its_anchor(self):
        root = FakeRoot({"datapad": {"under": "publication.n.01"}})
        chain = kinds.ancestors(root, "datapad")
        self.assertIn("publication.n.01", chain)
        self.assertIn("entity.n.01", chain, "and everything above it")

    def test_and_takes_a_floor_from_it(self):
        """The win. A datapad under `publication` can be read."""
        root = FakeRoot({"datapad": {"under": "publication.n.01"}})
        self.assertEqual(kinds.floor(root, "datapad"), {"read": True})

    def test_a_real_sense_ignores_any_anchor_it_was_given(self):
        root = FakeRoot({"book.n.01": {"under": "weapon.n.01"}})
        self.assertNotIn("weapon.n.01", kinds.ancestors(root, "book.n.01"))
        self.assertEqual(kinds.floor(root, "book.n.01"), {"read": True})

    def test_an_anchor_wordnet_does_not_know_is_not_believed(self):
        """
        Worse than no anchor, if it were trusted: everything downstream would
        take the kind for grounded when it is not.
        """
        root = FakeRoot({"datapad": {"under": "dataslate.n.01"}})
        self.assertEqual(kinds.anchor(root, "datapad"), "")
        self.assertEqual(kinds.ancestors(root, "datapad"), frozenset())

    def test_a_spec_with_no_anchor_is_no_anchor(self):
        root = FakeRoot({"datapad": {"affordances": {"read": True}}})
        self.assertEqual(kinds.anchor(root, "datapad"), "")


@tag("unit")
class PruningThroughTheAnchor(SimpleTestCase):

    def test_the_taxonomy_still_prunes_what_it_implies(self):
        self.assertEqual(kinds.prune(["sword.n.01", "weapon.n.01"]),
                         ["sword.n.01"])

    def test_an_anchored_kind_and_its_anchor_are_one_thing(self):
        """
        A "datapad, device" is a datapad, the way a "sword, weapon" is a sword.
        Without the anchor both names survive and the world holds two kinds
        where it means one.
        """
        root = FakeRoot({"datapad": {"under": "device.n.01"}})
        self.assertEqual(kinds.prune(["datapad", "device.n.01"], root),
                         ["datapad"])
        self.assertEqual(kinds.prune(["datapad", "device.n.01"]),
                         ["datapad", "device.n.01"],
                         "and without the world there is nothing to know it by")

    def test_genuinely_separate_kinds_both_survive(self):
        root = FakeRoot({"datapad": {"under": "device.n.01"}})
        self.assertEqual(kinds.prune(["sword.n.01", "inscription.n.01"], root),
                         ["sword.n.01", "inscription.n.01"])


@tag("unit")
class TellingABadSenseFromAGoodOne(SimpleTestCase):
    """
    The third signal, and the one that costs nothing.

    A single-sense word is never asked about, so `blaster` -- whose only
    WordNet sense is "a workman employed to blast with explosives" -- becomes a
    kind of person for the life of the world. The generator said it is
    wieldable and takeable. A person is neither, and that is computable.
    """

    def test_a_takeable_person_is_a_contradiction(self):
        self.assertEqual(
            kinds.sense_contradicts("blaster.n.01", ["wield"], True), "person")

    def test_so_is_a_takeable_building(self):
        self.assertEqual(
            kinds.sense_contradicts("structure.n.01", [], True), "structure")

    def test_an_ordinary_object_contradicts_nothing(self):
        for sense in ("chest.n.02", "book.n.01", "sword.n.01", "bottle.n.01"):
            self.assertEqual(
                kinds.sense_contradicts(sense, ["open", "get"], True), "",
                sense)

    def test_a_person_nobody_claimed_to_pick_up_is_fine(self):
        """Characters are kinds too. Only the clash is a signal."""
        self.assertEqual(kinds.sense_contradicts("person.n.01", [], False), "")

    def test_the_case_this_deliberately_misses(self):
        """
        Recorded so the limit is known rather than discovered.

        A virtual reality `pod` lands on "the vessel that contains the seeds of
        a plant", whose bucket is nothing at all -- so no declared affordance
        can contradict it, and this says nothing. Finding that class needs a
        different signal; see docs/rulebooks-from-inform.md 7.
        """
        self.assertEqual(lexicon.buckets("pod.n.01"), frozenset())
        self.assertEqual(kinds.sense_contradicts("pod.n.01", ["enter"], True),
                         "")


@tag("unit")
class SettlingAKind(SimpleTestCase):

    def test_an_anchor_is_stored_with_the_kind(self):
        root = FakeRoot()
        kinds.remember(root, "datapad", {"read": True},
                       under="publication.n.01")
        self.assertEqual(root.db.kind_specs["datapad"]["under"],
                         "publication.n.01")

    def test_and_the_floor_it_brings_is_applied(self):
        root = FakeRoot()
        granted = kinds.remember(root, "holodeck", {"enter": True},
                                 under="publication.n.01")
        self.assertTrue(granted["read"], "the anchor's floor wins")
        self.assertTrue(granted["enter"], "and what was declared survives")

    def test_an_unknown_anchor_is_not_stored(self):
        root = FakeRoot()
        kinds.remember(root, "datapad", {"read": True}, under="nonsense.n.99")
        self.assertNotIn("under", root.db.kind_specs["datapad"])

    def test_a_real_sense_is_not_given_an_anchor(self):
        root = FakeRoot()
        kinds.remember(root, "book.n.01", {}, under="weapon.n.01")
        self.assertNotIn("under", root.db.kind_specs["book.n.01"])

    def test_a_word_whose_senses_disagree_takes_one_too(self):
        """
        Not only a word the dictionary has never heard of, which is what this
        accepted before and is the narrower question `needs_anchor` answers.

        `box` has senses and they straddle a bucket, so `canonical` leaves the
        bare word -- and nothing anywhere ever chose between them, so the kind
        sat with no taxonomy above it for good. 37 of 192 kinds across the two
        phase 13 soak worlds are this, and they are `box`, `key`, `knife`,
        `pen`, `shoe`, `wheel`: ordinary words, not invented ones.
        """
        root = FakeRoot()
        kinds.remember(root, "box", {"get": True}, under="box.n.01")
        self.assertEqual(root.db.kind_specs["box"]["under"], "box.n.01")

    def test_and_then_a_rule_about_containers_can_reach_it(self):
        """The whole point of an anchor, asserted on the case that was missing."""
        root = FakeRoot({"box": {"under": "box.n.01"}})
        self.assertTrue(kinds.is_a(root, "box", "container.n.01"))

    def test_the_prompt_asks_for_both_cases(self):
        rule = kinds.anchor_rule()
        self.assertIn("never heard of", rule)
        self.assertIn("several unrelated things", rule)

    def test_the_first_answer_still_stands(self):
        """Unchanged, and the reason is unchanged: revising a kind orphans
        every rule that was learned against its old affordances."""
        root = FakeRoot()
        kinds.remember(root, "datapad", {"read": True})
        again = kinds.remember(root, "datapad", {"burn": True})
        self.assertEqual(again, {"read": True})


@tag("unit")
class WithNoDictionary(SimpleTestCase):
    """`kinds` inherits `lexicon`'s promise: clumsier, never impossible."""

    def test_everything_answers_without_raising(self):
        with mock.patch.object(lexicon, "_wordnet", lambda: None):
            root = FakeRoot({"datapad": {"under": "publication.n.01"}})
            self.assertEqual(kinds.ancestors(root, "datapad"), frozenset())
            self.assertEqual(kinds.floor(root, "datapad"), {})
            self.assertEqual(kinds.anchor(root, "datapad"), "")
            self.assertEqual(kinds.sense_contradicts("blaster.n.01",
                                                     ["wield"], True), "")
            # A kind is still a kind, and still prunes duplicates by name.
            self.assertEqual(kinds.prune(["datapad", "datapad"], root),
                             ["datapad"])
