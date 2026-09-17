"""
Setting a world's clock, and who is told what time it is.

Every world has the real clock until somebody changes it, and the usual change
is only the year. World generation may set a year and does not have to; NPCs are
told the date in words, so a barman in 1852 does not mention the telephone. See
docs/becoming-and-time.md 8.5 and 8.6.
"""

from datetime import datetime

from django.test import SimpleTestCase, tag

from tests.base import GameTest
from tests.support import (FakeSponsor, immediately, replying, tool_call,
                           tool_reply)
from world import clock, lore, worldgen


class SettingTest(GameTest):

    def setUp(self):
        super().setUp()
        self.root = self.room1
        self.root.db.is_world_root = True
        self.root.db.world_root = self.root
        self.now = datetime(2026, 9, 15, 19, 0).timestamp()
        clock.NOW = lambda: self.now

    def tearDown(self):
        clock.NOW = None
        super().tearDown()


@tag("world")
class TheWorldSpec(SettingTest):

    def test_a_year_in_the_spec_sets_the_year(self):
        lore.store(self.root, {"clock": {"year": 1852}})
        self.assertEqual(clock.now(self.root).year, 1852)

    def test_the_spec_keeps_the_clock_exactly_across_a_reset(self):
        clock.set_year(self.root, 1852)
        spec = lore.spec_of(self.root)
        clock.reset(self.root)
        lore.store(self.root, spec)
        self.assertEqual(clock.now(self.root), datetime(1852, 9, 15, 19, 0))

    def test_a_world_on_real_time_keeps_nothing(self):
        self.assertEqual(lore.spec_of(self.root)["clock"], {})

    def test_real_puts_it_back(self):
        clock.set_year(self.root, 1852)
        lore.store(self.root, {"clock": {"real": True}})
        self.assertTrue(clock.is_real(self.root))

    def test_what_cannot_be_set_is_said(self):
        problems = lore.store_clock(self.root, {"year": 20000})
        self.assertTrue(problems)
        self.assertTrue(clock.is_real(self.root))


@tag("world")
class WhoIsTold(SettingTest):

    def test_a_prompt_gets_the_date_in_words(self):
        clock.set_year(self.root, 1852)
        line = lore.when(self.root)
        self.assertIn("1852", line)
        self.assertTrue(line.startswith("It is a "))

    def test_nothing_is_said_outside_a_world(self):
        self.assertEqual(lore.when(None), "")

    def test_view_world_says_what_time_it_is(self):
        from commands.world_subject import _world_detail

        clock.seed_periods(self.root)
        clock.set_year(self.root, 1852)
        said = _world_detail(self.root, 1, 1)
        self.assertIn("15 September 1852, 7:00pm", said)
        self.assertIn("dusk", said)


@tag("unit")
class TypingIt(SimpleTestCase):

    def test_a_year(self):
        from commands.world_subject import _parse_year

        self.assertEqual(_parse_year("1852"), (1852, None))
        self.assertIsNone(_parse_year("a long time ago")[0])
        self.assertIsNone(_parse_year("0")[0])

    def test_a_date_and_hour(self):
        from commands.world_subject import _parse_now

        self.assertEqual(_parse_now("1852-06-14 19:30"),
                         ("1852-06-14T19:30:00", None))
        self.assertIsNone(_parse_now("Tuesday")[0])

    def test_a_day_length(self):
        from commands.world_subject import _parse_day

        self.assertEqual(_parse_day("120 minutes"), (120.0, None))
        self.assertIsNone(_parse_day("0")[0])


@tag("world")
class GenerationMayChooseAYear(SettingTest):

    def plan(self, **extra):
        zones = [{"name": name, "purpose": "things happen",
                  "room_types": [name.lower()], "room_budget": 4}
                 for name in ("Hall", "Wing", "Yard")]
        planned = []
        with immediately(), replying(
                tool_reply(tool_call("plan_world", zones=zones, **extra))):
            worldgen._generate_plan(FakeSponsor(), "Victorian London", "",
                                    planned.append)
        return planned[0]

    def test_a_setting_that_names_an_era_gets_its_year(self):
        self.assertEqual(self.plan(year=1852)["year"], 1852)

    def test_and_one_that_does_not_stays_real(self):
        self.assertNotIn("year", self.plan())
