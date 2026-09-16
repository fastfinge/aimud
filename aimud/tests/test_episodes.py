"""
What is remembered, and how it is shown again.

Three questions, one per class. What a memory says -- an episode, in the past
tense, named, with no state claims in it. How a recalled memory is said again
-- with the names things have now, or as it was stored when somebody in it is
gone. And how an NPC is shown what it remembers -- oldest first, with an age,
beside what is true now.
"""

from datetime import datetime, timedelta
from unittest import mock

from django.test import SimpleTestCase, tag

from tests.base import GameTest
from world import events, memory, ownership, pronouns


class Stage(GameTest):
    characters = 2
    loose_objects = 1

    def setUp(self):
        super().setUp()
        self.room1.db.world_root = self.room1
        self.room1.db.is_world_root = True
        self.jessica, self.britney = self.char1, self.char2
        self.jessica.key, self.britney.key = "Jessica", "Britney"
        self.sword = self.obj1
        self.sword.key = "sword"
        pronouns.give(self.jessica, "she", self.room1)
        pronouns.give(self.britney, "she", self.room1)

    def event(self, template="{actor} $pconj(hand) {target} {direct}.",
              **fields):
        base = dict(actor=self.jessica, room=self.room1, verb="hand",
                    roles={"direct": self.sword, "target": self.britney},
                    room_template=template)
        base.update(fields)
        return events.Event(**base)


@tag("world")
class WhatIsRemembered(Stage):
    second_room = True

    def test_an_episode_is_the_narration_in_the_past(self):
        line, _about, _metadata = memory.episode_of(self.event())
        self.assertEqual(line, "Jessica handed Britney the sword.")

    def test_it_holds_no_effect_lines(self):
        line, _, _ = memory.episode_of(self.event(effects=["The sword is now blunt."]))
        self.assertNotIn("blunt", line)

    def test_a_contest_says_how_it_went(self):
        lost, _, _ = memory.episode_of(self.event(
            verb="attack", contested=True, outcome="failure",
            template="{actor} $pconj(swing) at {target}."))
        self.assertEqual(lost, "Jessica swung at Britney, and failed.")

    def test_with_no_narration_the_verb_and_its_roles_say_it(self):
        line, _, _ = memory.episode_of(self.event(
            template="", verb="hug", roles={"direct": self.britney}))
        self.assertEqual(line, "Jessica hugged Britney.")

    def test_and_looking_is_looking_at_something(self):
        line, _, _ = memory.episode_of(self.event(
            template="", verb="look", roles={"direct": self.sword}))
        self.assertEqual(line, "Jessica looked at the sword.")

    def test_the_metadata_is_enough_to_say_it_again(self):
        _, about, metadata = memory.episode_of(self.event(
            quotes={"quote": "take it"}))
        self.assertEqual(metadata["shape"], memory.SHAPE)
        self.assertEqual(metadata["actor"], self.jessica.id)
        self.assertEqual(metadata["roles"], {"direct": self.sword.id,
                                             "target": self.britney.id})
        self.assertEqual(metadata["quotes"], {"quote": "take it"})
        self.assertIn(("Britney", f"#{self.britney.id}"), about)

    def test_speech_reads_in_the_same_voice(self):
        self.assertEqual(memory.describe_event("say", "Raldor", "Hello."),
                         'Raldor said, "Hello."')

    def test_arriving_is_named_and_never_i(self):
        written = []
        with mock.patch("world.memory.remember",
                        lambda character, text, **kw: written.append(text)):
            self.jessica.move_to(self.room2, quiet=True)
        self.assertIn("Jessica arrived in Room2 from Room", written)

    def test_a_state_a_verb_set_is_a_triple_not_a_memory(self):
        from world import effects

        noted = []
        with mock.patch("world.memory.note_triple",
                        lambda where, subject, predicate, object_, **kw:
                        noted.append((subject, object_))):
            effects.apply(self.jessica, self.room1,
                          [{"type": "set_state", "role": "direct",
                            "add": ["blunt"]}],
                          bound={"direct": self.sword},
                          world_root=self.room1)
        self.assertIn((f"#{self.sword.id}", "blunt"), noted)


