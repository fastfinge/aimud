"""
Crafting, as rules a world writes for itself.

The question this answers is the one from `docs/future-plans.md`: could our
rules express everything Evennia's crafting contrib does? The answer turned
out to be "almost, and the three gaps are one" -- counting, matching by sort,
and telling an effect what a condition found. Those are `world.quantity` and
the found sets, and they are tested where they live.

What is tested here is the join: that with all of it in place, a recipe really
is an ordinary rule, and needs nothing crafting-shaped underneath it.

**The ruleset ships the frame and no recipes**, which is the whole argument
against copying the contrib. A recipe is a fact about one world -- what iron
and wood make *here* -- and belongs with that world's other rules, where it
can be read, replaced, scoped to a room, and proposed by `suggest` from what
players kept trying. So the recipes below are written by the test, the way a
world or a model would write them.

**Typed inputs-first, and that is not a stylistic choice.** `docs/rulesets.md`
§1.1 argued that the contrib's `craft <recipe> from <stuff>` is the wrong
syntax here, because `verbs.bind` binds nouns to things that exist and a blade
being forged does not exist yet -- so `forge a blade` would conjure the blade
and then run the rule that makes it. The first draft of this file typed
exactly that and walked into exactly that: every recipe test reached for a
model to invent a blade. `forge`, naming the result not at all and reading
what is in hand, is the idiom -- and it is also the one the endless-alchemy
world in future-plans wants.
"""

from django.test import tag

from tests import test_phases
from world import kinds, rulebooks as R
from world import rulesets, verbs


@tag("world")
class TheFrame(test_phases.RunningTheAttempt):

    def setUp(self):
        super().setUp()
        rulesets.seed(self.root, ["crafting"])

    def test_the_verbs_it_folds(self):
        for word in ("forge", "craft", "brew"):
            self.assertEqual(verbs.canonical_verb(word, self.root), "make")
        for word in ("mix", "blend"):
            self.assertEqual(verbs.canonical_verb(word, self.root), "combine")

    def test_and_only_for_a_world_that_chose_it(self):
        self.assertEqual(verbs.canonical_verb("forge"), "forge")

    def test_combining_takes_two_things_you_are_holding(self):
        from world import actions

        spec = actions.spec(self.root, "combine")
        roles = {role["role"]: role for role in spec["applies_to"]}
        self.assertEqual(roles["direct"]["access"], "carried")
        self.assertEqual(roles["instrument"]["access"], "carried")

    def test_it_ships_no_recipes(self):
        """A recipe is a fact about one world, not about crafting."""
        names = [r["name"] for r in R.all_rules(self.root)
                 if rulesets.from_ruleset(r, "crafting")]
        self.assertEqual(len(names), 2, names)


@tag("world")
class ARecipeAWorldWrote(test_phases.RunningTheAttempt):
    """
    Two lumps of coal and an iron bar make a blade.

    Written as a world would write it: a check rule that counts what is
    needed and files it, and a carry-out that consumes exactly those and
    makes the result.
    """

    def setUp(self):
        super().setUp()
        rulesets.seed(self.root, ["crafting"])
        for verb in ("combine", "make"):
            kinds.admit(self.root, ["coal.n.01"], verb, True)
            kinds.admit(self.root, ["iron.n.01"], verb, True)

    def stuff(self, key, kind, how_many=1):
        from evennia import create_object

        made = []
        for _ in range(how_many):
            obj = create_object("typeclasses.objects.Object", key=key,
                                location=self.char1)
            obj.db.kinds = [kind]
            obj.db.affordances = {"combine": True}
            made.append(obj)
        return made

    def recipe(self):
        R.add(self.root, R.blank(
            action="make", phase=R.CHECK, scope={"world": True},
            name="a blade needs iron and two coals", about="actor",
            conditions=[
                {"subject": "actor",
                 "holds": {"of_kind": "iron.n.01", "as": "metal"}},
                {"subject": "actor",
                 "holds": {"of_kind": "coal.n.01", "count": 2,
                           "as": "fuel"}},
            ]))
        R.add(self.root, R.blank(
            action="make", phase=R.CARRY_OUT, scope={"world": True},
            name="and this is what forging one does",
            effects=[
                {"type": "destroy_object", "name_role": "fuel"},
                {"type": "destroy_object", "name_role": "metal"},
                {"type": "create_object", "name": "iron blade",
                 "why": "what forging makes", "location": "actor"},
            ]))

    def blades(self):
        return [obj for obj in self.char1.contents if "blade" in obj.key]

    def test_with_the_makings_you_get_a_blade(self):
        iron = self.stuff("iron bar", "iron.n.01")
        coal = self.stuff("lump of coal", "coal.n.01", 2)
        self.recipe()
        self.try_it("forge")
        self.assertEqual(len(self.blades()), 1)
        for used in iron + coal:
            self.assertIsNone(used.pk, "the makings should be used up")

    def test_without_them_you_are_told_what_is_missing(self):
        self.stuff("iron bar", "iron.n.01")
        self.recipe()
        said = self.try_it("forge")
        self.assertIn("coal", said.lower())
        self.assertEqual(self.blades(), [])

    def test_and_a_shortfall_says_how_many_more(self):
        self.stuff("iron bar", "iron.n.01")
        self.stuff("lump of coal", "coal.n.01", 1)
        self.recipe()
        said = self.try_it("forge")
        self.assertIn("one more", said.lower())

    def test_only_what_the_recipe_asked_for_is_consumed(self):
        """Three coals in the pack, a recipe for two: one is left."""
        self.stuff("iron bar", "iron.n.01")
        coal = self.stuff("lump of coal", "coal.n.01", 3)
        self.recipe()
        self.try_it("forge")
        self.assertEqual(len([c for c in coal if c.pk is not None]), 1)

    def test_an_iron_key_is_not_iron(self):
        """
        The bug the whole of this rests on. `holds` used to match a substring
        of what a thing is called, so a recipe wanting iron was answered by
        anything with "iron" in its name.
        """
        from evennia import create_object

        key = create_object("typeclasses.objects.Object", key="iron key",
                            location=self.char1)
        key.db.kinds = ["key.n.01"]
        self.stuff("lump of coal", "coal.n.01", 2)
        self.recipe()
        self.try_it("forge")
        self.assertEqual(self.blades(), [])
        self.assertIsNotNone(key.pk)


@tag("world")
class WhatTheFrameRefuses(test_phases.RunningTheAttempt):
    loose_objects = 2

    def setUp(self):
        super().setUp()
        rulesets.seed(self.root, ["crafting"])
        self.obj2.key = "brick"
        self.obj2.db.kinds = ["brick.n.01"]
        kinds.admit(self.root, ["book.n.01"], "combine", True)
        kinds.admit(self.root, ["brick.n.01"], "combine", True)

    def test_you_cannot_combine_what_does_not_go_together(self):
        """
        The one thing the frame itself says. Inform ships a handful of these
        and they are why an author writes so little; this is the crafting
        one, and it stops `combine the innkeeper with the table` reaching a
        model at all.
        """
        self.obj1.move_to(self.char1, quiet=True)
        self.obj2.move_to(self.char1, quiet=True)
        said = self.try_it("combine book with brick")
        self.assertNotIn("You do it", said)
