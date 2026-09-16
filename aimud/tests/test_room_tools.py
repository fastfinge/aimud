"""
Rooms on finish tools: the second part of phase 6 of
docs/generator-tool-loops.md.

The world plan, an area's plan, a room's name and its description are tool
loops now. What the naming checks used to say in a conversation built by hand
is the tool's result, and what used to be dropped after a description came
back -- a trait nothing measures, a word list nobody keeps -- is sent back.
"""

from unittest import mock

from django.test import tag

from tests.base import GameTest
from tests.support import (FakeSponsor, finishing, immediately, replying,
                           tool_call, tool_reply)
from world import toolbox as tb
from world import worldgen, zones


def _offered(recorder, index, name):
    for schema in recorder.tools(index) or ():
        if schema["function"]["name"] == name:
            return schema["function"]
    return None


def _results(recorder, index):
    return "\n".join(message["content"]
                     for message in recorder.tool_results(index))


def _zone(name, types):
    return {"name": name, "purpose": "things happen", "room_types": types,
            "room_budget": 4}


class _World(GameTest):

    def setUp(self):
        super().setUp()
        self.root = self.room1
        self.root.db.is_world_root = True
        self.root.db.world_root = self.root
        self.root.db.room_title = "Front Hall"
        self.root.db.room_category = "circulation"


@tag("world")
class PlanningAWorld(_World):

    def test_a_singleton_no_zone_has_is_sent_back(self):
        zones_given = [_zone("Hall", ["hall"]), _zone("Wing", ["classroom"]),
                       _zone("Yard", ["yard"])]
        planned = []
        with immediately(), replying(
                tool_reply(tool_call("plan_world", zones=zones_given,
                                     singleton_types=["gymnasium"])),
                tool_reply(tool_call("plan_world", zones=zones_given,
                                     singleton_types=["yard"]))) as recorder:
            worldgen._generate_plan(FakeSponsor(), "a school", "",
                                    planned.append)
        self.assertIn("gymnasium", _results(recorder, 1))
        self.assertEqual(planned[0]["singleton_types"], ["yard"])
        self.assertEqual(len(planned[0]["zones"]), 3)

    def test_a_failed_plan_is_no_plan(self):
        from world import llm

        planned = []
        with immediately(), replying(llm.LLMError("no route")):
            worldgen._generate_plan(FakeSponsor(), "a school", "",
                                    planned.append)
        self.assertEqual(planned, [{}])

    def test_one_smaller_area_is_not_a_division(self):
        tool = worldgen.area_tool(self.root, "hall")
        said = []
        tool.handler(tb.ToolContext(world_root=self.root),
                     {"purpose": "p", "room_types": ["hall"], "room_budget": 4,
                      "zones": [_zone("Wing", ["classroom"])]}, said.append)
        self.assertIsInstance(said[0], tb.Complaint)
        self.assertIn("not a division", said[0].text)

    def test_an_area_as_deep_as_areas_go_is_not_offered_smaller_ones(self):
        tool = worldgen.area_tool(self.root, "hall")
        ctx = tb.ToolContext(world_root=self.root)
        with mock.patch("world.zones.depth", return_value=0):
            self.assertIn("zones", tool.parameters(ctx)["properties"])
        with mock.patch("world.zones.depth", return_value=zones.MAX_DEPTH):
            self.assertNotIn("zones", tool.parameters(ctx)["properties"])