@tag("world")
class WhereThingsWent(Stage):
    """
    Moving and destroying things is the world's history, written as triples.
    Making them is not: things are made when first needed, not when first
    mentioned, so a record of it would be misleading.
    """

    second_room = True

    def noted(self, action):
        written = {"note": [], "end": []}

        def note(where, subject, predicate, object_, **kwargs):
            written["note"].append((subject, predicate, object_,
                                    kwargs.get("supersede")))

        def end(where, subject, predicate, object_=None):
            written["end"].append((subject, predicate, object_))

        with mock.patch("world.memory.note_triple", note), \
                mock.patch("world.memory.end_triples", end):
            action()
        return written

    def test_taking_a_thing_records_who_carries_it(self):
        written = self.noted(lambda: self.sword.move_to(
            self.jessica, quiet=True, move_type="get"))
        self.assertIn((f"#{self.sword.id}", "located",
                       f"carried_by #{self.jessica.id}", True),
                      written["note"])

    def test_placing_a_thing_says_how_it_sits(self):
        from evennia import create_object
        from typeclasses.objects import Object

        table = create_object(Object, key="table", location=self.room1)
        self.sword.db.relation = "on"
        written = self.noted(lambda: self.sword.move_to(
            table, quiet=True, move_type="place"))
        self.assertIn((f"#{self.sword.id}", "located", f"on #{table.id}", True),
                      written["note"])

    def test_dropping_a_thing_says_the_room(self):
        self.sword.move_to(self.jessica, quiet=True, move_type="get")
        written = self.noted(lambda: self.sword.move_to(
            self.room1, quiet=True, move_type="drop"))
        self.assertIn((f"#{self.sword.id}", "located",
                       f"in #{self.room1.id}", True), written["note"])

    def test_housekeeping_is_not_history(self):
        written = self.noted(lambda: self.sword.move_to(
            self.jessica, quiet=True, move_type="teleport"))
        self.assertEqual(written["note"], [])

    def test_a_person_moving_is_not_a_thing_moving(self):
        written = self.noted(lambda: self.jessica.move_to(
            self.room2, quiet=True))
        self.assertEqual(written["note"], [])

    def test_making_a_thing_is_not_history(self):
        from evennia import create_object
        from typeclasses.objects import Object

        written = self.noted(lambda: create_object(
            Object, key="lamp", location=self.room1))
        self.assertEqual(written["note"], [])

    def test_outside_a_world_nothing_is_written(self):
        written = self.noted(lambda: self.sword.move_to(
            self.room2, quiet=True))
        self.assertEqual(written["note"], [])

    def test_destroying_a_thing_closes_where_it_was(self):
        from world import effects

        was = f"#{self.sword.id}"        # read now: it is about to be gone
        written = self.noted(lambda: effects.apply(
            self.jessica, self.room1,
            [{"type": "destroy_object", "role": "direct"}],
            bound={"direct": self.sword}, world_root=self.room1))
        self.assertIn((was, "located", None), written["end"])
        self.assertIn((was, "is", "destroyed", False), written["note"])


@tag("world")
class SayingItAgain(Stage):

    def row(self, event, content=None, timestamp="2026-09-15T10:00:00"):
        line, _about, metadata = memory.episode_of(event)
        return {"id": "m1", "content": content or line,
                "timestamp": timestamp, "metadata": metadata}

    def test_a_renamed_character_is_remembered_by_their_new_name(self):
        row = self.row(self.event())
        self.britney.key = "Brit"
        self.assertEqual(memory.rerender(row), "Jessica handed Brit the sword.")

    def test_somebody_gone_leaves_the_stored_sentence(self):
        row = self.row(self.event())
        self.sword.delete()
        self.assertEqual(memory.rerender(row), "")
        self.assertIn("Jessica handed Britney the sword.",
                      memory.format_recalled([row]))

    def test_a_memory_written_before_this_shape_is_shown_as_stored(self):
        old = {"content": "I did: hug her", "timestamp": "",
               "metadata": {"verb": "hug"}}
        self.assertEqual(memory.rerender(old), "")
        self.assertEqual(memory.format_recalled([old]), "- I did: hug her")


