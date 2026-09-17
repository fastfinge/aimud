"""
Conditions that say "or", and conditions that say the opposite.

See docs/becoming-and-time.md §4. The three tests §4.6 names are the spine of
this module, and the rest is everything that reads a condition learning that a
condition may now be a node:

* every predicate declares an opposite or a refusal;
* a condition and its negation always disagree, including about a subject
  that is not there, a figure somebody does not have, and a list of several
  values -- which is where an opposite that is nearly right goes wrong;
* negating twice gives back something that answers the same.
"""

from django.test import SimpleTestCase, tag

from tests.base import GameTest
from world import conditions as C
from world import goals, planner, relations, rule_gen, rulecheck, traits, verbs


@tag("unit")
class EveryPredicateIsAccountedFor(SimpleTestCase):

    def test_every_predicate_has_an_opposite_or_a_reason_it_has_none(self):
        for name in C._PREDICATES:
            with self.subTest(predicate=name):
                self.assertTrue(name in C.OPPOSITES or name in C.UNNEGATABLE,
                                f"{name} declares neither an opposite nor a "
                                f"refusal")
                self.assertFalse(name in C.OPPOSITES and name in C.UNNEGATABLE)

    def test_opposites_are_opposite_both_ways(self):
        for name, opposite in C.OPPOSITES.items():
            self.assertEqual(C.OPPOSITES[opposite], name)

    def test_every_predicate_can_be_found(self):
        """`predicate_of` looks for them by name, so a new one must be listed."""
        self.assertEqual(set(C.PREDICATES), set(C._PREDICATES))

    def test_the_refused_ones_refuse(self):
        for name in C.UNNEGATABLE:
            self.assertIsNone(C.negate({"subject": "direct", name: "actor"}))


@tag("unit")
class MakingANode(SimpleTestCase):

    key = {"subject": "actor", "holds": ["key"]}
    pick = {"subject": "actor", "holds": ["lockpick"]}
    lit = {"subject": "direct", "is": ["lit"]}

    def test_a_node_of_one_is_that_one(self):
        self.assertEqual(C.normalise({"any": [self.key]}), self.key)

    def test_a_node_inside_its_own_kind_is_part_of_it(self):
        self.assertEqual(
            C.normalise({"any": [self.key, {"any": [self.pick, self.lit]}]}),
            {"any": [self.key, self.pick, self.lit]})

    def test_an_empty_node_is_not_a_condition(self):
        self.assertIsNone(C.normalise({"any": []}))

    def test_a_member_asking_nothing_spoils_the_node(self):
        """Dropping it would make an `any` harder to pass than was written."""
        self.assertIsNone(C.normalise({"any": [self.key, {"subject": "x"}]}))

    def test_nesting_is_capped(self):
        deep = self.key
        for kind in ("any", "all", "any", "all"):
            deep = {kind: [deep, self.lit]}
        self.assertEqual(C.depth_of(deep), 4)
        self.assertIsNone(C.normalise(deep))
        self.assertIsNotNone(C.normalise(deep["all"][0]))

    def test_width_is_capped(self):
        wide = {"any": [{"subject": "actor", "holds": [f"coin{n}"]}
                        for n in range(C.MAX_MEMBERS + 1)]}
        self.assertIsNone(C.normalise(wide))

    def test_an_all_at_the_top_joins_the_list_it_is_in(self):
        kept, refused = C.normalise_all([{"all": [self.key, self.lit]},
                                         self.pick])
        self.assertEqual(kept, [self.key, self.lit, self.pick])
        self.assertEqual(refused, [])

    def test_leaves_know_which_are_only_one_way_through(self):
        found = list(C.leaves({"all": [self.lit,
                                       {"any": [self.key, self.pick]}]}))
        self.assertEqual(found, [(self.lit, False), (self.key, True),
                                 (self.pick, True)])


