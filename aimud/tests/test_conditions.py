"""
One condition language, tested against both of the two it replaces.

The point of this module is that four things stop having their own opinion
about what "the chest must be open" means. So the tests are in three parts:
each predicate on its own; the two adapters, which have to read every shape
already stored in the corpus; and `achieves`, which is the planner's half and
the one that goes wrong silently.

`achieves` gets a table over every predicate crossed with every effect type,
because that is the invertibility ground rule and a hole in it does not show
up as a failure -- it shows up as an NPC standing still.
"""

from django.test import SimpleTestCase, tag
from evennia.utils.test_resources import EvenniaTest

from tests.support import all_rules, worlds
from world import conditions as C
from world import verbs, zones


@tag("world")
class Predicates(EvenniaTest):

    def setUp(self):
        super().setUp()
        self.root = self.room1
        self.root.db.is_world_root = True
        self.room1.db.world_root = self.root
        self.room2.db.world_root = self.root
        self.ctx = C.context(bound={"direct": self.obj1}, actor=self.char1,
                             world_root=self.root)

    def test_a_state_the_thing_is_in(self):
        verbs.apply_states(self.obj1, add=["open"], world_root=self.root)
        self.assertTrue(C.evaluate({"subject": "direct", "is": ["open"]},
                                   self.ctx))
        self.assertFalse(C.evaluate({"subject": "direct", "is": ["locked"]},
                                    self.ctx))

    def test_a_state_it_must_not_be_in(self):
        self.assertTrue(C.evaluate({"subject": "direct", "lacks": ["burning"]},
                                   self.ctx))
        verbs.apply_states(self.obj1, add=["burning"], world_root=self.root)
        self.assertFalse(C.evaluate({"subject": "direct", "lacks": ["burning"]},
                                    self.ctx))

    def test_what_can_be_done_to_it(self):
        self.obj1.db.affordances = {"read": True}
        self.assertTrue(C.evaluate({"subject": "direct", "affords": ["read"]},
                                   self.ctx))
        self.assertFalse(C.evaluate({"subject": "direct", "affords": ["burn"]},
                                    self.ctx))

    def test_an_adjective_where_a_verb_was_meant_still_reads(self):
        """
        39 of the first 42 requirements written after the vocabulary changed
        were adjectives. `verbs._wanted_affordances` folded them; so does this.
        """
        self.obj1.db.affordances = {"read": True}
        self.assertTrue(
            C.evaluate({"subject": "direct", "affords": ["readable"]},
                       self.ctx))

    def test_what_sort_of_thing_it_is(self):
        self.obj1.db.kinds = ["sword.n.01"]
        self.assertTrue(
            C.evaluate({"subject": "direct", "kind": "weapon.n.01"}, self.ctx))
        self.assertFalse(
            C.evaluate({"subject": "direct", "kind": "food.n.01"}, self.ctx))

    def test_holding_something_by_role(self):
        """"To throw it you must be holding it" is about whatever is thrown."""
        self.assertFalse(
            C.evaluate({"subject": "actor", "holds": ["direct"]}, self.ctx))
        self.obj1.move_to(self.char1, quiet=True)
        self.assertTrue(
            C.evaluate({"subject": "actor", "holds": ["direct"]}, self.ctx))

    def test_holding_something_by_name(self):
        self.obj1.move_to(self.char1, quiet=True)
        self.assertTrue(
            C.evaluate({"subject": "actor", "holds": ["Obj"]}, self.ctx))
        self.assertFalse(
            C.evaluate({"subject": "actor", "holds": ["brass key"]}, self.ctx))

    def test_wearing_something(self):
        self.obj1.move_to(self.char1, quiet=True)
        self.assertFalse(
            C.evaluate({"subject": "actor", "wears": ["Obj"]}, self.ctx))
        self.obj1.db.worn = True
        self.assertTrue(
            C.evaluate({"subject": "actor", "wears": ["Obj"]}, self.ctx))

    def test_a_figure_a_person_must_reach(self):
        from world import traits

        traits.ensure(self.char1, "stamina", world_root=self.root, base=20)
        self.assertTrue(
            C.evaluate({"subject": "actor", "trait": "stamina", "min": 10},
                       self.ctx))
        self.assertFalse(
            C.evaluate({"subject": "actor", "trait": "stamina", "min": 50},
                       self.ctx))

    def test_where_somebody_is(self):
        self.room2.db.room_title = "The Library"
        self.char1.move_to(self.room2, quiet=True)
        self.assertTrue(
            C.evaluate({"subject": "actor", "in_room": "Library"}, self.ctx))
        self.assertFalse(
            C.evaluate({"subject": "actor", "in_room": "Kitchen"}, self.ctx))

    def test_a_condition_about_nothing_at_all_is_not_met(self):
        empty = C.context(bound={}, actor=self.char1, world_root=self.root)
        self.assertFalse(C.evaluate({"subject": "direct", "is": ["open"]},
                                    empty))

    def test_but_a_lacks_about_nothing_is_met(self):
        """What is not here is not in that condition, which is the honest read."""
        empty = C.context(bound={}, actor=self.char1, world_root=self.root)
        self.assertTrue(C.evaluate({"subject": "direct", "lacks": ["burning"]},
                                   empty))

    def test_a_condition_with_no_predicate_asks_nothing(self):
        self.assertTrue(C.evaluate({"subject": "direct"}, self.ctx))
        self.assertTrue(C.evaluate({}, self.ctx))



