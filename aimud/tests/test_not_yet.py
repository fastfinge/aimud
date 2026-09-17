"""
Not yet: waiting for what will come true on its own.

Two things change with nobody acting, and both can be worked out: the clock and
a figure with a rate. A goal that needs one of them is not given up on; the
planner answers "not yet", the character does other things, and looks again
when it is due. See docs/becoming-and-time.md 7.4.
"""

import time
from datetime import datetime
from unittest import mock

from django.test import tag

from tests.base import GameTest
from tests.support import clock as reactor_clock
from world import becoming, clock, planner, standard_rules, traits, verbs
from world import conditions as C
from world import rulebooks as R


def at(*when):
    return datetime(*when).timestamp()


class NotYetTest(GameTest):

    def setUp(self):
        super().setUp()
        becoming.forget_waiting()
        self.root = self.room1
        self.root.db.is_world_root = True
        self.room1.db.world_root = self.root
        self.now = at(2026, 9, 16, 12, 0)
        clock.NOW = lambda: self.now
        self.time = mock.patch("evennia.contrib.rpg.traits.traits.time",
                               side_effect=lambda: self.now)
        self.time.start()
        clock.seed_periods(self.root)
        self.ctx = C.context({}, self.char1, self.root)

    def tearDown(self):
        self.time.stop()
        clock.NOW = None
        becoming.forget_waiting()
        super().tearDown()


@tag("world")
class WhenItWillBeTrue(NotYetTest):

    def test_already_true_is_now(self):
        self.assertEqual(C.eventually({"subject": "world", "is": ["day"]},
                                      self.ctx), 0.0)

    def test_the_clock_comes_round(self):
        self.assertAlmostEqual(
            C.eventually({"subject": "world", "clock": {"from": 20, "to": 5}},
                         self.ctx), 8 * 3600, places=3)

    def test_a_time_of_day_is_worked_out_through_its_definition(self):
        self.assertAlmostEqual(
            C.eventually({"subject": "world", "is": ["night"]}, self.ctx),
            8 * 3600, places=3)
        self.now = at(2026, 9, 16, 22, 0)
        self.assertAlmostEqual(
            C.eventually({"subject": "world", "lacks": ["night"]}, self.ctx),
            7 * 3600, places=3)

    def test_a_figure_on_its_way(self):
        traits.adjust(self.char1, "mana", set_to=5, rate=1,
                      world_root=self.root, announce=False)
        self.assertAlmostEqual(
            C.eventually({"subject": "actor", "trait": "mana", "min": 10},
                         self.ctx), 5.0, places=3)

    def test_but_not_one_going_the_other_way(self):
        traits.adjust(self.char1, "mana", set_to=5, rate=-1,
                      world_root=self.root, announce=False)
        self.assertIsNone(
            C.eventually({"subject": "actor", "trait": "mana", "min": 10},
                         self.ctx))

    def test_a_state_that_is_set_waits_on_somebody(self):
        self.assertIsNone(C.eventually({"subject": "actor", "is": ["lit"]},
                                       self.ctx))

    def test_any_is_its_soonest_and_all_waits_on_every_part(self):
        dusk = {"subject": "world", "clock": {"from": 18, "to": 20}}
        night = {"subject": "world", "clock": {"from": 20, "to": 5}}
        lit = {"subject": "actor", "is": ["lit"]}
        self.assertAlmostEqual(C.eventually({"any": [night, dusk]}, self.ctx),
                               6 * 3600, places=3)
        self.assertAlmostEqual(C.eventually({"all": [night, dusk]}, self.ctx),
                               8 * 3600, places=3)
        self.assertIsNone(C.eventually({"all": [night, lit]}, self.ctx))


