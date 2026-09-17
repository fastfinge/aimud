"""
Figures that cross a threshold with nobody doing anything.

A figure with a rate moves in a straight line, so the moment it will reach a
threshold a becomes rule cares about can be worked out, and one timer per
character fires exactly then -- while the world is awake, and never as a poll.
See docs/becoming-and-time.md §7.
"""

import time
from unittest import mock

from django.test import tag

from tests.base import GameTest
from tests.support import clock
from world import becoming, traits, verbs
from world import rulebooks as R


class CrossingTest(GameTest):

    def setUp(self):
        super().setUp()
        becoming.forget_waiting()
        self.clock = clock()
        becoming.CLOCK = self.clock
        self.root = self.room1
        self.root.db.is_world_root = True
        self.room1.db.world_root = self.root
        self.awake = mock.patch.object(becoming, "_awake", return_value=True)
        self.awake.start()
        self.now = time.time()
        self.time = mock.patch("evennia.contrib.rpg.traits.traits.time",
                               side_effect=lambda: self.now)
        self.time.start()

    def tearDown(self):
        self.time.stop()
        self.awake.stop()
        becoming.disarm(self.char1)
        becoming.CLOCK = None
        becoming.forget_waiting()
        super().tearDown()

    def starving_kills(self):
        verbs.register_state(self.root, "starving", when=[
            {"subject": "direct", "trait": "hunger", "max": 10}])
        R.add(self.root, R.blank(
            phase=R.BECOMES, scope={"world": True}, name="starving faints",
            when=[{"subject": "direct", "is": ["starving"]}],
            effects=[{"type": "set_state", "role": "direct",
                      "add": ["fainted"]}]))

    def draining(self, figure=50, rate=-1):
        traits.adjust(self.char1, "hunger", set_to=figure, rate=rate,
                      world_root=self.root, announce=False)
        becoming.settle()

    def wait(self, seconds):
        """Let real time and the reactor both move on."""
        self.now += seconds
        self.clock.advance(seconds)


@tag("world")
class WorkingOutWhen(CrossingTest):

    def test_the_threshold_comes_from_a_derived_state_a_rule_watches(self):
        self.starving_kills()
        self.assertEqual(becoming.thresholds(self.root, self.char1),
                         {"hunger": {10.0}})

    def test_a_falling_figure_reaches_a_threshold_below_it(self):
        self.starving_kills()
        self.draining(50, -2)
        self.assertAlmostEqual(becoming.next_crossing(self.root, self.char1),
                               20.0, places=3)

    def test_a_figure_moving_away_never_does(self):
        self.starving_kills()
        self.draining(50, 2)
        self.assertIsNone(becoming.next_crossing(self.root, self.char1))

    def test_nor_one_stopped_short_by_its_rate_target(self):
        self.starving_kills()
        self.draining(50, -1)
        self.char1.traits.get("hunger").ratetarget = 20
        self.assertIsNone(becoming.next_crossing(self.root, self.char1))


@tag("world")
class FiringThen(CrossingTest):

    def test_it_fires_when_the_figure_gets_there(self):
        self.starving_kills()
        self.draining(50, -1)
        self.wait(30)
        self.assertNotIn("fainted", verbs.states(self.char1))
        self.wait(11)
        self.assertIn("fainted", verbs.states(self.char1))

    def test_nothing_is_armed_while_the_world_sleeps(self):
        self.starving_kills()
        with mock.patch.object(becoming, "_awake", return_value=False):
            self.draining(50, -1)
        self.assertIsNone(getattr(self.char1.ndb, becoming.TIMER, None))

    def test_a_timer_that_fires_into_a_sleeping_world_does_nothing(self):
        self.starving_kills()
        self.draining(50, -1)
        with mock.patch.object(becoming, "_awake", return_value=False):
            self.wait(41)
        self.assertNotIn("fainted", verbs.states(self.char1))
        self.assertIsNone(getattr(self.char1.ndb, becoming.TIMER, None))

    def test_but_the_crossing_is_found_at_the_next_checkpoint(self):
        self.starving_kills()
        self.draining(50, -1)
        with mock.patch.object(becoming, "_awake", return_value=False):
            self.wait(41)
        traits.notice_changes(self.char1)
        becoming.settle()
        self.assertIn("fainted", verbs.states(self.char1))

    def test_stopping_the_drift_clears_the_timer(self):
        self.starving_kills()
        self.draining(50, -1)
        traits.adjust(self.char1, "hunger", rate=0, world_root=self.root,
                      announce=False)
        self.assertIsNone(getattr(self.char1.ndb, becoming.TIMER, None))

    def test_a_drifted_cost_follows_the_figure(self):
        """A derived state worth something is timed as well: gear follows it."""
        verbs.register_state(self.root, "weak", bonuses={"strength": -3},
                             when=[{"subject": "direct", "trait": "hunger",
                                    "max": 10}])
        traits.adjust(self.char1, "strength", set_to=10, world_root=self.root,
                      announce=False)
        self.draining(50, -1)
        self.wait(41)
        self.assertEqual(traits.value(self.char1, "strength"), 7)