@tag("world")
class WhatIsWithinReach(EvenniaTest):
    """
    Reach used to look only downwards -- your pockets, the floor, inside an
    open box -- because nothing could act on a place. A rule can, now: aboard
    a ship, `power` means powering the ship, and the ship is not something in
    the room. It is the room.
    """

    def setUp(self):
        super().setUp()
        self.root = self.room1
        self.root.db.is_world_root = True
        self.room2.db.world_root = self.root
        self.char1.move_to(self.room2, quiet=True)

    def reaches(self, thing):
        ctx = C.context(bound={"direct": thing}, actor=self.char1,
                        world_root=self.root)
        return C.evaluate({"subject": "direct", "reachable_by": "actor"}, ctx)

    def test_the_place_you_are_standing_in(self):
        self.assertTrue(self.reaches(self.room2))

    def test_and_the_place_that_place_is_part_of(self):
        """A pod inside a ship: the ship is still within reach."""
        self.room2.location = self.room1
        self.assertTrue(self.reaches(self.room1))

    def test_but_not_a_place_you_are_not_in(self):
        self.assertFalse(self.reaches(self.room1))

    def test_a_thing_on_the_floor_is_still_reachable(self):
        self.obj1.move_to(self.room2, quiet=True)
        self.assertTrue(self.reaches(self.obj1))

    def test_and_a_thing_in_another_room_is_still_not(self):
        self.obj1.move_to(self.room1, quiet=True)
        self.assertFalse(self.reaches(self.obj1))

@tag("world")
class SubjectsNobodyNamed(EvenniaTest):
    """The half that `launch` needed."""

    def setUp(self):
        super().setUp()
        self.root = self.room1
        self.root.db.is_world_root = True
        self.room2.db.world_root = self.root
        self.char1.move_to(self.room2, quiet=True)
        self.ctx = C.context(actor=self.char1, world_root=self.root)

    def test_the_room_you_are_in(self):
        verbs.apply_states(self.room2, add=["dark"], world_root=self.root)
        self.assertTrue(C.evaluate({"subject": "here", "is": ["dark"]},
                                   self.ctx))

    def test_the_ship_you_are_in_when_it_is_the_room(self):
        self.room2.db.kinds = ["spacecraft.n.01"]
        verbs.apply_states(self.room2, add=["powered"], world_root=self.root)
        self.assertTrue(C.evaluate(
            {"subject": {"enclosure": "spacecraft.n.01"}, "is": ["powered"]},
            self.ctx))

    def test_the_ship_you_are_in_when_it_is_a_zone(self):
        ship = zones.register(self.root, "Ship")
        zones.set_kind(self.root, ship, "spacecraft.n.01")
        zones.assign(self.root, self.room2, ship)
        zones.apply_states(self.root, ship, add=["powered"])
        self.assertTrue(C.evaluate(
            {"subject": {"enclosure": "spacecraft.n.01"}, "is": ["powered"]},
            self.ctx))

    def test_and_is_not_met_when_the_ship_is_not_powered(self):
        ship = zones.register(self.root, "Ship")
        zones.set_kind(self.root, ship, "spacecraft.n.01")
        zones.assign(self.root, self.room2, ship)
        self.assertFalse(C.evaluate(
            {"subject": {"enclosure": "spacecraft.n.01"}, "is": ["powered"]},
            self.ctx))

    def test_the_innermost_zone_whatever_sort_it_is(self):
        planet = zones.register(self.root, "Kepler Nine")
        zones.assign(self.root, self.room2, planet)
        zones.apply_states(self.root, planet, add=["port_closed"])
        self.assertTrue(C.evaluate(
            {"subject": {"zone": True}, "is": ["port_closed"]}, self.ctx))

    def test_a_ship_that_is_not_there_is_not_met(self):
        self.assertFalse(C.evaluate(
            {"subject": {"enclosure": "spacecraft.n.01"}, "is": ["powered"]},
            self.ctx))


