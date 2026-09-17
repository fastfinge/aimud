"""
How long ago something happened, to a character.

Phase 10 of docs/becoming-and-time.md, §8.7. Ages are read in the world's own
time; working memory says how old it is; a summary is as old as what it
summarises and a fact is not old at all; the `recall` tool ages what it finds;
and distillation is told dates that stay true. None of it needs a model or
mnemosyne: rows are handed over directly, and the clock is moved by hand.
"""

import sqlite3
from datetime import datetime, timedelta
from unittest import mock

from django.test import SimpleTestCase, tag
from evennia import create_object

from tests.base import GameTest
from tests.support import FakeSponsor, finishing, immediately, replying
from world import clock, fact_gen, memory, npc_gen
from world import toolbox as tb


def at(*when):
    """A real timestamp for a local date and time."""
    return datetime(*when).timestamp()


def stamp(when):
    """A real timestamp as mnemosyne writes one: local ISO."""
    return datetime.fromtimestamp(when).isoformat()


class ClockedWorld(GameTest):
    """A world whose real clock stands at noon on 16 September 2026."""

    def setUp(self):
        super().setUp()
        self.root = self.room1
        self.root.db.is_world_root = True
        self.room1.db.world_root = self.root
        self.now = at(2026, 9, 16, 12, 0)
        clock.NOW = lambda: self.now

    def tearDown(self):
        clock.NOW = None
        super().tearDown()

    def ago(self, **delta):
        return self.now - timedelta(**delta).total_seconds()


@tag("unit")
class TheWordsPastAFewDays(SimpleTestCase):

    NOW = datetime(2026, 9, 15, 18, 0, 0)

    def test_weeks_months_and_years(self):
        for delta, expected in ((timedelta(days=10), "a week ago"),
                                (timedelta(days=20), "2 weeks ago"),
                                (timedelta(days=45), "a month ago"),
                                (timedelta(days=100), "3 months ago"),
                                (timedelta(days=400), "a year ago"),
                                (timedelta(days=1000), "2 years ago")):
            when = (self.NOW - delta).isoformat()
            self.assertEqual(memory.age_of(when, self.NOW), expected, delta)

    def test_working_memory_stamps_are_numbers(self):
        when = (self.NOW - timedelta(days=2)).timestamp()
        self.assertEqual(memory.age_of(when, self.NOW), "2 days ago")


@tag("world")
class InTheWorldsOwnTime(ClockedWorld):

    def test_a_real_world_is_aged_as_it_always_was(self):
        self.assertEqual(memory.age_of(self.ago(days=1), world_root=self.root),
                         "yesterday")

    def test_a_world_whose_day_is_an_hour_long_ages_faster(self):
        clock.set_day_length(self.root, 60)
        # Ten real minutes is four hours there.
        self.assertEqual(
            memory.age_of(self.ago(minutes=10), world_root=self.root),
            "earlier today")
        # And a real day is twenty-four of its days.
        self.assertEqual(memory.age_of(self.ago(days=1), world_root=self.root),
                         "3 weeks ago")

    def test_moving_the_year_leaves_every_age_where_it_was(self):
        """Why ages are converted when read, not stamped with a world date."""
        clock.set_year(self.root, 1852)
        self.assertEqual(memory.age_of(self.ago(days=3), world_root=self.root),
                         "3 days ago")

    def test_yesterday_falls_on_the_worlds_own_midnight(self):
        # Eleven in the morning there, when it is noon here; two hours back is
        # nine, the same day, whatever the real hour.
        clock.set_now(self.root, datetime(1852, 6, 14, 11, 0))
        self.assertEqual(memory.age_of(self.ago(hours=2), world_root=self.root),
                         "earlier today")
        self.assertEqual(memory.age_of(self.ago(hours=12), world_root=self.root),
                         "yesterday")