@tag("unit")
class WorkingOutAMirror(SimpleTestCase):

    def test_a_list_flips_from_all_of_these_to_none_of_these(self):
        self.assertEqual(C.negate({"subject": "direct", "is": ["wet"]}),
                         {"subject": "direct", "lacks": ["wet"]})
        self.assertEqual(
            C.negate({"subject": "direct", "is": ["wet", "cold"]}),
            {"any": [{"subject": "direct", "lacks": ["wet"]},
                     {"subject": "direct", "lacks": ["cold"]}]})

    def test_all_and_any_swap(self):
        self.assertEqual(
            C.negate({"any": [{"subject": "actor", "holds": ["key"]},
                              {"subject": "direct", "lacks": ["locked"]}]}),
            {"all": [{"subject": "actor", "not_holds": ["key"]},
                     {"subject": "direct", "is": ["locked"]}]})

    def test_a_trait_range_negates_to_either_side_of_it(self):
        self.assertEqual(
            C.negate({"subject": "actor", "trait": "hunger", "min": 10,
                      "max": 30}),
            {"any": [{"subject": "actor", "trait": "hunger", "below": 10},
                     {"subject": "actor", "trait": "hunger", "above": 30}]})

    def test_having_some_of_a_figure_has_no_opposite_yet(self):
        self.assertIsNone(C.negate({"subject": "actor", "trait": "hunger"}))

    def test_nobody_and_somebody_are_not_each_others_opposite(self):
        """
        Both say no about a thing that is not there, which the complement
        test below found. The mirror of either says yes.
        """
        self.assertEqual(
            C.negate({"subject": "direct", "owned_by": "nobody"}),
            {"subject": "direct", "not_owned_by": "nobody"})
        self.assertEqual(
            C.negate({"subject": "direct", "owned_by": "actor"}),
            {"subject": "direct", "not_owned_by": "actor"})

    def test_one_refusal_refuses_the_whole(self):
        self.assertIsNone(C.negate(
            {"any": [{"subject": "direct", "is": ["open"]},
                     {"subject": "direct", "affords": ["read"]}]}))

    def test_nonsense_negates_to_nothing(self):
        for nonsense in (None, "nonsense", {}, {"subject": "direct"}):
            self.assertIsNone(C.negate(nonsense))


@tag("unit")
class SayingANodeWithNoWorld(SimpleTestCase):

    def test_the_shared_opening_is_said_once(self):
        self.assertEqual(
            C.describe({"any": [{"subject": "actor", "holds": ["key"]},
                                {"subject": "actor", "holds": ["lockpick"]}]}),
            "you are holding key or lockpick")

    def test_three_read_as_a_list(self):
        self.assertEqual(
            C._joined(["be carrying the key", "be carrying the lockpick",
                       "be carrying the crowbar"], "or"),
            "be carrying the key, the lockpick, or the crowbar")

    def test_the_new_predicates_say_something(self):
        for condition in (
                {"subject": "actor", "not_holds": ["key"]},
                {"subject": "actor", "not_wears": ["coat"]},
                {"subject": "direct", "not_kind": "weapon.n.01"},
                {"subject": "direct", "not_owned_by": "actor"},
                {"subject": "direct", "not_placed": {"in": "chest"}},
                {"subject": "actor", "not_in_room": "Library"},
                {"subject": "here", "not_leads_to": "Library"},
                {"subject": "actor", "trait": "hunger", "below": 10},
                {"subject": "actor", "trait": "hunger", "above": 10}):
            said = C.describe(condition)
            self.assertTrue(said, condition)
            self.assertNotIn("None", said)
            self.assertNotIn("_", said)


