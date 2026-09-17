"""
What time it is in a world, and what happens at a time of day.

Every world has a clock, the real one until it says otherwise, read and never
kept. Time of day is derived states of the world, and a place rule that watches
the clock fires live in a room somebody is in, or once and silently for a room
nobody was watching. See docs/becoming-and-time.md §8.
"""

from datetime import datetime
from unittest import mock

from django.test import SimpleTestCase, tag

from tests.base import GameTest
from tests.support import clock as reactor_clock
from world import becoming, clock, verbs
from world import conditions as C
from world import rulebooks as R


def at(*when):
    """A real timestamp for a local date and time."""
    return datetime(*when).timestamp()


class ClockTest(GameTest):

    def setUp(self):
        super().setUp()
        becoming.forget_waiting()
        self.root = self.room1
        self.root.db.is_world_root = True
        self.room1.db.world_root = self.root
        self.now = at(2026, 9, 16, 4, 0)
        clock.NOW = lambda: self.now

    def tearDown(self):
        clock.NOW = None
        becoming.forget_waiting()
        super().tearDown()


@tag("unit")
class TheDial(SimpleTestCase):

    def test_a_range_and_its_swap_cover_the_day_exactly_once(self):
        for half_hours in range(48):
            hour = half_hours / 2
            self.assertNotEqual(clock.in_range(hour, 20, 6),
                                clock.in_range(hour, 6, 20), hour)

    def test_a_range_includes_its_start_and_not_its_end(self):
        self.assertTrue(clock.in_range(20, 20, 6))
        self.assertFalse(clock.in_range(6, 20, 6))

    def test_hours_are_said_the_way_people_say_them(self):
        self.assertEqual(clock.hour_words(20), "eight at night")
        self.assertEqual(clock.hour_words(6), "six in the morning")
        self.assertEqual(clock.hour_words(0), "midnight")
        self.assertEqual(clock.hour_words(12), "noon")
        self.assertEqual(clock.hour_words(18.5), "half past six in the evening")

    def test_the_condition_reads_as_a_range_of_hours(self):
        self.assertEqual(
            C.describe({"subject": "world", "clock": {"from": 20, "to": 6}}),
            "it is between eight at night and six in the morning")

    def test_its_mirror_is_the_same_dial_the_other_way(self):
        self.assertEqual(
            C.negate({"subject": "world", "clock": {"from": 20, "to": 6}}),
            {"subject": "world", "clock": {"from": 6.0, "to": 20.0}})
        self.assertIsNone(
            C.negate({"subject": "world", "clock": {"from": 6, "to": 6}}))


@tag("world")
class EveryWorldHasOne(ClockTest):

    def test_it_is_the_real_one_until_told_otherwise(self):
        self.assertTrue(clock.is_real(self.root))
        self.assertEqual(clock.now(self.root), datetime(2026, 9, 16, 4, 0))

    def test_setting_the_year_keeps_the_day_and_the_hour(self):
        clock.set_year(self.root, 1852)
        self.assertEqual(clock.now(self.root), datetime(1852, 9, 16, 4, 0))
        self.now += 3600
        self.assertEqual(clock.now(self.root), datetime(1852, 9, 16, 5, 0))

    def test_a_leap_day_in_a_year_without_one_is_the_twenty_eighth(self):
        self.now = at(2024, 2, 29, 9, 0)
        clock.set_year(self.root, 2023)
        self.assertEqual(clock.now(self.root), datetime(2023, 2, 28, 9, 0))

    def test_a_shorter_day_does_not_make_the_hour_jump(self):
        clock.set_day_length(self.root, 60)
        self.assertEqual(clock.now(self.root), datetime(2026, 9, 16, 4, 0))
        self.now += 60 * 60
        self.assertEqual(clock.now(self.root), datetime(2026, 9, 17, 4, 0))

    def test_and_it_goes_back_to_real_time(self):
        clock.set_year(self.root, 1852)
        clock.reset(self.root)
        self.assertTrue(clock.is_real(self.root))

    def test_a_character_is_told_the_date_in_words(self):
        self.now = at(2026, 9, 15, 19, 0)
        clock.set_year(self.root, 1852)
        expected = datetime(1852, 9, 15, 19, 0).strftime("%A")
        self.assertEqual(clock.said(self.root),
                         f"It is a {expected} evening in September, 1852.")

    def test_the_condition_asks_this_worlds_dial(self):
        ctx = C.context({}, self.char1, self.root)
        night = {"subject": "world", "clock": {"from": 20, "to": 6}}
        self.assertTrue(C.evaluate(night, ctx))
        self.now = at(2026, 9, 16, 12, 0)
        self.assertFalse(C.evaluate(night, ctx))