@tag("world")
class SummariesAndFacts(ClockedWorld):

    def test_a_summary_is_as_old_as_what_it_summarises(self):
        """Sleep stamps it days later; it was "earlier today" otherwise."""
        row = {"content": "I mended the well with Bram.",
               "timestamp": stamp(self.ago(hours=1)), "source": "sleep_consolidation",
               "span": (stamp(self.ago(days=9)), stamp(self.ago(days=5)))}
        self.assertEqual(memory.format_recalled([row], world_root=self.root),
                         "- between a week ago and 5 days ago: "
                         "I mended the well with Bram.")

    def test_one_that_all_happened_on_a_day_says_the_day_once(self):
        row = {"content": "A quiet morning.", "timestamp": stamp(self.now),
               "span": (stamp(self.ago(days=4, hours=1)),
                        stamp(self.ago(days=4)))}
        self.assertEqual(memory.format_recalled([row], world_root=self.root),
                         "- 4 days ago: A quiet morning.")

    def test_a_distilled_fact_is_not_aged(self):
        row = {"content": "Bram owes me a favour.",
               "timestamp": stamp(self.ago(days=1)),
               "source": memory.FACT_SOURCE}
        self.assertEqual(memory.format_recalled([row], world_root=self.root),
                         "- Bram owes me a favour.")

    def test_a_summary_is_ordered_by_when_it_happened(self):
        summary = {"content": "the summary", "timestamp": stamp(self.now),
                   "span": (stamp(self.ago(days=6)), stamp(self.ago(days=5)))}
        event = {"content": "the event", "timestamp": stamp(self.ago(days=2))}
        shown = memory.format_recalled([event, summary],
                                       world_root=self.root).splitlines()
        self.assertTrue(shown[0].endswith("the summary"), shown)


