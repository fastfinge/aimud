"""
How many of what sort.

`world.quantity` is one question asked in six places, so it is tested in two
parts: the spec reader on its own, which needs no world at all, and the four
predicates that count over it, which need things to count.

The counting cases are written as the requirements that wanted them -- two
lumps of coal for a recipe, no more than one hat for a wardrobe -- rather than
as arithmetic, because the arithmetic is three lines and the thing that can go
wrong is what a rule *means*.
"""

from django.test import SimpleTestCase, tag

from tests.base import GameTest
from world import conditions as C
from world import quantity, verbs


class ReadingASpec(SimpleTestCase):
    """The spec reader, which is the whole of the new vocabulary."""

    def test_a_bare_word_is_a_name_and_means_one(self):
        spec = quantity.read("brass key")
        self.assertEqual(spec["of_name"], "brass key")
        self.assertEqual(spec["count"], 1)
        self.assertEqual(spec["of_kind"], "")

    def test_an_article_is_dropped_so_both_spellings_match_alike(self):
        self.assertEqual(quantity.read("a brass key")["of_name"], "brass key")
        self.assertEqual(quantity.read("the brass key")["of_name"], "brass key")

    def test_a_role_is_read_as_a_role_only_when_one_is_expected(self):
        """
        With no attempt in front of it a bare word is always a name.

        The safe reading of the two: a name that matches nothing refuses, and
        a role that matches nothing would quietly pass.
        """
        self.assertEqual(quantity.read("direct")["of_name"], "direct")
        self.assertEqual(
            quantity.read("direct", roles=C.ROLES)["role"], "direct")

    def test_a_sort_and_a_number(self):
        spec = quantity.read({"of_kind": "coal.n.01", "count": 2})
        self.assertEqual(spec["of_kind"], "coal.n.01")
        self.assertEqual(spec["count"], 2)

    def test_the_names_a_model_is_likely_to_reach_for(self):
        """`named` and `kind` are what a *subject* is written with already."""
        self.assertEqual(quantity.read({"named": "key"})["of_name"], "key")
        self.assertEqual(quantity.read({"kind": "coal.n.01"})["of_kind"],
                         "coal.n.01")

    def test_a_role_written_as_a_name_is_still_a_role(self):
        spec = quantity.read({"of_name": "direct"}, roles=C.ROLES)
        self.assertEqual(spec["role"], "direct")
        self.assertEqual(spec["of_name"], "")

    def test_a_count_over_the_ceiling_is_refused_rather_than_trimmed(self):
        """A requirement cut down to fit asks for something else."""
        self.assertIsNone(
            quantity.read({"of_kind": "coal.n.01",
                           "count": quantity.MAX_COUNT + 1}))

    def test_nonsense_is_refused(self):
        self.assertIsNone(quantity.read({"of_kind": "coal.n.01", "count": 0}))
        self.assertIsNone(quantity.read({"of_kind": "coal.n.01",
                                         "count": "some"}))
        self.assertIsNone(quantity.read({"count": 2}))
        self.assertIsNone(quantity.read(""))
        self.assertIsNone(quantity.read(None))

    def test_one_unreadable_item_is_reported_and_not_swallowed(self):
        specs, ok = quantity.read_all(["coal", {"count": 2}])
        self.assertFalse(ok)
        self.assertEqual(len(specs), 1)

    def test_a_mapping_is_one_item_and_does_not_come_apart(self):
        """
        The `model_json.listed` trap, one level up.

        Read by type, a stored mapping is not a dict and falls through to the
        sequence case -- where it comes apart into its keys, and a recipe for
        two lumps of coal becomes a requirement to carry an "of_kind".
        """
        specs, ok = quantity.read_all({"of_kind": "coal.n.01", "count": 2})
        self.assertTrue(ok)
        self.assertEqual(len(specs), 1)
        self.assertEqual(specs[0]["count"], 2)


class SayingWhatIsWanted(SimpleTestCase):

    def test_a_named_thing_is_definite_because_a_rule_means_that_thing(self):
        self.assertEqual(quantity.said(quantity.read("brass key")),
                         "the brass key")

    def test_a_number_is_indefinite_because_no_two_in_particular_are_meant(self):
        said = quantity.said(quantity.read({"of_name": "apple", "count": 3}))
        self.assertEqual(said, "three apples")

    def test_what_is_still_wanted_rather_than_the_whole_requirement(self):
        """Somebody holding two of three is told what to do next."""
        spec = quantity.read({"of_name": "apple", "count": 3})
        self.assertEqual(quantity.shortfall(["a", "b"], spec), "one more apple")
        self.assertEqual(quantity.shortfall(["a", "b", "c"], spec), "")

    def test_nothing_held_yet_asks_for_the_whole_of_it(self):
        spec = quantity.read({"of_name": "apple", "count": 3})
        self.assertEqual(quantity.shortfall([], spec), "three apples")