@tag("world")
class SayingIt(EvenniaTest):
    """Two moods, because a want and a refusal are read differently."""

    def setUp(self):
        super().setUp()
        self.root = self.room1
        self.root.db.is_world_root = True
        self.room1.db.world_root = self.root
        self.ctx = C.context(bound={"direct": self.obj1}, actor=self.char1,
                             world_root=self.root)

    def test_a_want_reads_as_something_to_do(self):
        said = C.describe({"subject": "direct", "is": ["open"]}, self.ctx,
                          mood=C.WANT)
        self.assertIn("open", said)
        self.assertTrue(said.startswith("get "), said)

    def test_a_refusal_reads_as_a_complaint(self):
        said = C.describe({"subject": "direct", "is": ["open"]}, self.ctx,
                          mood=C.UNMET)
        self.assertIn("is not open", said)
        self.assertTrue(said.endswith("."), said)

    def test_a_refusal_about_yourself_says_you(self):
        said = C.describe({"subject": "actor", "is": ["seated"]}, self.ctx,
                          mood=C.UNMET)
        self.assertIn("You are not seated", said)

    def test_a_missing_affordance_says_what_it_is_good_for(self):
        """
        The sentence that answers "then what can I do with it?" without
        another attempt, which `verbs.check` went to trouble over.
        """
        self.obj1.db.affordances = {"read": True, "burn": True}
        said = C.describe({"subject": "direct", "affords": ["drink"]},
                          self.ctx, mood=C.UNMET)
        self.assertIn("cannot drink", said)
        self.assertIn("burn", said)
        self.assertIn("read", said)

    def test_the_first_unmet_condition_is_the_one_reported(self):
        verbs.apply_states(self.obj1, add=["burning"], world_root=self.root)
        said = C.unmet([
            {"subject": "direct", "lacks": ["burning"]},
            {"subject": "direct", "is": ["open"]},
        ], self.ctx)
        self.assertIn("already burning", said)

    def test_and_nothing_is_said_when_everything_holds(self):
        self.assertEqual(C.unmet([{"subject": "direct", "lacks": ["x"]}],
                                 self.ctx), "")


@tag("unit")
class ReadingTheOldShapes(SimpleTestCase):
    """
    Both adapters, against every rule in the exported corpus.

    A property over the whole corpus rather than facts about single records,
    so replacing the fixtures later costs nothing here.
    """

    def test_a_role_keyed_requires_becomes_conditions(self):
        got = C.from_requires({"direct": {"has": ["read"],
                                          "lacks": ["burning"]}})
        self.assertIn({"subject": "direct", "affords": ["read"]}, got)
        self.assertIn({"subject": "direct", "lacks": ["burning"]}, got)

    def test_a_trait_requirement_keeps_its_bounds(self):
        got = C.from_requires({"actor": {"trait": {"stamina": {"min": 10}}}})
        self.assertEqual(got, [{"subject": "actor", "trait": "stamina",
                                "min": 10}])

    def test_a_clause_written_as_one_word_is_still_a_list(self):
        """`{"holds": "direct"}` must not become six conditions, one a letter."""
        got = C.from_requires({"actor": {"holds": "direct"}})
        self.assertEqual(got, [{"subject": "actor", "holds": ["direct"]}])

    def test_every_requires_in_the_corpus_converts(self):
        seen = 0
        for label, key, rule in all_rules():
            for condition in C.from_requires(rule.get("requires")):
                self.assertIn("subject", condition, f"{label} {key}")
                name, _value = C.predicate_of(condition)
                self.assertTrue(name, f"{label} {key}: {condition}")
                seen += 1
        self.assertGreater(seen, 200, "the corpus should have conditions in it")

    def test_the_order_of_clauses_is_fixed(self):
        """Two runs must produce the same complaint, so the order cannot be
        dictionary order."""
        requires = {"direct": {"lacks": ["burning"], "is": ["open"],
                               "has": ["read"]}}
        first = C.from_requires(requires)
        self.assertEqual([C.predicate_of(c)[0] for c in first],
                         ["is", "lacks", "affords"])

    def test_goal_shapes_convert(self):
        cases = [
            ({"type": "state", "object": "lantern", "is": ["lit"]},
             [{"subject": {"named": "lantern"}, "is": ["lit"]}]),
            ({"type": "holds", "object": "brass key"},
             [{"subject": "actor", "holds": ["brass key"]}]),
            ({"type": "worn", "object": "grey coat"},
             [{"subject": "actor", "wears": ["grey coat"]}]),
            ({"type": "in_room", "room": "Library"},
             [{"subject": "actor", "in_room": "Library"}]),
            ({"type": "trait", "trait": "stamina", "min": 5},
             [{"subject": "actor", "trait": "stamina", "min": 5}]),
            ({"type": "gone", "object": "rat"},
             [{"subject": {"named": "rat"}, "gone": True}]),
        ]
        for goal, expected in cases:
            self.assertEqual(C.from_goal(goal), expected, goal)

    def test_a_delivery_is_the_recipient_holding_it(self):
        """Which is what `goals` already tests: the thing is inside them."""
        self.assertEqual(
            C.from_goal({"type": "delivered", "object": "letter",
                         "to": "the steward"}),
            [{"subject": {"named": "the steward"}, "holds": ["letter"]}])

    def test_a_goal_naming_a_sort_of_thing_rather_than_a_thing(self):
        self.assertEqual(
            C.from_goal({"type": "exists", "kind": "cake.n.01"}),
            [{"subject": {"of_kind": "cake.n.01"}, "exists": True}])

    def test_an_unknown_goal_type_converts_to_nothing(self):
        self.assertEqual(C.from_goal({"type": "invented"}), [])
        self.assertEqual(C.from_goal("nonsense"), [])