@tag("unit")
class ReadingNodesBackwards(SimpleTestCase):

    def test_an_any_is_met_by_meeting_a_branch(self):
        wants = {"any": [{"subject": "direct", "is": ["open"]},
                         {"subject": "direct", "is": ["broken"]}]}
        self.assertTrue(C.achieves({"type": "set_state", "add": ["broken"]},
                                   wants))
        self.assertFalse(C.achieves({"type": "set_state", "add": ["lit"]},
                                    wants))

    def test_letting_go_achieves_not_holding(self):
        wants = {"subject": "actor", "not_holds": ["direct"]}
        self.assertTrue(C.achieves({"type": "move_object", "to": "room"},
                                   wants))
        self.assertTrue(C.achieves({"type": "destroy_object"}, wants))
        self.assertFalse(C.achieves({"type": "move_object", "to": "actor"},
                                    wants))

    def test_exclusive_bounds_read_like_inclusive_ones(self):
        falling = {"type": "set_trait", "trait": "hunger", "change": -5}
        rising = {"type": "set_trait", "trait": "hunger", "change": 5}
        below = {"subject": "actor", "trait": "hunger", "below": 10}
        self.assertTrue(C.achieves(falling, below))
        self.assertFalse(C.achieves(rising, below))
        self.assertTrue(C.achieves(
            {"type": "set_trait", "trait": "hunger", "set_to": 9}, below))
        self.assertFalse(C.achieves(
            {"type": "set_trait", "trait": "hunger", "set_to": 10}, below))

    def test_giving_it_away_achieves_it_not_being_yours(self):
        wants = {"subject": "direct", "not_owned_by": "actor"}
        self.assertTrue(C.achieves({"type": "set_owner", "to": "target"},
                                   wants))
        self.assertFalse(C.achieves({"type": "set_owner", "to": "actor"},
                                    wants))


@tag("unit")
class TheGoalShape(SimpleTestCase):

    def test_an_any_becomes_a_goal_and_back(self):
        condition = {"any": [{"subject": "actor", "holds": ["key"]},
                             {"subject": "actor", "not_in_room": "Cellar"}]}
        goal = C.as_goal(condition, {}, None)
        self.assertEqual(goal, {"type": "any", "of": [
            {"type": "holds", "object": "key"},
            {"type": "not_in_room", "room": "Cellar"}]})
        self.assertEqual(C.from_goal(goal), [condition])

    def test_a_branch_with_no_goal_form_is_left_out(self):
        condition = {"any": [{"subject": "actor", "holds": ["key"]},
                             {"subject": "world", "is": ["night"]}]}
        self.assertEqual(C.as_goal(condition, {}, None),
                         {"type": "holds", "object": "key"})

    def test_a_goal_keeps_an_any_through_sanitising(self):
        kept = goals.sanitise([{"type": "any", "of": [
            {"type": "holds", "object": "key"},
            {"type": "not_holds", "object": "torch"}]}])
        self.assertEqual(kept, [{"type": "any", "of": [
            {"type": "holds", "object": "key"},
            {"type": "not_holds", "object": "torch"}]}])

    def test_but_not_one_with_a_branch_nobody_can_test(self):
        self.assertEqual(goals.sanitise([{"type": "any", "of": [
            {"type": "holds", "object": "key"},
            {"type": "telepathy"}]}]), [])


@tag("unit")
class WritingThemDown(SimpleTestCase):

    def setUp(self):
        self.offered = [("world", "everywhere", {"world": True})]

    def keep(self, *rules):
        return rule_gen.validate({"rules": list(rules)}, self.offered, "open")

    def test_an_any_is_kept(self):
        kept, complaints = self.keep(
            {"phase": "check", "scope": "world", "name": "a key or a pick",
             "conditions": [{"any": [
                 {"subject": "actor", "holds": ["key"]},
                 {"subject": "actor", "holds": ["lockpick"]}]}]})
        self.assertEqual(complaints, [])
        self.assertIn("any", kept[0]["conditions"][0])

    def test_a_check_rule_packed_into_one_all_is_refused(self):
        kept, complaints = self.keep(
            {"phase": "check", "scope": "world", "name": "both",
             "conditions": [{"all": [
                 {"subject": "actor", "holds": ["key"]},
                 {"subject": "direct", "lacks": ["rusted"]}]}]})
        self.assertEqual(kept, [])
        self.assertTrue(any("packed" in c for c in complaints))

    def test_an_empty_any_is_refused(self):
        kept, complaints = self.keep(
            {"phase": "check", "scope": "world", "name": "nothing",
             "conditions": [{"any": []}]})
        self.assertEqual(kept, [])
        self.assertTrue(complaints)

    def test_a_dead_branch_does_not_kill_the_rule(self):
        """Only when every branch demands what `open` produces is it dead."""
        produced = {"open"}
        one_way = {"any": [{"subject": "direct", "is": ["open"]},
                           {"subject": "actor", "holds": ["key"]}]}
        every_way = {"any": [{"subject": "direct", "is": ["open"]},
                             {"subject": "direct", "is": ["open"]}]}
        self.assertEqual(rulecheck.dead_states(one_way, produced), set())
        self.assertEqual(rulecheck.dead_states(every_way, produced), {"open"})
        self.assertEqual(
            rulecheck.dead_states({"all": [one_way,
                                           {"subject": "direct",
                                            "is": ["open"]}]}, produced),
            {"open"})


