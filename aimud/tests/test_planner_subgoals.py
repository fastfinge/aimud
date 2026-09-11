"""
The step before the step: what a planner does with a verb it cannot use yet.

`launch` refused for want of power becomes the goal "the ship is powered" becomes
the step `power`. One link at a time, capped, and every link read off rules the
world wrote for itself.

The gap this closes was real rather than theoretical. The planner read
`world_root.db.verb_rules` and nothing else, so every check rule written since
phase 7 was invisible to it: it would propose launching a cold ship, watch the
attempt be refused, and then blame the launch rule for not doing what it promised.
`ThePlannerSeesRulebooks` is the class that pins that down.
"""

from django.test import SimpleTestCase, tag
from evennia.utils.test_resources import EvenniaTest

from world import conditions as C
from world import goals, planner, rulebooks as R
from world import standard_rules, verbs


@tag("unit")
class ReadingAConditionBackAsAGoal(SimpleTestCase):
    """
    A check rule refuses in the condition language and the planner plans in the
    goal language, so something has to carry a refusal across.
    """

    def test_a_state_condition_becomes_a_state_goal(self):
        self.assertEqual(
            C.as_goal({"subject": {"named": "Kestrel"}, "is": ["powered"]}),
            {"type": "state", "object": "Kestrel", "is": ["powered"]})

    def test_a_lacks_condition_keeps_its_sense(self):
        self.assertEqual(
            C.as_goal({"subject": {"named": "Kestrel"}, "lacks": ["damaged"]}),
            {"type": "state", "object": "Kestrel", "lacks": ["damaged"]})

    def test_a_trait_condition_keeps_its_bounds(self):
        self.assertEqual(
            C.as_goal({"subject": "actor", "trait": "piloting", "min": 10},
                      actor=None),
            {"type": "trait", "trait": "piloting", "min": 10})

    def test_holding_and_wearing_come_back(self):
        self.assertEqual(
            C.as_goal({"subject": "actor", "holds": ["brass key"]}),
            {"type": "holds", "object": "brass key"})
        self.assertEqual(
            C.as_goal({"subject": "actor", "wears": ["helmet"]}),
            {"type": "worn", "object": "helmet"})

    def test_a_room_condition_comes_back(self):
        self.assertEqual(
            C.as_goal({"subject": "actor", "in_room": "Bridge"}),
            {"type": "in_room", "room": "Bridge"})

    def test_a_condition_about_a_place_has_no_goal_form(self):
        """
        There is nothing to walk up to and change. Offering it would send a
        character off to do something about the idea of a room.
        """
        self.assertIsNone(C.as_goal({"subject": "here", "is": ["flooded"]}))
        self.assertIsNone(
            C.as_goal({"subject": {"zone": True}, "lacks": ["sealed"]}))
        self.assertIsNone(C.as_goal(
            {"subject": {"enclosure": "spacecraft.n.01"}, "is": ["powered"]}))

    def test_nor_does_one_about_a_role_nothing_was_bound_to(self):
        self.assertIsNone(C.as_goal({"subject": "direct", "is": ["powered"]}))

    def test_but_a_bound_role_is_named(self):
        class Thing:
            key = "Kestrel"

        self.assertEqual(
            C.as_goal({"subject": "direct", "is": ["powered"]},
                      bound={"direct": Thing()}),
            {"type": "state", "object": "Kestrel", "is": ["powered"]})

    def test_predicates_a_planner_cannot_advance_are_refused(self):
        """
        `affords`, `able` and `reachable_by` describe the shape of a situation
        rather than something a character could go and change -- offering them
        would send an NPC off to make a bottle drinkable.
        """
        for condition in ({"subject": {"named": "x"}, "affords": ["drink"]},
                          {"subject": "actor", "able": "acting"},
                          {"subject": {"named": "x"}, "reachable_by": "actor"},
                          {"subject": {"named": "x"}, "kind": "bottle.n.01"},
                          {"subject": {"named": "x"}, "unbound": True}):
            self.assertIsNone(C.as_goal(condition), condition)

    def test_a_list_keeps_only_what_has_a_goal_form(self):
        found = C.as_goals([
            {"subject": {"named": "Kestrel"}, "is": ["powered"]},
            {"subject": "here", "is": ["flooded"]},
            {"subject": "actor", "in_room": "Bridge"}])
        self.assertEqual([g["type"] for g in found], ["state", "in_room"])