@tag("world")
class Counting(GameTest):
    """The four predicates, over things that really are in a world."""

    def setUp(self):
        super().setUp()
        self.root = self.room1
        self.root.db.is_world_root = True
        self.room1.db.world_root = self.root
        self.ctx = C.context(actor=self.char1, world_root=self.root)

    def make(self, key, kind="", where=None, worn=False):
        from evennia import create_object

        obj = create_object("typeclasses.objects.Object", key=key,
                            location=where or self.char1)
        if kind:
            obj.db.kinds = [kind]
        if worn:
            verbs.apply_states(obj, add=["worn"], world_root=self.root)
        return obj

    # -- counting ---------------------------------------------------------

    def test_a_recipe_wanting_two_is_not_answered_by_one(self):
        self.make("lump of coal", "coal.n.01")
        wanted = {"subject": "actor",
                  "holds": {"of_kind": "coal.n.01", "count": 2}}
        self.assertFalse(C.evaluate(wanted, self.ctx))
        self.make("lump of coal", "coal.n.01")
        self.assertTrue(C.evaluate(wanted, self.ctx))

    def test_and_says_how_many_are_still_wanted(self):
        self.make("lump of coal", "coal.n.01")
        said = C.describe({"subject": "actor",
                           "holds": {"of_kind": "coal.n.01", "count": 2}},
                          self.ctx, mood=C.WANT)
        self.assertIn("one more", said)

    def test_an_uncounted_clause_still_means_exactly_what_it_did(self):
        wanted = {"subject": "actor", "holds": ["brass key"]}
        self.assertFalse(C.evaluate(wanted, self.ctx))
        self.make("brass key")
        self.assertTrue(C.evaluate(wanted, self.ctx))

    # -- sort beats spelling ----------------------------------------------

    def test_iron_is_not_answered_by_an_iron_key(self):
        """
        The bug this whole module started from: `holds` matched a substring of
        what a thing was called, so a rule about iron was satisfied by
        anything with "iron" in its name.
        """
        self.make("iron key", "key.n.01")
        self.assertFalse(C.evaluate(
            {"subject": "actor", "holds": {"of_kind": "iron.n.01"}}, self.ctx))

    def test_but_a_sort_covers_its_sorts(self):
        """A rule about wood is answered by an oak plank."""
        self.make("oak plank", "oak.n.01")
        self.assertTrue(C.evaluate(
            {"subject": "actor", "holds": {"of_kind": "wood.n.01"}}, self.ctx))

    def test_a_name_still_matches_by_name_for_a_rule_that_means_one_thing(self):
        self.make("iron key", "key.n.01")
        self.assertTrue(C.evaluate(
            {"subject": "actor", "holds": {"of_name": "iron key"}}, self.ctx))

    # -- wearing ----------------------------------------------------------

    def test_fewer_than_this_many_worn(self):
        """
        `not_wears` with a count of two is "fewer than two hats", which is
        true of somebody wearing one and false of somebody wearing two.

        Worth being careful about where this is used as a *limit*, and the
        clothing ruleset got it wrong first time round. A check rule runs
        before the thing it guards, so "you may wear only one hat" is `count:
        1` -- be wearing fewer than one hat *before* putting one on -- and
        `count: 2` would let the second one through and refuse the third.
        """
        limit = {"subject": "actor",
                 "not_wears": {"of_kind": "hat.n.01", "count": 2}}
        self.assertTrue(C.evaluate(limit, self.ctx))
        self.make("straw hat", "hat.n.01", worn=True)
        self.assertTrue(C.evaluate(limit, self.ctx))
        self.make("felt hat", "hat.n.01", worn=True)
        self.assertFalse(C.evaluate(limit, self.ctx))

    def test_carried_but_not_worn_does_not_count_as_worn(self):
        self.make("straw hat", "hat.n.01")
        self.assertFalse(C.evaluate(
            {"subject": "actor", "wears": {"of_kind": "hat.n.01"}}, self.ctx))

    # -- the mirror -------------------------------------------------------

    def test_the_opposite_of_at_least_two_is_fewer_than_two(self):
        wanted = {"subject": "actor",
                  "holds": {"of_kind": "coal.n.01", "count": 2}}
        mirror = C.negate(wanted)
        self.assertIsNotNone(mirror)
        self.assertTrue(C.evaluate(mirror, self.ctx))
        self.make("lump of coal", "coal.n.01")
        self.assertTrue(C.evaluate(mirror, self.ctx))
        self.make("lump of coal", "coal.n.01")
        self.assertFalse(C.evaluate(mirror, self.ctx))

    def test_and_the_uncounted_pair_still_mirrors_as_it_did(self):
        wanted = {"subject": "actor", "holds": ["brass key"]}
        mirror = C.negate(wanted)
        self.assertTrue(C.evaluate(mirror, self.ctx))
        self.make("brass key")
        self.assertFalse(C.evaluate(mirror, self.ctx))

    # -- refusing what cannot be read -------------------------------------

    def test_a_requirement_nobody_can_read_is_never_stored(self):
        self.assertIsNone(C.normalise(
            {"subject": "actor", "holds": {"count": 99}}))

    def test_and_fails_closed_if_one_ever_reaches_the_gate(self):
        """
        Both ways round. A check rule is what stands between an action and the
        world, and one that gives up quietly lets the action through.
        """
        self.assertFalse(C.evaluate(
            {"subject": "actor", "holds": {"count": 99}}, self.ctx))
        self.assertFalse(C.evaluate(
            {"subject": "actor", "not_holds": {"count": 99}}, self.ctx))
