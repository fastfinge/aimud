"""
What a condition found, named by the effects of the same rule.

A condition could find things and an effect could only name a role somebody
typed. So a check rule could count two lumps of coal and the carry-out that
was to consume them had no way to ask which two -- it could only search again,
and a second search may answer differently.

A spec with an `as` files what it matched under that name; `effects` reads it.
The tests here are about the join between the two halves, so they run whole
attempts through the pipeline rather than calling either half directly.
"""

from django.test import tag

from tests import test_phases
from world import rulebooks as R
from world import conditions as C
from world import effects, kinds, verbs


@tag("world")
class NamingWhatWasCounted(test_phases.RunningTheAttempt):

    def setUp(self):
        super().setUp()
        for verb in ("burn", "stoke"):
            kinds.admit(self.root, self.obj1.db.kinds, verb, True)

    def coal(self, how_many, key="lump of coal"):
        from evennia import create_object

        made = []
        for _ in range(how_many):
            obj = create_object("typeclasses.objects.Object", key=key,
                                location=self.char1)
            obj.db.kinds = ["coal.n.01"]
            made.append(obj)
        return made

    def recipe(self, count=2):
        """A check that counts the fuel, and a carry-out that consumes it."""
        R.add(self.root, R.blank(
            action="read", phase=R.CHECK, scope={"world": True},
            name="you must have the fuel", about="actor",
            conditions=[{"subject": "actor",
                         "holds": {"of_kind": "coal.n.01", "count": count,
                                   "as": "fuel"}}]))
        R.add(self.root, R.blank(
            action="read", phase=R.CARRY_OUT, scope={"world": True},
            name="and it is used up",
            effects=[{"type": "destroy_object", "name_role": "fuel"}]))

    def test_the_things_the_check_counted_are_the_things_consumed(self):
        lumps = self.coal(2)
        self.recipe()
        self.try_it("read book")
        for lump in lumps:
            self.assertIsNone(lump.pk, "the counted coal should be gone")

    def test_and_only_as_many_as_it_asked_for(self):
        """
        Three in the pack, a recipe for two: one lump is left.

        `quantity.matching` stops at what was asked for, so a rule that files
        what it found files the number in the requirement rather than
        everything in the pack.
        """
        lumps = self.coal(3)
        self.recipe(count=2)
        self.try_it("read book")
        left = [lump for lump in lumps if lump.pk is not None]
        self.assertEqual(len(left), 1)

    def test_nothing_is_consumed_when_the_check_refuses(self):
        lumps = self.coal(1)
        self.recipe(count=2)
        self.try_it("read book")
        self.assertIsNotNone(lumps[0].pk)

    def test_a_set_can_be_moved_as_well_as_destroyed(self):
        lumps = self.coal(2)
        R.add(self.root, R.blank(
            action="read", phase=R.CHECK, scope={"world": True},
            name="you must have the fuel", about="actor",
            conditions=[{"subject": "actor",
                         "holds": {"of_kind": "coal.n.01", "count": 2,
                                   "as": "fuel"}}]))
        R.add(self.root, R.blank(
            action="read", phase=R.CARRY_OUT, scope={"world": True},
            name="and it is set down",
            effects=[{"type": "move_object", "name_role": "fuel",
                      "to": "room"}]))
        self.try_it("read book")
        for lump in lumps:
            self.assertIs(lump.location, self.room1)

    def test_a_set_can_be_put_into_a_state(self):
        lumps = self.coal(2)
        R.add(self.root, R.blank(
            action="read", phase=R.CHECK, scope={"world": True},
            name="you must have the fuel", about="actor",
            conditions=[{"subject": "actor",
                         "holds": {"of_kind": "coal.n.01", "count": 2,
                                   "as": "fuel"}}]))
        R.add(self.root, R.blank(
            action="read", phase=R.CARRY_OUT, scope={"world": True},
            name="and it catches",
            effects=[{"type": "set_state", "role": "fuel",
                      "add": ["burning"]}]))
        self.try_it("read book")
        for lump in lumps:
            self.assertIn("burning", verbs.states(lump))

    def test_an_after_rule_may_name_what_its_own_guard_found(self):
        lumps = self.coal(2)
        R.add(self.root, R.blank(
            action="read", phase=R.AFTER, scope={"world": True},
            name="reading by coal-light burns it", about="actor",
            when=[{"subject": "actor",
                   "holds": {"of_kind": "coal.n.01", "count": 2,
                             "as": "fuel"}}],
            effects=[{"type": "destroy_object", "name_role": "fuel"}]))
        self.try_it("read book")
        for lump in lumps:
            self.assertIsNone(lump.pk)

    def test_a_name_is_local_to_the_rule_that_named_it(self):
        """
        Two after rules, both using the word "fuel" for different things.

        They are different rules, written at different times by different
        people, and the second must not act on what the first happened to
        find. Here the second rule's guard fails, so it finds nothing and its
        effect has nothing to destroy -- and the coal survives.
        """
        lumps = self.coal(1)
        R.add(self.root, R.blank(
            action="read", phase=R.AFTER, scope={"world": True},
            name="one rule's fuel", about="actor",
            when=[{"subject": "actor",
                   "holds": {"of_kind": "coal.n.01", "as": "fuel"}}],
            effects=[{"type": "set_state", "role": "fuel",
                      "add": ["warm"]}]))
        R.add(self.root, R.blank(
            action="read", phase=R.AFTER, scope={"world": True},
            name="another rule's fuel", about="actor",
            when=[{"subject": "actor",
                   "holds": {"of_kind": "peat.n.01", "as": "fuel"}}],
            effects=[{"type": "destroy_object", "name_role": "fuel"}]))
        self.try_it("read book")
        self.assertIsNotNone(lumps[0].pk)
        self.assertIn("warm", verbs.states(lumps[0]))

    def test_a_role_nobody_filed_is_still_one_thing(self):
        """Every effect already written names a single role, and still does."""
        self.coal(1)
        R.add(self.root, R.blank(
            action="read", phase=R.CARRY_OUT, scope={"world": True},
            name="the book crumbles",
            effects=[{"type": "destroy_object", "name_role": "direct"}]))
        self.try_it("read book")
        self.assertIsNone(self.obj1.pk)


@tag("world")
class WhatASetMayNotBe(test_phases.RunningTheAttempt):
    """
    `everyone` stays confined to the two effects it was confined to.

    On the record: `crowds=False` is belt and braces here rather than the only
    thing standing in the way. A crowd is only ever people, and `_protected`
    refuses to destroy or move a character in any case, so these would pass
    without it. It is still worth declaring -- an effect should say what it
    accepts rather than rely on something further down to refuse, and the day
    a crowd means anything other than people the declaration is what holds.
    """

    characters = 2

    def test_destroying_everyone_present_is_still_not_a_sentence(self):
        R.add(self.root, R.blank(
            action="read", phase=R.CARRY_OUT, scope={"world": True},
            name="a terrible book",
            effects=[{"type": "destroy_object", "name_role": "everyone"}]))
        self.try_it("read book")
        self.assertIsNotNone(self.char2.pk)

    def test_but_a_crowd_may_still_be_put_into_a_state(self):
        R.add(self.root, R.blank(
            action="read", phase=R.CARRY_OUT, scope={"world": True},
            name="read aloud, and everyone shivers",
            effects=[{"type": "set_state", "role": "everyone",
                      "add": ["uneasy"]}]))
        self.try_it("read book")
        self.assertIn("uneasy", verbs.states(self.char2))
