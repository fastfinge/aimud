"""
A room's contents on a finish tool, and the wants nothing in the world can
satisfy: the last part of phase 6 of docs/generator-tool-loops.md.

The phase's finish line is here: somebody wants a thing that exists nowhere,
a room is furnished while they play, and the thing it makes is named in the
words the want accepts, so going there and taking it is enough.
"""

from unittest import mock

from django.test import tag
from evennia import create_object
from evennia.utils.test_resources import EvenniaTest

from tests.support import (FakeSponsor, finishing, immediately, replying,
                           tool_call, tool_reply)
from world import goals, planner, worldgen

ORE = {"name": "Raw Ore", "description": "A lump of raw ore, streaked grey.",
       "kind": "ore", "takeable": True}


def _results(recorder, index):
    return "\n".join(message["content"]
                     for message in recorder.tool_results(index))


class _World(EvenniaTest):

    def setUp(self):
        super().setUp()
        self.root = self.room1
        self.root.db.world_root = self.root
        self.root.db.is_world_root = True
        self.mine = self.room2
        self.mine.db.world_root = self.root
        self.mine.db.is_ai_room = True
        self.mine.db.room_type = "mine"
        self.mine.db.room_title = "Old Mine"
        self.mine.db.desc = "Timbers hold up a low rock ceiling."
        self.mine.tags.add(str(self.root.id), category="ai_world")

    def furnish(self, *replies):
        with immediately(), replying(*replies) as recorder:
            worldgen.populate_room(FakeSponsor(), self.mine)
        return recorder


@tag("world")
class FindingWhatNobodyMade(_World):

    def test_a_want_for_a_thing_nowhere_is_met_by_exploring(self):
        goal = [{"type": "holds", "object": "raw ore"}]
        self.char1.db.goal = goal
        self.assertEqual(planner.blocker(self.char1, self.root, goal[0])[0],
                         planner.MISSING_THING)

        with mock.patch("world.commonsense.available", return_value=False):
            recorder = self.furnish(finishing(furnish_room={
                "items": [ORE], "wants_npc": False}))
        self.assertIn("named so that the name contains 'raw ore'",
                      recorder.sent(0))

        ore = next(obj for obj in self.mine.contents if obj.key == "Raw Ore")
        self.assertEqual([want for want in goals.blocked_wants(self.root)
                          if want["who"] is self.char1], [])
        ore.move_to(self.char1, quiet=True)
        self.assertTrue(goals.progress(goal, self.char1, self.root)[0][0])

    def test_with_a_corpus_a_thing_is_hinted_only_where_it_is_found(self):
        self.char1.db.goal = [{"type": "holds", "object": "raw ore"}]
        with mock.patch("world.commonsense.available", return_value=True), \
                mock.patch("world.commonsense.forward",
                           return_value=["mine", "quarry"]):
            here = worldgen.contents_hints(self.root, self.mine)
            self.mine.db.room_type = "kitchen"
            self.mine.db.room_title = "Scullery"
            elsewhere = worldgen.contents_hints(self.root, self.mine)
        self.assertEqual(len(here), 1)
        self.assertEqual(elsewhere, [])

    def test_never_in_the_room_of_whoever_wants_it(self):
        from typeclasses.npcs import NPC

        bram = create_object(NPC, key="Bram", location=self.mine)
        bram.db.goal = [{"type": "holds", "object": "raw ore"}]
        with mock.patch("world.commonsense.available", return_value=False):
            self.assertEqual(worldgen.contents_hints(self.root, self.mine), [])
            self.assertEqual(len(worldgen.contents_hints(self.root,
                                                         self.root)), 1)

    def test_a_room_nobody_built_is_hinted_to_the_namer(self):
        self.char1.db.goal = [{"type": "in_room", "room": "Boiler Room"}]
        self.root.db.room_title = "Front Hall"
        named = []
        with immediately(), replying(finishing(name_room={
                "name": "Boiler Room", "category": "circulation",
                "zone": "Basement"})) as recorder:
            worldgen._generate_name(FakeSponsor(), "a school", "(nothing)",
                                    self.root, "north", "",
                                    on_success=named.append,
                                    on_error=self.fail)
        self.assertIn("a room whose name contains 'Boiler Room', which nobody "
                      "has built", recorder.sent(0))
        self.assertEqual(named[0]["name"], "Boiler Room")


@tag("world")
class FurnishingARoom(_World):

    def test_a_thing_the_description_already_has_is_sent_back(self):
        lamp = {"name": "Brass Lamp", "description": "A squat brass lamp.",
                "kind": "lamp", "takeable": True}
        timbers = dict(lamp, name="Loose Timbers", kind="timbers")
        recorder = self.furnish(
            tool_reply(tool_call("furnish_room", items=[timbers],
                                 wants_npc=False)),
            tool_reply(tool_call("furnish_room", items=[lamp],
                                 wants_npc=False)))
        self.assertIn("already has one", _results(recorder, 1))
        keys = [obj.key for obj in self.mine.contents]
        self.assertIn("Brass Lamp", keys)
        self.assertNotIn("Loose Timbers", keys)

    def test_an_empty_room_is_a_real_answer(self):
        before = len(self.mine.contents)
        recorder = self.furnish(finishing(furnish_room={
            "items": [], "wants_npc": False}))
        self.assertEqual(recorder.count, 1)
        self.assertEqual(len(self.mine.contents), before)