@tag("unit")
class ReadingBackwards(SimpleTestCase):
    """
    The planner's half, and the ground rule it enforces.

    An effect nobody can read backwards is not a cheap effect, it is a hole in
    the planner: every goal that needs it becomes unreachable, and an NPC
    stands still rather than failing.
    """

    def test_setting_a_state_achieves_wanting_it(self):
        self.assertTrue(C.achieves(
            {"type": "set_state", "add": ["open"]},
            {"subject": "direct", "is": ["open"]}))

    def test_but_not_a_different_state(self):
        self.assertFalse(C.achieves(
            {"type": "set_state", "add": ["lit"]},
            {"subject": "direct", "is": ["open"]}))

    def test_removing_a_state_achieves_wanting_it_gone(self):
        self.assertTrue(C.achieves(
            {"type": "set_state", "remove": ["burning"]},
            {"subject": "direct", "lacks": ["burning"]}))

    def test_taking_a_thing_achieves_holding_it(self):
        self.assertTrue(C.achieves(
            {"type": "move_object", "to": "actor"},
            {"subject": "actor", "holds": ["direct"]}))
        self.assertFalse(C.achieves(
            {"type": "move_object", "to": "room"},
            {"subject": "actor", "holds": ["direct"]}))

    def test_putting_a_thing_somewhere_achieves_it_being_there(self):
        self.assertTrue(C.achieves(
            {"type": "move_object", "to": "container", "preposition": "in"},
            {"subject": "direct", "placed": {"in": "chest"}}))
        self.assertFalse(C.achieves(
            {"type": "move_object", "to": "target", "preposition": "on"},
            {"subject": "direct", "placed": {"in": "chest"}}))

    def test_making_and_destroying(self):
        self.assertTrue(C.achieves({"type": "create_object"},
                                   {"subject": "direct", "exists": True}))
        self.assertTrue(C.achieves({"type": "destroy_object"},
                                   {"subject": "direct", "gone": True}))

    def test_a_trait_moves_the_way_the_goal_wants(self):
        rising = {"type": "set_trait", "trait": "stamina", "change": 5}
        falling = {"type": "set_trait", "trait": "stamina", "change": -5}
        wants_more = {"subject": "actor", "trait": "stamina", "min": 10}
        wants_less = {"subject": "actor", "trait": "stamina", "max": 2}
        self.assertTrue(C.achieves(rising, wants_more))
        self.assertFalse(C.achieves(falling, wants_more))
        self.assertTrue(C.achieves(falling, wants_less))

    def test_a_trait_effect_about_something_else_achieves_nothing(self):
        self.assertFalse(C.achieves(
            {"type": "set_trait", "trait": "health", "change": 5},
            {"subject": "actor", "trait": "stamina", "min": 10}))

    def test_every_predicate_has_an_answer_for_every_effect(self):
        """
        The invertibility table. Not that every pair is True -- most are
        not -- but that every pair is *answered*, without raising, so a new
        effect type cannot quietly become unreadable.
        """
        effects = [
            {"type": "set_state", "add": ["x"], "remove": ["y"]},
            {"type": "set_trait", "trait": "stamina", "change": 1},
            {"type": "create_object"}, {"type": "destroy_object"},
            {"type": "move_object", "to": "actor"},
            {"type": "move_object", "to": "target", "preposition": "on"},
            {"type": "modify_object"}, {"type": "modify_room"},
            {"type": "move_actor", "exit": "north"},
            {"type": "an_effect_nobody_has_written_yet"},
        ]
        conditions = [
            {"subject": "direct", "is": ["x"]},
            {"subject": "direct", "lacks": ["y"]},
            {"subject": "direct", "affords": ["read"]},
            {"subject": "direct", "kind": "weapon.n.01"},
            {"subject": "actor", "holds": ["direct"]},
            {"subject": "actor", "wears": ["coat"]},
            {"subject": "direct", "placed": {"on": "table"}},
            {"subject": "actor", "trait": "stamina", "min": 1},
            {"subject": "actor", "in_room": "Library"},
            {"subject": "direct", "exists": True},
            {"subject": "direct", "gone": True},
        ]
        for effect in effects:
            for condition in conditions:
                got = C.achieves(effect, condition)
                self.assertIsInstance(got, bool,
                                      f"{effect['type']} / {condition}")

    def test_nonsense_is_answered_and_not_raised(self):
        self.assertFalse(C.achieves(None, {"subject": "direct", "is": ["x"]}))
        self.assertFalse(C.achieves({"type": "set_state"}, {}))


