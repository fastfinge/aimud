"""
Telling a player a model is still working, on a clock moved by hand.

Phase 1 of docs/generator-tool-loops.md. Every test here moves time itself,
because a test that waited ten real seconds to see a notice would be a test
nobody ran.
"""

from unittest import mock

from django.test import SimpleTestCase, tag
from evennia import create_object
from evennia.utils.test_resources import EvenniaCommandTest, EvenniaTest

from commands.account_cmds import CmdBusy
from tests.support import clock
from world import busy


class _Listening:
    """What a character is sent, kept, and a clock to move."""

    def listen(self):
        self.clock = clock()
        self.said = []
        self.char1.msg = lambda text="", **kwargs: self.said.append(str(text))

    def notices(self):
        return [line for line in self.said if line.startswith("Still ")]

    def start(self, doing="trying to pry the crate", who=None, **kwargs):
        return busy.start(who or self.char1, doing, clock=self.clock, **kwargs)


@tag("world")
class TellingAPlayer(_Listening, EvenniaTest):

    def setUp(self):
        super().setUp()
        self.listen()

    def test_nothing_is_said_before_the_interval(self):
        self.start()
        self.clock.advance(9)
        self.assertEqual(self.notices(), [])

    def test_one_line_per_interval_with_how_long_it_has_been(self):
        self.start()
        self.clock.advance(10)
        self.clock.advance(10)
        self.assertEqual(self.notices(), [
            "Still trying to pry the crate... (10 seconds)",
            "Still trying to pry the crate... (20 seconds)",
        ])

    def test_it_says_what_the_job_is_doing_now(self):
        wait = self.start()
        wait.stage("working out what pry does")
        self.clock.advance(10)
        self.assertEqual(self.notices(),
                         ["Still working out what pry does... (10 seconds)"])

    def test_done_stops_it_and_can_be_said_twice(self):
        wait = self.start()
        self.clock.advance(10)
        wait.done()
        wait.done()
        self.clock.advance(60)
        self.assertEqual(len(self.notices()), 1)
        self.assertFalse(wait.open)

    def test_how_long_a_player_waited_is_written_down(self):
        """A verb that needs four calls is four ledger entries and one wait."""
        wait = self.start()
        self.clock.advance(34.5)
        with mock.patch("world.busy.logger.log_info") as logged:
            wait.done()
            wait.done()
        logged.assert_called_once_with(
            "busy: waited 34.5s for 'trying to pry the crate'")

    def test_a_wait_nobody_was_told_about_is_not(self):
        wait = busy.Wait("building the way north", clock=self.clock)
        self.clock.advance(20)
        with mock.patch("world.busy.logger.log_info") as logged:
            wait.done()
        logged.assert_not_called()

    def test_closing_closes_the_wait_before_the_answer(self):
        wait = self.start()
        seen = []
        busy.closing(wait, lambda answer: seen.append((answer, wait.open)))(
            "a room")
        self.assertEqual(seen, [("a room", False)])

    def test_a_player_who_has_gone_is_not_told_again(self):
        self.start()
        with mock.patch.object(self.char1.sessions, "count", return_value=0):
            self.clock.advance(30)
        self.assertEqual(self.notices(), [])

    def test_a_player_chooses_how_often(self):
        busy.set_interval(self.char1.account, 25)
        self.start()
        self.clock.advance(20)
        self.assertEqual(self.notices(), [])
        self.clock.advance(5)
        self.assertEqual(self.notices(),
                         ["Still trying to pry the crate... (25 seconds)"])

    def test_off_means_never(self):
        busy.set_interval(self.char1.account, 0)
        self.start()
        self.clock.advance(300)
        self.assertEqual(self.notices(), [])

    def test_a_lost_wait_stops_at_the_safety_limit(self):
        self.start(lifetime=30)
        self.clock.advance(10)
        self.clock.advance(10)
        self.clock.advance(10)
        self.clock.advance(60)
        self.assertEqual(len(self.notices()), 2)

    def test_a_long_download_can_ask_for_no_limit(self):
        self.start(lifetime=None)
        for _ in range(100):
            self.clock.advance(10)
        self.assertEqual(len(self.notices()), 100)