@tag("world")
class NamingARoom(_World):

    def name(self, *replies):
        named, failed = [], []
        with immediately(), replying(*replies) as recorder:
            worldgen._generate_name(FakeSponsor(), "a school", "(nothing)",
                                    self.root, "north", "",
                                    on_success=named.append,
                                    on_error=failed.append)
        self.assertEqual(failed, [])
        return (named[0] if named else None), recorder

    def test_a_repeated_name_is_sent_back_and_the_second_kept(self):
        room = {"name": "Boiler Room", "type": "boiler_room",
                "category": "circulation", "zone": "Basement"}
        named, recorder = self.name(
            tool_reply(tool_call("name_room", **dict(room, name="Front Hall"))),
            tool_reply(tool_call("name_room", **room)))
        self.assertIn("repeats a room that already exists", _results(recorder, 1))
        self.assertEqual(named["name"], "Boiler Room")

    def test_the_way_back_is_not_an_exit_on_offer(self):
        _named, recorder = self.name(finishing(name_room={
            "name": "Boiler Room", "category": "circulation",
            "zone": "Basement"}))
        exits = _offered(recorder, 0, "name_room")["parameters"][
            "properties"]["exits"]["items"]["properties"]["name"]["enum"]
        self.assertNotIn("south", exits)
        self.assertIn("north", exits)

    def test_a_destination_is_not_offered_beside_a_destination(self):
        self.root.db.room_category = "destination"
        _named, recorder = self.name(finishing(name_room={
            "name": "Boiler Room", "category": "circulation",
            "zone": "Basement"}))
        category = _offered(recorder, 0, "name_room")["parameters"][
            "properties"]["category"]["enum"]
        self.assertNotIn("destination", category)

    def test_rounds_out_takes_the_last_name_as_it_stands(self):
        named, recorder = self.name(finishing(name_room={
            "name": "Front Hall", "category": "circulation",
            "zone": "Basement"}))
        self.assertEqual(recorder.count, worldgen.NAME_ROUNDS)
        self.assertEqual(named["name"], "Front Hall")


@tag("world")
class DescribingARoom(_World):

    def describe(self, *replies):
        got, failed = [], []
        with immediately(), replying(*replies) as recorder:
            worldgen._generate_description(
                FakeSponsor(), "a school", "", "(nothing)", "Boiler Room",
                "boiler_room", "circulation",
                on_success=lambda *parts: got.append(parts),
                on_error=failed.append, world_root=self.root)
        self.assertEqual(failed, [])
        return (got[0] if got else None), recorder

    def test_a_trait_nothing_measures_is_sent_back(self):
        got, recorder = self.describe(
            tool_reply(tool_call("describe_room", description="Hot pipes.",
                                 trait_bonuses={"zorbitude": 2})),
            tool_reply(tool_call("describe_room", description="Hot pipes.")))
        self.assertIn("zorbitude", _results(recorder, 1))
        self.assertEqual(got, ("Hot pipes.", {}, []))

    def test_darkness_is_given_as_nothing_rather_than_as_nought(self):
        said = worldgen.description_complaints(
            {"description": "A dark cellar.", "trait_bonuses": {"light": 0}},
            self.root)
        self.assertTrue(any("leave light out" in line for line in said), said)

    def test_a_slot_no_list_answers_is_sent_back(self):
        declared = [{"name": "hiss", "means": "what old pipes sound like",
                     "entries": ["a hiss", "a knock"]}]
        got, recorder = self.describe(
            tool_reply(tool_call("describe_room",
                                 description="The pipes give {hiss}.")),
            tool_reply(tool_call("describe_room",
                                 description="The pipes give {hiss}.",
                                 new_token_lists=declared)))
        self.assertIn("{hiss}", _results(recorder, 1))
        self.assertEqual(got[2], declared)

    def test_a_list_that_can_never_finish_is_sent_back(self):
        said = worldgen.description_complaints(
            {"description": "It goes {echo}.",
             "new_token_lists": [{"name": "echo", "means": "an echo",
                                  "entries": ["{echo} again"]}]}, self.root)
        self.assertTrue(any("never finish" in line for line in said), said)

    def test_the_word_lists_are_looked_up_rather_than_pasted_in(self):
        from world import token_lists

        token_lists.register(self.root, "drip", {
            "means": "what water does in a cellar", "entries": ["a drip"]})
        _got, recorder = self.describe(finishing(describe_room={
            "description": "Hot pipes."}))
        self.assertIsNotNone(_offered(recorder, 0, "list_word_lists"))
        self.assertNotIn("what water does in a cellar", recorder.sent(0))