@tag("unit")
class WhereASummarysSpanIsFound(SimpleTestCase):
    """The one SQL read at the mnemosyne boundary, against its two tables."""

    def memory(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE episodic_memory (id TEXT, summary_of TEXT)")
        conn.execute("CREATE TABLE working_memory (id TEXT, timestamp TEXT)")
        conn.executemany("INSERT INTO working_memory VALUES (?, ?)",
                         [("w1", "2026-09-01T10:00:00"),
                          ("w2", "2026-09-04T09:00:00"),
                          ("w3", "2026-09-10T09:00:00")])
        conn.execute("INSERT INTO episodic_memory VALUES ('e1', 'w1,w2')")
        conn.execute("INSERT INTO episodic_memory VALUES ('e2', '')")
        return mock.Mock(conn=conn)

    def test_the_oldest_and_newest_of_what_it_names(self):
        self.assertEqual(memory._span_sync(self.memory(), "e1"),
                         ("2026-09-01T10:00:00", "2026-09-04T09:00:00"))

    def test_nothing_named_is_no_span(self):
        found = self.memory()
        self.assertEqual(memory._span_sync(found, "e2"), ())
        self.assertEqual(memory._span_sync(found, "missing"), ())


@tag("world")
class WorkingMemory(ClockedWorld):

    def setUp(self):
        super().setUp()
        from typeclasses.npcs import NPC

        self.npc = create_object(NPC, key="Bram", location=self.room1)

    def test_what_goes_in_is_stamped(self):
        self.npc._note_to_self("The door is locked.")
        self.assertEqual(self.npc.db.action_history[-1]["at"], self.now)

    def test_all_of_it_recent_is_just_now(self):
        history = [{"type": "action", "actor": "Bram", "text": "waves",
                    "line": "Bram waved.", "at": self.ago(minutes=2)}]
        self.assertEqual(npc_gen._aged_history(history, self.root),
                         "Just now:\nBram waved.")

    def test_a_week_old_conversation_is_not_just_now(self):
        history = [{"type": "say", "actor": "Raldor", "text": "hello",
                    "line": "Raldor said hello.", "at": self.ago(days=7)},
                   {"type": "action", "actor": "Raldor", "text": "arrives",
                    "line": "Raldor arrived.", "at": self.ago(minutes=1)}]
        self.assertEqual(npc_gen._aged_history(history, self.root),
                         "Most recently:\na week ago: Raldor said hello.\n"
                         "Raldor arrived.")

    def test_an_entry_from_before_the_stamp_is_shown_as_it_was(self):
        history = [{"type": "action", "actor": "Bram", "text": "waves",
                    "line": "Bram waved."}]
        self.assertEqual(npc_gen._aged_history(history, self.root),
                         "Just now:\nBram waved.")

    def test_what_recall_compares_against_carries_no_age(self):
        """Recall leaves out what is on show by its words, not its age."""
        self.npc.db.action_history = [
            {"type": "say", "actor": "Raldor", "text": "hello",
             "line": "Raldor said hello.", "at": self.ago(days=7)}]
        text, _bank, _cues, on_show = npc_gen._memory_inputs(
            self.npc, self.room1, "Hall")
        self.assertEqual(on_show, ["Raldor said hello."])
        self.assertIn("a week ago: Raldor said hello.", text)


@tag("world")
class TheRecallTool(ClockedWorld):

    def test_what_it_finds_is_aged_like_the_prompt(self):
        tool = memory.lookup_tools()[0]
        rows = [{"content": "Raldor gave me a coin.", "metadata": {},
                 "timestamp": stamp(self.ago(days=2))}]
        said = []
        ctx = tb.ToolContext(world_root=self.root, room=self.room1,
                             actor=self.char1)
        with immediately(), \
                mock.patch.object(memory, "where_for", return_value="bank"), \
                mock.patch.object(memory, "recall_rows_sync",
                                  return_value=rows):
            tool.handler(ctx, {"query": "coin"}, said.append)
        self.assertEqual(said, ["- 2 days ago: Raldor gave me a coin."])

    def test_finding_nothing_still_says_so(self):
        tool = memory.lookup_tools()[0]
        said = []
        with immediately(), \
                mock.patch.object(memory, "where_for", return_value="bank"), \
                mock.patch.object(memory, "recall_rows_sync", return_value=[]):
            tool.handler(tb.ToolContext(world_root=self.root,
                                        actor=self.char1),
                         {"query": "coin"}, said.append)
        self.assertEqual(said, ["Nothing comes to mind about coin."])


@tag("world")
class DatesThatStayTrue(ClockedWorld):

    def test_a_span_on_the_worlds_calendar(self):
        clock.set_year(self.root, 1852)
        row = {"span": (stamp(self.ago(days=4)), stamp(self.ago(days=2)))}
        self.assertEqual(memory.dated(row, self.root),
                         "from 12 September 1852 to 14 September 1852")

    def test_one_day(self):
        row = {"timestamp": stamp(self.ago(hours=1))}
        self.assertEqual(memory.dated(row, self.root), "on 16 September 2026")

    def test_nothing_to_tell_from(self):
        self.assertEqual(memory.dated({"timestamp": ""}, self.root), "")

    def test_distillation_is_shown_the_dates(self):
        clock.set_year(self.root, 1852)
        summary = {"content": "I helped Bram mend the well.",
                   "timestamp": stamp(self.now),
                   "span": (stamp(self.ago(days=3)), stamp(self.ago(days=3)))}

        def distillable(where, callback):
            callback([summary], "through")

        def store_facts(where, facts, through, on_done=None):
            if on_done:
                on_done(len(facts))

        with immediately(), \
                replying(finishing(record_facts={"facts": []})) as recorder, \
                mock.patch("world.activity.quiet_enough_for_heavy_work",
                           return_value=True), \
                mock.patch("world.memory.distillable", distillable), \
                mock.patch("world.memory.store_facts", store_facts), \
                mock.patch.object(fact_gen, "_world_of",
                                  return_value=self.root), \
                mock.patch.object(fact_gen, "_account_for",
                                  return_value=FakeSponsor()):
            fact_gen.distil(banks=["bank"])
        self.assertIn("- (on 13 September 1852) I helped Bram mend the well.",
                      recorder.sent(0))
        self.assertIn("stays true", recorder.sent(0))