@tag("world")
class AConditionAndItsMirrorAlwaysDisagree(GameTest):
    """
    The complement test. Every condition here is asked of a world that makes
    it true and a world that makes it false, and at the edges where a nearly
    right opposite goes wrong: nobody there, no such figure, several values.
    """

    loose_objects = 2
    second_room = True

    def setUp(self):
        super().setUp()
        self.root = self.room1
        self.root.db.is_world_root = True
        self.room1.db.world_root = self.root
        self.room2.db.world_root = self.root
        self.room2.db.room_title = "Library"
        self.obj1.db.kinds = ["sword.n.01"]
        traits.adjust(self.char1, "stamina", set_to=10, world_root=self.root,
                      announce=False)

    CONDITIONS = [
        {"subject": "direct", "is": ["open"]},
        {"subject": "direct", "is": ["open", "lit"]},
        {"subject": "direct", "lacks": ["open"]},
        {"subject": "direct", "lacks": ["open", "lit"]},
        {"subject": "actor", "holds": ["direct"]},
        {"subject": "target", "holds": ["direct"]},
        {"subject": "actor", "not_holds": ["direct"]},
        {"subject": "actor", "wears": ["coat"]},
        {"subject": "direct", "kind": "weapon.n.01"},
        {"subject": "direct", "not_kind": "food.n.01"},
        {"subject": "direct", "owned_by": "actor"},
        {"subject": "direct", "owned_by": "nobody"},
        {"subject": "direct", "owned_by": "somebody"},
        {"subject": "direct", "placed": {"on": "target"}},
        {"subject": "actor", "trait": "stamina", "min": 5},
        {"subject": "actor", "trait": "stamina", "max": 5},
        {"subject": "actor", "trait": "stamina", "below": 10},
        {"subject": "actor", "trait": "stamina", "above": 10},
        {"subject": "actor", "trait": "stamina", "min": 5, "max": 20},
        {"subject": "actor", "trait": "stamina", "min": 5, "below": 10},
        {"subject": "actor", "trait": "luck", "min": 1},
        {"subject": "actor", "trait": "luck", "below": 1},
        {"subject": "direct", "trait": "luck", "max": 3},
        {"subject": "actor", "in_room": "Room"},
        {"subject": "actor", "not_in_room": "Library"},
        {"subject": "direct", "exists": True},
        {"subject": "direct", "gone": True},
        {"subject": "direct", "unbound": True},
        {"subject": "here", "leads_to": "Library"},
        {"subject": "here", "leads_to": "Nowhere"},
        {"subject": "world", "clock": {"from": 20, "to": 6}},
        {"subject": "world", "clock": {"from": 6, "to": 20}},
        {"any": [{"subject": "direct", "is": ["open"]},
                 {"subject": "actor", "holds": ["direct"]}]},
        {"all": [{"subject": "direct", "lacks": ["open"]},
                 {"subject": "actor", "trait": "stamina", "min": 5}]},
    ]

    def worlds(self):
        """The same condition, asked of several different states of things."""
        yield "as it starts", C.context({"direct": self.obj1,
                                         "target": self.obj2}, self.char1,
                                        self.root)
        yield "with nothing named", C.context({}, self.char1, self.root)
        verbs.apply_states(self.obj1, add=["open"], world_root=self.root)
        self.obj1.move_to(self.char1, quiet=True)
        yield "open and held", C.context({"direct": self.obj1}, self.char1,
                                         self.root)
        verbs.apply_states(self.obj1, add=["lit"], world_root=self.root)
        self.obj1.move_to(self.room1, quiet=True)
        relations.place(self.obj1, self.obj2, "on")
        yield "open, lit and on the other", C.context(
            {"direct": self.obj1, "target": self.obj2}, self.char1, self.root)

    def test_they_disagree_everywhere(self):
        for where, ctx in self.worlds():
            for condition in self.CONDITIONS:
                mirror = C.negate(condition)
                with self.subTest(where=where, condition=condition):
                    self.assertIsNotNone(mirror)
                    self.assertNotEqual(C.evaluate(condition, ctx),
                                        C.evaluate(mirror, ctx),
                                        f"{condition} and {mirror}")

    def test_negating_twice_answers_the_same(self):
        for where, ctx in self.worlds():
            for condition in self.CONDITIONS:
                with self.subTest(where=where, condition=condition):
                    self.assertEqual(
                        C.evaluate(C.negate(C.negate(condition)), ctx),
                        C.evaluate(condition, ctx))


