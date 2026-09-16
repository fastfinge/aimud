"""
Schemas every provider will accept.

The first soak of the tool loops lost every item, every character and every
verb declaration for two days. Each call failed in a third of a second with
"Provider returned error" and no tool ever chosen, while the room generators
went through on the very same model.

What the failing schemas had in common was an enum offering `""` to mean
"leave this out". Google's validation refuses an empty member and the call
with it. Nothing in the game said so, and nothing could have: the schemas were
tested against what this game accepts, never against what a provider will
take.

So that shape is refused here instead, over every tool the game can build --
including the ones that fill an enum from a world's own names, where a blank
is a data question rather than a spelling one.
"""

from django.test import SimpleTestCase, tag
from evennia import create_object

from tests.base import GameTest
from world import toolbox as tb


def _enums(schema, path=""):
    """Every enum in a schema, as (where it is, what it offers)."""
    if isinstance(schema, dict):
        for key, value in schema.items():
            if key == "enum":
                yield path, value
            else:
                yield from _enums(value, f"{path}.{key}" if path else key)
    elif isinstance(schema, list):
        for index, value in enumerate(schema):
            yield from _enums(value, f"{path}[{index}]")


@tag("unit")
class WhatIsDroppedOnTheWayOut(SimpleTestCase):

    def test_an_empty_member_is_dropped(self):
        cleaned = tb.portable({"type": "string", "enum": ["hat", "", "  "]})
        self.assertEqual(cleaned["enum"], ["hat"])

    def test_an_enum_of_nothing_leaves_the_field_open(self):
        cleaned = tb.portable({"type": "string", "enum": ["", " "]})
        self.assertNotIn("enum", cleaned)
        self.assertEqual(cleaned["type"], "string")

    def test_it_reaches_every_depth(self):
        cleaned = tb.portable({"properties": {"worn": {"items": {
            "properties": {"kind": {"enum": ["coat", ""]}}}}}})
        self.assertEqual(
            cleaned["properties"]["worn"]["items"]["properties"]["kind"]["enum"],
            ["coat"])

    def test_and_leaves_everything_else_exactly_as_it_was(self):
        schema = {"type": "object", "required": ["name"],
                  "properties": {"name": {"type": "string", "enum": ["a"]}}}
        self.assertEqual(tb.portable(schema), schema)

    def test_a_tool_is_sanitised_as_it_is_handed_over(self):
        """The one choke point: whatever a tool asks for goes through here."""
        tool = tb.Tool("t", "", {"type": "object", "properties": {
            "sense": {"type": "string", "enum": ["chest.n.02", ""]}}})
        offered = tool.schema(tb.ToolContext())["function"]["parameters"]
        self.assertEqual(offered["properties"]["sense"]["enum"],
                         ["chest.n.02"])


@tag("world")
class EveryToolTheGameOffers(GameTest):
    """
    Built for real, from a world with things and people in it, because the
    enums that matter are the ones filled in from what is standing about.
    """

    loose_objects = 1

    def setUp(self):
        super().setUp()
        from typeclasses.npcs import NPC

        self.root = self.room1
        self.root.db.world_root = self.root
        self.root.db.is_world_root = True
        self.root.db.room_title = "Front Hall"
        self.obj1.db.kinds = ["chest"]
        self.npc = create_object(NPC, key="Melia", location=self.root)

    def tools(self):
        from world import (actions, fact_gen, item_gen, lookups, npc_gen,
                           quest_gen, rule_gen, suggest, verb_gen, worldgen)

        offered = [("world", "everywhere", {"world": True})]
        found = [
            actions.declaration_tool("break"),
            item_gen.item_tool("chest"),
            worldgen.contents_tool("A plain hall."),
            worldgen.description_tool(),
            worldgen.plan_world_tool(),
            worldgen.area_tool(self.root, "hall"),
            worldgen.first_name_tool({"zones": [{"name": "Hall"}]}),
            worldgen.name_tool({"Front Hall"}, self.root, self.root, None,
                               "north"),
            npc_gen.character_tool({"Melia"}),
            npc_gen.dressing_tool(),
            quest_gen.quest_tool(),
            quest_gen.goal_tool(self.npc),
            rule_gen.rules_tool("power", offered, []),
            verb_gen.narration_tool({"direct": self.obj1}, self.char1),
            suggest.verdicts_tool([{"id": "r1"}]),
            fact_gen.facts_tool(),
        ]
        return found + list(lookups.all_tools().values())

    def test_no_enum_offers_nothing(self):
        ctx = tb.ToolContext(world_root=self.root, room=self.root,
                             actor=self.char1, bound={"direct": self.obj1})
        for tool in self.tools():
            schema = tool.schema(ctx)
            for where, offered in _enums(schema):
                self.assertTrue(
                    offered, f"{tool.name}: {where} offers an empty enum")
                for member in offered:
                    self.assertTrue(
                        str(member).strip(),
                        f"{tool.name}: {where} offers an empty member")

    def test_an_npcs_own_tools_too(self):
        """
        These fill their enums from the room: the things here, the people
        here, the ways out. A world with a nameless thing in it would have
        broken every character's turn.
        """
        from world import npc_gen

        box = npc_gen._toolbox_for(self.npc, self.root)
        for schema in box.schemas:
            for where, offered in _enums(schema):
                name = schema["function"]["name"]
                self.assertTrue(offered,
                                f"{name}: {where} offers an empty enum")
                for member in offered:
                    self.assertTrue(
                        str(member).strip(),
                        f"{name}: {where} offers an empty member")


@tag("world")
class WhatAModelSendsBack(GameTest):
    """
    "Leave it out" is said by leaving it out now, but a model taught by every
    other schema it has read sends "" instead, and a round spent refusing that
    is a round spent on nothing.
    """

    def test_an_optional_field_given_nothing_is_a_field_nobody_filled_in(self):
        parameters = tb.params(
            {"name": {"type": "string"},
             "clothing_type": {"type": "string", "enum": ["hat", "top"]}},
            ["name"])
        self.assertEqual(
            tb.problems_with({"name": "coat", "clothing_type": ""},
                             parameters), [])

    def test_but_a_required_one_is_still_missing(self):
        parameters = tb.params({"name": {"type": "string"}}, ["name"])
        self.assertEqual(tb.problems_with({"name": ""}, parameters),
                         ["name is required"])

    def test_and_a_real_value_outside_the_enum_is_still_wrong(self):
        parameters = tb.params(
            {"clothing_type": {"type": "string", "enum": ["hat"]}}, [])
        self.assertTrue(tb.problems_with({"clothing_type": "sombrero"},
                                         parameters))