@tag("unit")
class SayingItWithNoWorld(SimpleTestCase):
    """
    The mood `help` and `rules` need: what a rule requires, not whether you
    satisfy it. There is nothing to resolve a subject against, so every
    sentence is written from the words of the condition.
    """

    def said(self, condition):
        return C.describe(condition)

    def test_a_condition_reads_as_a_plain_statement(self):
        self.assertEqual(
            self.said({"subject": {"enclosure": "spacecraft.n.01"},
                       "is": ["powered"]}),
            "the spacecraft you are in is powered")

    def test_a_lacks_list_means_none_of_them_rather_than_not_all(self):
        """"not damaged and breached" says the wrong thing about the pair."""
        self.assertEqual(
            self.said({"subject": "direct", "lacks": ["damaged", "breached"]}),
            "what you act on is not damaged or breached")

    def test_you_takes_plural_agreement(self):
        """Read aloud, "you has piloting" stops a sentence dead."""
        self.assertEqual(
            self.said({"subject": "actor", "trait": "piloting", "min": 10}),
            "you have piloting of 10 or more")
        self.assertEqual(
            self.said({"subject": "actor", "lacks": ["dead"]}),
            "you are not dead")

    def test_and_everything_else_takes_singular(self):
        self.assertEqual(
            self.said({"subject": "direct", "is": ["open"]}),
            "what you act on is open")

    def test_a_role_named_in_a_clause_is_said_rather_than_spelled(self):
        self.assertEqual(
            self.said({"subject": "actor", "holds": ["direct"]}),
            "you are holding what you act on")

    def test_the_innermost_zone_has_a_name_a_player_would_recognise(self):
        self.assertEqual(
            self.said({"subject": {"zone": True}, "lacks": ["port_closed"]}),
            "the area you are in is not port closed")

    def test_every_predicate_says_something(self):
        conditions = [
            {"subject": "direct", "is": ["open"]},
            {"subject": "direct", "lacks": ["burning"]},
            {"subject": "direct", "affords": ["read"]},
            {"subject": "direct", "kind": "weapon.n.01"},
            {"subject": "actor", "holds": ["direct"]},
            {"subject": "actor", "wears": ["coat"]},
            {"subject": "direct", "placed": {"in": "chest"}},
            {"subject": "actor", "trait": "stamina", "min": 5},
            {"subject": "actor", "trait": "stamina", "max": 5},
            {"subject": "actor", "trait": "stamina"},
            {"subject": "actor", "in_room": "Library"},
            {"subject": {"named": "key"}, "exists": True},
            {"subject": {"named": "rat"}, "gone": True},
        ]
        for condition in conditions:
            said = self.said(condition)
            self.assertTrue(said, condition)
            self.assertNotIn("None", said, condition)
            self.assertNotIn("_", said, condition)

    def test_nonsense_says_nothing_rather_than_raising(self):
        for condition in ({}, None, "nonsense", {"subject": "direct"}):
            self.assertEqual(self.said(condition), "")

    def test_describing_needs_no_actor_and_no_world(self):
        """`rules launch` is typed while standing in a field."""
        self.assertTrue(self.said({"subject": {"named": "brass key"},
                                   "exists": True}))