@tag("unit")
class HowLongAgo(SimpleTestCase):

    NOW = datetime(2026, 9, 15, 18, 0, 0)

    def test_the_buckets(self):
        for delta, expected in ((timedelta(minutes=3), "moments ago"),
                                (timedelta(minutes=50), "a little while ago"),
                                (timedelta(hours=5), "earlier today"),
                                (timedelta(days=1), "yesterday"),
                                (timedelta(days=4), "4 days ago")):
            stamp = (self.NOW - delta).isoformat()
            self.assertEqual(memory.age_of(stamp, self.NOW), expected, delta)

    def test_a_timestamp_that_does_not_read_has_no_age(self):
        self.assertEqual(memory.age_of("", self.NOW), "")
        self.assertEqual(memory.age_of(None, self.NOW), "")


@tag("world")
class WhatAnNpcIsShown(Stage):

    NOW = datetime(2026, 9, 15, 18, 0, 0)

    def rows(self):
        early = memory.episode_of(self.event(
            template="{actor} $pconj(pick) up {direct}.", verb="get",
            roles={"direct": self.sword}))
        late = memory.episode_of(self.event())
        return [
            {"content": late[0], "metadata": late[2],
             "timestamp": (self.NOW - timedelta(minutes=2)).isoformat()},
            {"content": early[0], "metadata": early[2],
             "timestamp": (self.NOW - timedelta(days=1)).isoformat()},
        ]

    def test_oldest_first_with_an_age(self):
        shown = memory.format_recalled(self.rows(), now=self.NOW).splitlines()
        self.assertEqual(shown[0], "- yesterday: Jessica picked up the sword.")
        self.assertEqual(shown[1],
                         "- moments ago: Jessica handed Britney the sword.")

    def test_beside_what_is_true_now(self):
        ownership.claim(self.britney, self.sword)
        self.sword.move_to(self.britney, quiet=True)
        shown = memory.format_recalled(self.rows(), now=self.NOW)
        self.assertIn("Now: the sword is Britney's and carried by Britney.",
                      shown)

    def test_and_what_is_true_now_is_capped(self):
        from evennia import create_object
        from typeclasses.objects import Object

        rows = []
        for n in range(6):
            thing = create_object(Object, key=f"thing{n}", location=self.room1)
            rows.append({"content": "x", "timestamp": "",
                         "metadata": {"roles": {"direct": thing.id}}})
        state = memory.present_state(rows)
        self.assertEqual(state.count(" is "), memory.MOST_NOW)

    def test_just_now_reads_the_remembered_line(self):
        from world.npc_gen import _format_history

        self.assertEqual(
            _format_history([{"type": "action", "actor": "Jessica",
                              "text": "Jessica hands Britney the sword.",
                              "line": "Jessica handed Britney the sword."}]),
            "Jessica handed Britney the sword.")


@tag("unit")
class RecallLeavesOutWhatIsOnShow(SimpleTestCase):

    def test_by_what_it_says(self):
        rows = [{"id": "a", "content": "Jessica handed Britney the sword.",
                 "timestamp": "", "metadata": {}},
                {"id": "b", "content": "Jessica picked up the sword.",
                 "timestamp": "", "metadata": {}}]
        where = memory.Where("bank", "session")
        with mock.patch.object(memory, "available", return_value=True), \
                mock.patch.object(memory, "_recall_sync", return_value=rows):
            found = memory.recall_rows_sync(
                where, "sword", top_k=5,
                already_known=["Jessica handed Britney the sword."])
            strings = memory.recall_sync(where, "sword", top_k=5)
            by_cue = memory.recall_for_cues(where, ["sword"], rows=True)
        self.assertEqual([row["id"] for row in found], ["b"])
        self.assertEqual(strings, [rows[0]["content"], rows[1]["content"]])
        self.assertEqual([row["id"] for row in by_cue], ["a", "b"])