@tag("world")
class NobodyToTell(_Listening, EvenniaTest):
    """
    Only players. A character cannot worry that the game has crashed, and a
    notice in its memory would be one more thing its next prompt read past.
    """

    def setUp(self):
        super().setUp()
        self.listen()

    def test_a_character_nobody_plays_is_refused(self):
        npc = create_object("typeclasses.npcs.NPC", key="Bram",
                            location=self.room1)
        sent = []
        npc.msg = lambda text="", **kwargs: sent.append(text)
        wait = self.start(who=npc)
        self.clock.advance(60)
        self.assertEqual(sent, [])
        self.assertEqual(wait.waiters, [])
        self.assertEqual(npc.db.action_history or [], [])

    def test_nor_is_a_thing(self):
        wait = busy.Wait("building the way north", clock=self.clock)
        self.assertFalse(wait.add(self.obj1))

    def test_the_players_at_a_door_are_told_and_the_rest_are_not(self):
        wait = self.start("building the way north")
        self.assertFalse(wait.add(self.obj1))
        self.assertTrue(wait.add(self.char1))       # already there; still true
        self.assertEqual(wait.waiters, [self.char1])

    def test_a_wait_already_closed_takes_nobody(self):
        wait = self.start()
        wait.done()
        self.assertFalse(wait.add(self.char1))


@tag("unit")
class ReadingWhatWasTyped(SimpleTestCase):

    def test_seconds_in_range(self):
        self.assertEqual(busy.parse_interval("20"), (20, ""))
        self.assertEqual(busy.parse_interval(str(busy.LEAST)),
                         (busy.LEAST, ""))
        self.assertEqual(busy.parse_interval(str(busy.MOST)), (busy.MOST, ""))

    def test_off_and_default(self):
        self.assertEqual(busy.parse_interval("off"), (0, ""))
        self.assertEqual(busy.parse_interval("default"), (None, ""))

    def test_anything_else_is_a_complaint(self):
        for said in ("3", "500", "soon", ""):
            seconds, complaint = busy.parse_interval(said)
            self.assertIsNone(seconds, said)
            self.assertTrue(complaint, said)


@tag("unit")
class NamingEachStage(SimpleTestCase):
    """`attempt`'s waiter, which is how a verb's stages reach a wait."""

    def test_the_wait_opens_once_and_every_stage_is_named(self):
        from world.attempt import _once

        happened = []
        waiter = _once(lambda: happened.append("opened"),
                       lambda stage: happened.append(stage))
        waiter("working out what pry takes")
        waiter("working out what pry does here")
        waiter()
        self.assertEqual(happened, ["opened", "working out what pry takes",
                                    "working out what pry does here"])

    def test_it_still_tolerates_nothing_to_call(self):
        from world.attempt import _once

        _once(None)("a stage with nobody listening")
        _once(None, None)()


@tag("world")
class TheBusyCommand(EvenniaCommandTest):

    def test_unset_it_says_the_default(self):
        said = self.call(CmdBusy(), "")
        self.assertIn("every 10 seconds", said)
        self.assertIn("default", said)

    def test_setting_it_is_kept_on_the_account(self):
        self.call(CmdBusy(), "30")
        self.assertEqual(busy.interval_for(self.char1), 30)
        self.assertIn("every 30 seconds", self.call(CmdBusy(), ""))

    def test_off(self):
        self.call(CmdBusy(), "off")
        self.assertEqual(busy.interval_for(self.char1), 0)
        self.assertIn("not told", self.call(CmdBusy(), ""))

    def test_back_to_the_default(self):
        self.call(CmdBusy(), "30")
        self.call(CmdBusy(), "default")
        self.assertEqual(busy.interval_for(self.char1), busy.DEFAULT_INTERVAL)
        self.assertIsNone(busy.chosen(self.char1.account))

    def test_out_of_range_is_refused_and_nothing_changes(self):
        said = self.call(CmdBusy(), "2")
        self.assertIn("from 5 to 120", said)
        self.assertIsNone(busy.chosen(self.char1.account))


@tag("world")
class WaitingOnAVerb(_Listening, EvenniaTest):
    """End to end through the real command handler, as a player types it."""

    def setUp(self):
        super().setUp()
        self.room1.db.world_root = self.room1
        self.room1.db.is_world_root = True
        self.room1.db.world_description = "A harbour town."
        self.listen()

    def test_a_slow_verb_says_it_is_still_working_until_it_answers(self):
        held = {}

        def attempt(caller, raw, sponsor, on_message, on_wait=None,
                    on_stage=None, **kwargs):
            on_wait()
            on_stage("working out what pry does here")
            held["deliver"] = on_message

        paying = mock.Mock()
        paying.key.return_value = "a key"
        with mock.patch.object(busy, "CLOCK", self.clock), \
                mock.patch("world.attempt.attempt", attempt), \
                mock.patch("commands.unknown_cmd._sponsor_for",
                           return_value=paying):
            self.char1.execute_cmd("pry crate")
            self.clock.advance(10)
            held["deliver"]("You pry the crate open.")
            self.clock.advance(60)

        self.assertEqual(self.notices(),
                         ["Still working out what pry does here... "
                          "(10 seconds)"])
        self.assertIn("You pry the crate open.", self.said)