@tag("world")
class SayingANodeInAWorld(GameTest):
    loose_objects = 1

    def setUp(self):
        super().setUp()
        self.root = self.room1
        self.room1.db.world_root = self.root
        self.ctx = C.context({}, self.char1, self.root)
        self.either = {"any": [{"subject": "actor", "holds": ["key"]},
                               {"subject": "actor", "holds": ["lockpick"]}]}

    def test_a_failed_any_is_one_complaint(self):
        self.assertEqual(C.unmet([self.either], self.ctx),
                         "You need to be carrying the key or the lockpick.")

    def test_and_passes_when_one_branch_does(self):
        self.obj1.key = "lockpick"
        self.obj1.move_to(self.char1, quiet=True)
        self.assertTrue(C.evaluate(self.either, self.ctx))
        self.assertEqual(C.unmet([self.either], self.ctx), "")

    def test_a_rule_that_takes_either_is_gathered_either_way(self):
        from world import rulebooks

        rulebooks.add(self.root, rulebooks.blank(
            action="open", phase=rulebooks.AFTER, name="either will do",
            when=[self.either],
            effects=[{"type": "narrate"}]))
        self.assertEqual(rulebooks.gather(self.root, "open", {}, self.char1,
                                          phase=rulebooks.AFTER), [])
        self.obj1.key = "key"
        self.obj1.move_to(self.char1, quiet=True)
        found = rulebooks.gather(self.root, "open", {}, self.char1,
                                 phase=rulebooks.AFTER)
        self.assertEqual([r["name"] for r in found], ["either will do"])

    def test_the_listing_prints_a_node_as_a_group(self):
        from commands.rules_subject import condition_lines

        lines = condition_lines(self.either, "  ")
        self.assertEqual(lines[0], "  any one of these:")
        self.assertEqual(len(lines), 3)
        self.assertTrue(lines[1].startswith("    "))


@tag("world")
class PlanningTowardsAnOpposite(GameTest):
    loose_objects = 1
    second_room = True

    def setUp(self):
        super().setUp()
        self.root = self.room1
        self.room1.db.world_root = self.root
        self.room2.db.world_root = self.root
        self.obj1.key = "torch"

    def test_not_holding_something_is_putting_it_down(self):
        self.obj1.move_to(self.char1, quiet=True)
        action, _key, _condition = planner.plan_for(
            self.char1, self.root, [{"type": "not_holds", "object": "torch"}])
        self.assertEqual(action, "drop torch")

    def test_not_being_somewhere_is_leaving_by_any_way_out(self):
        action, _key, _condition = planner.plan_for(
            self.char1, self.root,
            [{"type": "not_in_room", "room": self.room1.key}])
        self.assertEqual(action, self.exit.key)

    def test_an_any_takes_the_branch_that_offers_a_step(self):
        self.obj1.move_to(self.char1, quiet=True)
        action, _key, _condition = planner.plan_for(
            self.char1, self.root, [{"type": "any", "of": [
                {"type": "holds", "object": "philosopher's stone"},
                {"type": "not_holds", "object": "torch"}]}])
        self.assertEqual(action, "drop torch")

    def test_a_goal_with_an_any_is_tested_as_one(self):
        goal = [{"type": "any", "of": [
            {"type": "holds", "object": "torch"},
            {"type": "in_room", "room": "Nowhere at all"}]}]
        self.assertFalse(goals.satisfied(goal, self.char1, self.root))
        self.obj1.move_to(self.char1, quiet=True)
        self.assertTrue(goals.satisfied(goal, self.char1, self.root))