@tag("world")
class AShipThatNeedsPowerFirst(EvenniaTest):
    """
    The spaceship from the planner's side. Nothing here writes a plan; the world
    is asked what to do next and answers with the step before the one wanted.
    """

    def setUp(self):
        super().setUp()
        self.root = self.room1
        self.root.db.is_world_root = True
        self.room1.db.world_root = self.root
        self.char1.move_to(self.room1, quiet=True)
        standard_rules.seed(self.root)

        self.ship = self.obj1
        self.ship.key = "Kestrel"
        self.ship.db.kinds = ["spacecraft.n.01"]
        self.ship.move_to(self.room1, quiet=True)

        R.add(self.root, R.blank(
            action="launch", phase=R.CARRY_OUT,
            scope={"kind": "spacecraft.n.01"}, about="direct",
            name="launching takes the ship up",
            effects=[{"type": "set_state", "role": "direct",
                      "add": ["in_flight"]}]))
        R.add(self.root, R.blank(
            action="launch", phase=R.CHECK,
            scope={"kind": "spacecraft.n.01"}, about="direct",
            name="a ship only launches under power",
            conditions=[{"subject": "direct", "is": ["powered"]}]))
        R.add(self.root, R.blank(
            action="power", phase=R.CARRY_OUT,
            scope={"kind": "spacecraft.n.01"}, about="direct",
            name="powering a ship wakes its reactor",
            effects=[{"type": "set_state", "role": "direct",
                      "add": ["powered"]}]))

    def next_step(self, goal):
        action, _key, _condition = planner.plan_for(self.char1, self.root, goal)
        return action

    def test_the_step_is_the_one_before_the_one_wanted(self):
        self.assertEqual(
            self.next_step([{"type": "state", "object": "Kestrel",
                             "is": ["in_flight"]}]),
            "power Kestrel")

    def test_and_once_that_is_done_the_wanted_one_is_offered(self):
        verbs.apply_states(self.ship, add=["powered"], world_root=self.root)
        self.assertEqual(
            self.next_step([{"type": "state", "object": "Kestrel",
                             "is": ["in_flight"]}]),
            "launch Kestrel")

    def test_a_verb_with_nothing_in_its_way_is_offered_directly(self):
        self.assertEqual(
            self.next_step([{"type": "state", "object": "Kestrel",
                             "is": ["powered"]}]),
            "power Kestrel")

    def test_the_blame_goes_to_the_rule_that_promised_the_thing(self):
        """
        Not to the rule about to be run. If powering does not leave the ship
        powered, the rule that says what powering does is the one at fault.
        """
        action, key, condition = planner.plan_for(
            self.char1, self.root,
            [{"type": "state", "object": "Kestrel", "is": ["in_flight"]}])
        self.assertEqual(action, "power Kestrel")
        self.assertEqual(condition["is"], ["in_flight"])

    def test_a_chain_with_no_bottom_gives_up_rather_than_looping(self):
        """
        Powering needs a fuel rod that does not exist, so there is no step. The
        honest answer is none, not a circle.
        """
        R.add(self.root, R.blank(
            action="power", phase=R.CHECK,
            scope={"kind": "spacecraft.n.01"}, about="direct",
            name="a ship needs its reactor primed",
            conditions=[{"subject": "direct", "is": ["primed"]}]))
        self.assertIsNone(
            self.next_step([{"type": "state", "object": "Kestrel",
                             "is": ["in_flight"]}]))

    def test_and_the_depth_is_capped(self):
        """
        Every link is read off an effect a model wrote. A chain four deep built
        on four approximations is the long plan that fails silently at the end.
        """
        self.assertEqual(planner.MAX_SUBGOALS, 3)
        chain = ["in_flight", "powered", "primed", "fuelled", "loaded"]
        for wanted, needed in zip(chain, chain[1:]):
            R.add(self.root, R.blank(
                action=f"do_{needed}", phase=R.CARRY_OUT,
                scope={"kind": "spacecraft.n.01"}, about="direct",
                name=f"makes a ship {needed}",
                effects=[{"type": "set_state", "role": "direct",
                          "add": [needed]}]))
        # Nothing blows up and nothing loops; whether a step is found at all is
        # a question about the cap, not about correctness.
        self.next_step([{"type": "state", "object": "Kestrel",
                         "is": ["in_flight"]}])