@tag("world")
class ThePlannerWaits(NotYetTest):
    loose_objects = 1

    def setUp(self):
        super().setUp()
        standard_rules.seed(self.root)
        self.ship = self.obj1
        self.ship.key = "Kestrel"
        self.ship.db.kinds = ["spacecraft.n.01"]
        R.add(self.root, R.blank(
            action="launch", phase=R.CARRY_OUT,
            scope={"kind": "spacecraft.n.01"}, about="direct",
            name="launching takes the ship up",
            effects=[{"type": "set_state", "role": "direct",
                      "add": ["in_flight"]}]))
        R.add(self.root, R.blank(
            action="launch", phase=R.CHECK,
            scope={"kind": "spacecraft.n.01"}, about="direct",
            name="the port only opens by day",
            conditions=[{"subject": "world", "is": ["day"]}]))
        self.goal = [{"type": "state", "object": "Kestrel",
                      "is": ["in_flight"]}]

    def test_a_step_is_offered_when_nothing_is_waited_for(self):
        move = planner.next_move(self.char1, self.root, self.goal)
        self.assertEqual(move.action, "launch Kestrel")

    def test_a_step_the_clock_forbids_is_not_yet(self):
        self.now = at(2026, 9, 16, 6, 30)
        move = planner.next_move(self.char1, self.root, self.goal)
        self.assertIsNone(move.action)
        self.assertAlmostEqual(move.wait, 30 * 60, places=3)

    def test_a_wait_too_long_is_no_step_at_all(self):
        self.now = at(2026, 9, 16, 22, 0)
        move = planner.next_move(self.char1, self.root, self.goal)
        self.assertIsNone(move.action)
        self.assertIsNone(move.wait)

    def test_a_player_is_told_it_is_not_yet(self):
        self.now = at(2026, 9, 16, 6, 30)
        action, note = planner.advise(self.char1, self.root, self.goal)
        self.assertIsNone(action)
        self.assertIn("Nothing to do yet", note)
        self.assertIn("about 30 minutes", note)

    def test_the_reason_is_waiting_not_missing(self):
        self.now = at(2026, 9, 16, 6, 30)
        reason, _what = planner.blocker(self.char1, self.root, self.goal[0])
        self.assertEqual(reason, planner.WAITING)


@tag("world")
class ACharacterWaits(NotYetTest):

    def setUp(self):
        super().setUp()
        from evennia import create_object

        self.reactor = reactor_clock()
        becoming.CLOCK = self.reactor
        self.awake = mock.patch.object(becoming, "_awake", return_value=True)
        self.awake.start()
        self.npc = create_object("typeclasses.npcs.NPC", key="Mira",
                                 location=self.room1)
        traits.adjust(self.npc, "mana", set_to=5, rate=1,
                      world_root=self.root, announce=False)
        self.npc.db.goal = [{"type": "trait", "trait": "mana", "min": 10}]

    def tearDown(self):
        becoming.disarm(self.npc)
        self.awake.stop()
        becoming.CLOCK = None
        super().tearDown()

    def test_waiting_is_not_being_stuck(self):
        self.assertFalse(self.npc._pursue_goal(self.room1))
        self.assertTrue(self.npc.db.goal_waiting)
        self.assertEqual(self.npc.db.goal_stalls or 0, 0)
        self.assertEqual(self.npc.db.goal, [{"type": "trait", "trait": "mana",
                                             "min": 10}])

    def test_it_is_woken_when_the_wait_is_due(self):
        self.npc._pursue_goal(self.room1)
        self.npc.ndb.idle_probability = 0
        self.now += 6
        self.reactor.advance(6)
        self.assertEqual(self.npc.ndb.idle_probability, 100)

    def test_and_looks_again_rather_than_trusting_the_estimate(self):
        self.npc._pursue_goal(self.room1)
        self.now += 6
        self.npc._pursue_goal(self.room1)
        # Mana has come back, so the goal is reached and nothing is awaited.
        self.assertFalse(self.npc.db.goal)
        self.assertFalse(self.npc.db.goal_waiting)

    def test_waiting_for_the_same_thing_too_often_is_being_stuck(self):
        traits.adjust(self.npc, "mana", rate=0, world_root=self.root,
                      announce=False)
        self.npc.db.goal = [{"type": "trait", "trait": "mana", "min": 10},
                            {"type": "trait", "trait": "focus", "min": 1}]
        traits.adjust(self.npc, "mana", set_to=5, rate=1,
                      world_root=self.root, announce=False)
        for _round in range(planner.MAX_WAIT):
            self.npc.db.goal_waiting = dict(self.npc.db.goal_waiting or {},
                                            until=0)
            self.npc._pursue_goal(self.room1)
            if (self.npc.db.goal_stalls or 0) > 0:
                break
        self.assertGreater(self.npc.db.goal_stalls or 0, 0)

    def test_a_new_goal_is_not_held_up_by_an_old_wait(self):
        self.npc._pursue_goal(self.room1)
        self.npc.db.goal = [{"type": "trait", "trait": "focus", "min": 1}]
        self.assertFalse(self.npc._still_waiting())
        self.assertFalse(self.npc.db.goal_waiting)

    def test_its_prompt_says_what_it_is_waiting_for(self):
        from world.npc_gen import _want_line

        self.npc._pursue_goal(self.room1)
        self.assertIn("cannot be done yet", _want_line(self.npc))