@tag("world")
class TimesOfDay(ClockTest):
    loose_objects = 1

    def test_every_world_is_given_them_once(self):
        clock.seed_periods(self.root)
        self.assertEqual(
            {slug for slug in verbs.derived_states(self.root)},
            {"dawn", "day", "dusk", "night"})

    def test_night_is_true_of_the_world_and_of_nothing_in_it(self):
        clock.seed_periods(self.root)
        self.now = at(2026, 9, 16, 22, 0)
        self.assertIn("night", verbs.implied_states(self.root))
        self.assertNotIn("night", verbs.implied_states(self.obj1))
        self.assertNotIn("night", verbs.condition(self.obj1))

    def test_a_rule_asks_for_it_by_name(self):
        clock.seed_periods(self.root)
        ctx = C.context({}, self.char1, self.root)
        wants = {"subject": "world", "is": ["day"]}
        self.assertFalse(C.evaluate(wants, ctx))
        self.now = at(2026, 9, 16, 12, 0)
        self.assertTrue(C.evaluate(wants, ctx))

    def test_a_world_that_let_one_go_is_not_given_it_back(self):
        clock.seed_periods(self.root)
        vocab = verbs.vocabulary(self.root)
        vocab.pop("dusk")
        self.root.db.state_vocabulary = vocab
        clock.seed_periods(self.root)
        self.assertNotIn("dusk", verbs.derived_states(self.root))


class PlaceRuleTest(ClockTest):

    def setUp(self):
        super().setUp()
        self.reactor = reactor_clock()
        becoming.CLOCK = self.reactor
        self.awake = mock.patch.object(becoming, "_awake", return_value=True)
        self.awake.start()
        self.occupied = mock.patch.object(becoming, "occupied_rooms",
                                          return_value=[self.room1])
        self.occupied.start()
        clock.seed_periods(self.root)
        self.bell = R.add(self.root, R.blank(
            phase=R.BECOMES, scope={"world": True}, about="here",
            name="the bell rings at dawn",
            when=[{"subject": "world", "is": ["dawn"]}],
            effects=[{"type": "set_state", "role": "direct",
                      "add": ["rung"]}],
            report="Somewhere across the town, a bell rings."))

    def tearDown(self):
        self.occupied.stop()
        self.awake.stop()
        disarm = getattr(self.root.ndb, becoming.CLOCK_TIMER, None)
        if disarm is not None and disarm.active():
            disarm.cancel()
        becoming.CLOCK = None
        super().tearDown()

    def wait(self, seconds):
        self.now += seconds
        self.reactor.advance(seconds)


@tag("world")
class AtDawn(PlaceRuleTest):

    def test_the_timer_is_set_for_the_next_boundary_a_place_rule_watches(self):
        self.assertEqual(becoming.clock_hours(self.root), {5.0, 7.0})
        self.assertIsNotNone(getattr(self.root.ndb, becoming.CLOCK_TIMER))

    def test_the_bell_rings_in_a_room_somebody_is_in(self):
        with mock.patch.object(self.char1, "msg") as told:
            self.wait(59 * 60)
            self.assertNotIn("rung", verbs.states(self.room1))
            self.wait(2 * 60)
        self.assertIn("rung", verbs.states(self.room1))
        said = " ".join(str(call.args[0]) for call in told.call_args_list
                        if call.args)
        self.assertIn("a bell rings", said)

    def test_nothing_is_set_while_the_world_sleeps(self):
        with mock.patch.object(becoming, "_awake", return_value=False):
            becoming.arm_clock(self.root)
        self.assertIsNone(getattr(self.root.ndb, becoming.CLOCK_TIMER))


@tag("world")
class ComingIntoARoomNobodyWasWatching(PlaceRuleTest):

    def setUp(self):
        super().setUp()
        with mock.patch.object(becoming, "_awake", return_value=False):
            becoming.arm_clock(self.root)

    def test_a_first_visit_only_notes_what_is_true(self):
        self.now = at(2026, 9, 16, 5, 30)
        becoming.arrived(self.char1)
        self.assertNotIn("rung", verbs.states(self.room1))

    def test_what_rose_while_nobody_watched_happens_once_and_silently(self):
        becoming.arrived(self.char1)             # noted at four, not dawn
        self.now = at(2026, 9, 16, 12, 0)
        with mock.patch.object(self.char1, "msg") as told:
            becoming.arrived(self.char1)
        self.assertIn("rung", verbs.states(self.room1))
        said = " ".join(str(call.args[0]) for call in told.call_args_list
                        if call.args)
        self.assertNotIn("bell", said)

    def test_and_not_again_on_the_next_arrival(self):
        becoming.arrived(self.char1)
        self.now = at(2026, 9, 16, 12, 0)
        becoming.arrived(self.char1)
        verbs.apply_states(self.room1, remove=["rung"], world_root=self.root)
        self.now = at(2026, 9, 16, 13, 0)
        becoming.arrived(self.char1)
        self.assertNotIn("rung", verbs.states(self.room1))