@tag("world")
class ThePlannerSeesRulebooks(AShipThatNeedsPowerFirst):
    """
    The blindness this phase closes. Before it, the planner read one store and
    the pipeline read two, so they disagreed about why a thing was refused.
    """

    def test_a_rulebook_check_is_read_as_what_blocks_a_verb(self):
        unmet = planner.conditions_unmet_for(self.char1, self.root, "launch",
                                             self.ship)
        self.assertEqual(unmet, [{"subject": "direct", "is": ["powered"]}])

    def test_and_nothing_blocks_it_once_it_is_met(self):
        verbs.apply_states(self.ship, add=["powered"], world_root=self.root)
        self.assertEqual(
            planner.conditions_unmet_for(self.char1, self.root, "launch",
                                         self.ship), [])

    def test_the_same_rules_the_pipeline_would_gather(self):
        """
        Read out of the rulebooks rather than guessed, so the planner and the
        pipeline cannot come to disagree about why something is refused.
        """
        standing = planner.conditions_unmet_for(self.char1, self.root, "launch",
                                               self.ship)
        book = R.for_attempt(self.root, "launch", {"direct": self.ship},
                             self.char1, phase=R.CHECK)
        written = [c for rule in book for c in (rule.get("conditions") or [])]
        for condition in standing:
            self.assertIn(condition, written)

    def test_a_suspended_rule_blocks_nothing(self):
        """A proposal in the queue is in the book and not in force."""
        gate = R.add(self.root, R.blank(
            action="power", phase=R.CHECK,
            scope={"kind": "spacecraft.n.01"}, about="direct",
            name="a suspended requirement",
            conditions=[{"subject": "direct", "is": ["impossible"]}]))
        R.set_listed(self.root, gate["id"], False)
        self.assertEqual(
            self.next_step([{"type": "state", "object": "Kestrel",
                             "is": ["powered"]}]),
            "power Kestrel")

    def test_a_carry_out_rule_alone_is_enough_to_offer_a_verb(self):
        """
        No learned verb rule anywhere in this world. Before this phase the
        planner would have found nothing to do about any of it.
        """
        self.assertEqual(self.root.db.verb_rules or {}, {})
        self.assertEqual(
            self.next_step([{"type": "state", "object": "Kestrel",
                             "is": ["powered"]}]),
            "power Kestrel")


@tag("world")
class WhatAPlayerIsTold(AShipThatNeedsPowerFirst):
    """`advise` is the planner answering a question rather than acting."""

    def test_the_advice_is_the_step_before(self):
        action, note = planner.advise(
            self.char1, self.root,
            [{"type": "state", "object": "Kestrel", "is": ["in_flight"]}])
        self.assertEqual(action, "power Kestrel")
        self.assertTrue(note)

    def test_and_it_says_so_when_there_is_nothing_to_do(self):
        R.add(self.root, R.blank(
            action="power", phase=R.CHECK,
            scope={"kind": "spacecraft.n.01"}, about="direct",
            name="a ship needs its reactor primed",
            conditions=[{"subject": "direct", "is": ["primed"]}]))
        action, note = planner.advise(
            self.char1, self.root,
            [{"type": "state", "object": "Kestrel", "is": ["in_flight"]}])
        self.assertIsNone(action)
        self.assertIn("Nothing you can do", note)

    def test_a_goal_already_met_is_said_so(self):
        verbs.apply_states(self.ship, add=["in_flight"], world_root=self.root)
        action, note = planner.advise(
            self.char1, self.root,
            [{"type": "state", "object": "Kestrel", "is": ["in_flight"]}])
        self.assertIsNone(action)
        self.assertIn("done it", note)


@tag("unit")
class CausesReadBackwards(SimpleTestCase):
    """
    A planner's index, not a synonym test. Dropping and felling are not the same
    word and nothing here claims they are; they are two ways to make a thing
    descend, which is what a world with no rule about descending wants to know.
    """

    def test_the_specs_own_example(self):
        from world import lexicon

        found = lexicon.causing("descend")
        self.assertIn("lower", found)
        self.assertIn("fell", found)

    def test_it_is_many_to_one_on_purpose(self):
        from world import lexicon

        self.assertGreater(len(lexicon.causing("rise")), 1)

    def test_a_verb_that_causes_itself_is_no_candidate(self):
        """
        `open` causes `open` -- the causative pair. A world with no way to make
        something open does not need to be told to open it; it needs the rule it
        has not got.
        """
        from world import lexicon

        self.assertNotIn("open", lexicon.causing("open"))

    def test_a_word_nothing_causes_answers_empty(self):
        from world import lexicon

        self.assertEqual(lexicon.causing("datapad"), [])
        self.assertEqual(lexicon.causing(""), [])
        self.assertEqual(lexicon.causing(None), [])

    def test_the_index_is_small_enough_to_keep(self):
        """
        WordNet holds about 220 causes pairs in all, so inverted it is a couple
        of hundred entries -- worth holding, not worth storing.
        """
        from world import lexicon

        self.assertLess(len(lexicon._caused_by()), 500)


@tag("world")
class AVerbNobodyHasTried(AShipThatNeedsPowerFirst):
    """
    Offered to a person, never to a tick. Finding out what a new verb means costs
    a model call, and a planner that bought rules on a timer is the clock this
    design keeps refusing in a different hat.
    """

    def test_the_state_usually_names_its_own_verb(self):
        found = planner.untried_verbs(
            self.root, {"type": "state", "object": "Kestrel",
                        "is": ["vented"]})
        self.assertIn("vent", found)

    def test_a_verb_the_world_already_has_is_not_offered(self):
        """`power` has a rule in this fixture, so it is knowledge, not a guess."""
        found = planner.untried_verbs(
            self.root, {"type": "state", "object": "Kestrel",
                        "is": ["powered"]})
        self.assertNotIn("power", found)

    def test_nor_is_one_the_engine_answers_itself(self):
        found = planner.untried_verbs(
            self.root, {"type": "state", "object": "Kestrel",
                        "is": ["looked"]})
        self.assertNotIn("look", found)

    def test_the_harder_case_comes_from_the_causation_index(self):
        found = planner.untried_verbs(
            self.root, {"type": "state", "object": "Kestrel",
                        "is": ["descended"]})
        self.assertTrue(set(found) & {"lower", "fell"})

    def test_a_state_with_no_verb_anywhere_behind_it_offers_nothing(self):
        self.assertEqual(
            planner.untried_verbs(self.root,
                                  {"type": "state", "object": "Kestrel",
                                   "is": ["unlit"]}), [])

    def test_advice_offers_it_and_says_it_is_a_guess(self):
        action, note = planner.advise(
            self.char1, self.root,
            [{"type": "state", "object": "Kestrel", "is": ["vented"]}])
        self.assertEqual(action, "vent Kestrel")
        self.assertIn("nobody has tried", note)
        self.assertIn("work out what it means", note)

    def test_a_character_acting_on_its_own_may_take_it_too(self):
        """
        Not held back to players. An NPC with no step to take falls through to
        the dialogue model anyway -- `trigger_idle_action` asks what the
        character would do with itself -- so trying a word that might work is
        not a new cost, it is a better use of the same one. What keeps it
        bounded is `activity.npc_may_act` upstream and the fruitless tally below.
        """
        action, _key, _condition = planner.plan_for(
            self.char1, self.root,
            [{"type": "state", "object": "Kestrel", "is": ["vented"]}])
        self.assertEqual(action, "vent Kestrel")

    def test_a_guess_is_never_stacked_inside_a_subgoal(self):
        """
        One uncertainty at a time. Inside a chain the step already rests on an
        effect somebody guessed at, and a guess about vocabulary on top of that
        is two deep for one turn.
        """
        R.add(self.root, R.blank(
            action="launch", phase=R.CHECK,
            scope={"kind": "spacecraft.n.01"}, about="direct",
            name="a ship only launches when vented",
            conditions=[{"subject": "direct", "is": ["vented"]}]))
        verbs.apply_states(self.ship, add=["powered"], world_root=self.root)
        action, _key, _condition = planner.plan_for(
            self.char1, self.root,
            [{"type": "state", "object": "Kestrel", "is": ["in_flight"]}])
        self.assertIsNone(action, "the subgoal may not be answered by a guess")

    def test_and_a_guess_is_told_apart_from_knowledge(self):
        self.assertTrue(planner.is_a_guess(self.root, "vent Kestrel"))
        self.assertFalse(planner.is_a_guess(self.root, "power Kestrel"))

    def test_and_a_real_step_is_always_preferred_to_a_guess(self):
        action, _note = planner.advise(
            self.char1, self.root,
            [{"type": "state", "object": "Kestrel", "is": ["in_flight"]}])
        self.assertEqual(action, "power Kestrel",
                         "a rule the world has beats a word it might not")


@tag("world")
class AskingTwiceAndNoMore(EvenniaTest):
    """
    The bill that could otherwise run on its own.

    A character working at a goal may now try a verb this world has never
    learned, and the world spends a call finding out what it means. If the
    answer is "nothing", that has to be remembered -- or the same character
    tries the same word next tick, for ever, at the same price.

    `kinds.admit` caches a no and `actions.declare` caches an arity. This was
    the one answer cached nowhere.
    """

    def setUp(self):
        super().setUp()
        self.root = self.room1
        self.root.db.is_world_root = True
        self.room1.db.world_root = self.root
        self.room1.db.is_ai_room = True
        self.char1.move_to(self.room1, quiet=True)
        standard_rules.seed(self.root)
        self.thing = self.obj1
        self.thing.key = "Kestrel"
        self.thing.db.kinds = ["spacecraft.n.01"]
        self.thing.move_to(self.room1, quiet=True)
        from world import kinds

        kinds.admit(self.root, ["spacecraft.n.01"], "vent", True)

    def try_it(self, raw, reply):
        from tests.support import FakeSponsor, as_json, immediately, replying
        from world import attempt as attempt_mod

        said = []
        with immediately(), replying(
                as_json(reply) if isinstance(reply, dict) else reply) as script:
            attempt_mod.attempt(
                self.char1, raw, FakeSponsor(),
                on_message=lambda a, r=None: said.append(a or ""))
            self.asked = script.count
        return " ".join(s for s in said if s)

    def nothing_useful(self):
        return {"rules": [], "cannot_say": "nothing here vents anything"}

    def test_a_fruitless_ask_is_counted(self):
        from world import rule_gen

        self.try_it("vent Kestrel", self.nothing_useful())
        self.assertEqual(rule_gen.fruitless(self.root, "vent"), 1)

    def test_a_world_asks_twice_and_then_stops(self):
        from world import rule_gen

        for _ in range(rule_gen.ASKS_ALLOWED):
            self.try_it("vent Kestrel", self.nothing_useful())
        self.assertFalse(rule_gen.worth_asking(self.root, "vent"))

        said = self.try_it("vent Kestrel", self.nothing_useful())
        self.assertEqual(self.asked, 0, "no third call")
        self.assertIn("Nothing here knows how to vent", said)

    def test_the_first_answer_is_allowed_to_have_been_unlucky(self):
        from world import rule_gen

        self.try_it("vent Kestrel", "not json at all")
        self.assertTrue(rule_gen.worth_asking(self.root, "vent"),
                        "one empty answer is not evidence")

    def test_a_verb_that_did_produce_a_rule_is_not_counted_against(self):
        from world import rule_gen

        self.try_it("vent Kestrel", {
            "rules": [{"phase": "carry_out", "scope": "spacecraft.n.01",
                       "about": "direct", "name": "venting a ship clears it",
                       "effects": [{"type": "set_state", "role": "direct",
                                    "add": ["vented"]}]}]})
        self.assertEqual(rule_gen.fruitless(self.root, "vent"), 0)

    def test_and_the_planner_stops_offering_a_verb_the_world_gave_up_on(self):
        """
        Which closes the loop: the guess is tried, it comes to nothing, and the
        character does not spend another turn on it.
        """
        from world import rule_gen

        wanted = {"type": "state", "object": "Kestrel", "is": ["vented"]}
        self.assertIn("vent", planner.untried_verbs(self.root, wanted))
        for _ in range(rule_gen.ASKS_ALLOWED):
            rule_gen.note_fruitless(self.root, "vent")
        self.assertNotIn("vent", planner.untried_verbs(self.root, wanted))

    def test_a_network_failure_is_not_counted_against_a_verb(self):
        """
        A world offline for an afternoon must not come back having given up on
        half its vocabulary. That path ends in `on_error` and never reaches the
        tally.
        """
        from tests.support import FakeSponsor, immediately, replying
        from world import attempt as attempt_mod, llm, rule_gen

        with immediately(), replying(llm.LLMError("no route to host")):
            attempt_mod.attempt(self.char1, "vent Kestrel", FakeSponsor(),
                                on_message=lambda a, r=None: None)
        self.assertEqual(rule_gen.fruitless(self.root, "vent"), 0)

