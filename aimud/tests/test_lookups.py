"""
Every lookup a model may be offered, asked the way a model asks.

Phase 4 of docs/generator-tool-loops.md, §5. Each lookup is defined beside the
register it reads; `world.lookups` gathers them. What is held still here is
that every tool in §5 exists, speaks the conservative schema dialect, answers
from what the world holds, and is not offered where it cannot answer.
"""

from unittest import mock

from django.test import SimpleTestCase, tag
from evennia import create_object

from tests.base import GameTest
from tests.support import immediately, tool_call
from world import actions, lookups, token_lists, traits, verbs, zones
from world import rulebooks as R
from world import toolbox as tb

#: Every lookup §5 of the plan names.
PLANNED = {
    "list_traits", "show_trait", "list_pronoun_sets", "list_word_lists",
    "show_word_list", "try_text", "list_states", "show_state",
    "list_state_groups", "lexicon_senses", "lexicon_define",
    "lexicon_ancestors", "lexicon_hyponyms", "lexicon_parts", "verb_ancestors",
    "commonsense", "verb_info", "list_rules", "show_rule", "kind_info",
    "examine", "name_taken", "list_zones", "zone_info", "find_rooms",
    "list_known_verbs", "recall", "world_faults",
}

#: What the conservative dialect leaves out. See the plan, §4.1.
OUTSIDE_THE_DIALECT = {"oneOf", "anyOf", "allOf", "pattern", "maxLength",
                       "minLength", "format", "$ref"}


def _keys(value):
    if isinstance(value, dict):
        for key, inner in value.items():
            yield key
            yield from _keys(inner)
    elif isinstance(value, list):
        for inner in value:
            yield from _keys(inner)


@tag("unit")
class TheRegistry(SimpleTestCase):

    def test_every_planned_lookup_is_there(self):
        self.assertEqual(PLANNED - set(lookups.all_tools()), set())

    def test_every_lookup_looks(self):
        for name, tool in lookups.all_tools().items():
            self.assertTrue(tool.looks, name)

    def test_every_schema_stays_in_the_conservative_dialect(self):
        ctx = tb.ToolContext()
        for name, tool in lookups.all_tools().items():
            schema = tool.schema(ctx)
            self.assertEqual(set(_keys(schema)) & OUTSIDE_THE_DIALECT, set(),
                             name)

    def test_named_skips_what_does_not_exist(self):
        self.assertEqual([tool.name for tool in
                          lookups.named("list_traits", "nonsense", "find_rooms")],
                         ["list_traits", "find_rooms"])


@tag("unit")
class Paging(SimpleTestCase):

    def test_a_page_says_where_it_is_and_how_to_see_more(self):
        said = tb.paged(["apple", "pear", "plum"], {"limit": 2})
        self.assertIn("3 entries; showing 1 to 2", said)
        self.assertIn("offset=2", said)

    def test_a_query_filters(self):
        said = tb.paged(["apple", "pear", "plum"], {"query": "p"}, "fruit")
        self.assertIn("3 fruit matching 'p'", said)
        self.assertNotIn("offset=", said)

    def test_nothing_matching_says_so(self):
        self.assertIn("No fruit matching 'kiwi'",
                      tb.paged(["apple"], {"query": "kiwi"}, "fruit"))


@tag("world")
class AskingEachOne(GameTest):
    loose_objects = 1

    def setUp(self):
        super().setUp()
        self.root = self.room1
        self.root.db.world_root = self.root
        self.root.db.is_world_root = True
        self.root.db.room_title = "Harbour Office"

    def ask(self, tool, **args):
        # `tool`, not `name`: several lookups take an argument called name.
        found = lookups.all_tools()[tool]
        box = tb.Toolbox([found], tb.ToolContext(
            world_root=self.root, room=self.room1, actor=self.char1))
        got = []
        with immediately():
            box.run(tool_call(tool, **args), got.append)
        return str(got[0]) if got else ""

    def test_traits(self):
        traits.register(self.root, "stamina", means="effort left",
                        trait_type="gauge", base=100)
        self.assertIn("stamina (gauge): effort left",
                      self.ask("list_traits", query="stam"))
        self.assertIn("base: 100", self.ask("show_trait", slug="stamina"))
        self.assertIn("keeps no trait", self.ask("show_trait", slug="mana"))

    def test_pronoun_sets(self):
        self.assertIn("she/her/hers", self.ask("list_pronoun_sets"))

    def test_word_lists_and_trying_a_description(self):
        token_lists.register(self.root, "smell", {
            "means": "what a place smells of", "entries": ["tar", "brine"]})
        self.assertIn("{smell}", self.ask("list_word_lists"))
        self.assertIn("brine", self.ask("show_word_list", name="smell"))
        tried = self.ask("try_text", text="It smells of {smell} and {noise}.")
        self.assertIn("That comes to:", tried)
        self.assertIn("{noise}", tried.split("\n", 1)[1])

    def test_states_and_their_groups(self):
        verbs.register_state(self.root, "tarnished", means="dulled with age",
                             group="shine")
        self.assertIn("tarnished: dulled with age",
                      self.ask("list_states", query="tarn"))
        self.assertIn("group: shine", self.ask("show_state", slug="tarnished"))
        self.assertIn("shine: tarnished", self.ask("list_state_groups",
                                                   query="shine"))

    def test_the_dictionary(self):
        self.assertIn("chest.n.02", self.ask("lexicon_senses", word="chest"))
        self.assertIn("box", self.ask("lexicon_define", sense="chest.n.02"))
        self.assertIn("container.n.01",
                      self.ask("lexicon_ancestors", sense="chest.n.02"))
        self.assertIn("Sorts of sword",
                      self.ask("lexicon_hyponyms", sense="sword.n.01"))
        self.assertIn("hilt", self.ask("lexicon_parts", sense="sword.n.01"))
        self.assertTrue(self.ask("verb_ancestors", verb="pry"))

    def test_the_second_lexicon_only_when_it_is_here(self):
        ctx = tb.ToolContext(world_root=self.root)
        tool = lookups.all_tools()["commonsense"]
        with mock.patch("world.commonsense.available", return_value=False):
            self.assertFalse(tool.offered(ctx))
        with mock.patch("world.commonsense.available", return_value=True), \
                mock.patch("world.commonsense.forward",
                           return_value=["mine", "quarry"]):
            self.assertIn("mine, quarry", self.ask("commonsense", word="ore",
                                                   relation="found_at"))

    def test_a_verb_and_its_rules(self):
        R.add(self.root, R.blank(action="launch", phase=R.CHECK,
                                 name="a ship launches only under power"))
        said = self.ask("verb_info", verb="launch")
        self.assertIn("a ship launches only under power", said)
        self.assertIn("handles this verb", self.ask("verb_info", verb="look"))
        listed = self.ask("list_rules", action="launch")
        self.assertIn("a ship launches only under power", listed)
        rule_id = listed.split("\n")[1].split(" ", 1)[0]
        self.assertIn('"phase"', self.ask("show_rule", id=rule_id))

    def test_a_sort_of_thing(self):
        self.assertIn("weapon.n.01", self.ask("kind_info", kind="sword.n.01"))

    def test_examining_a_thing(self):
        said = self.ask("examine", name=self.obj1.key)
        self.assertIn(self.obj1.key, said)
        self.assertIn("belongs to nobody", said)
        self.assertIn("nothing called", self.ask("examine", name="unicorn"))

    def test_a_name_that_is_taken_and_one_that_is_free(self):
        create_object("typeclasses.npcs.NPC", key="Yuna Choi",
                      location=self.room1)
        self.assertIn("too close", self.ask("name_taken", name="Yuna Park"))
        self.assertIn("is free", self.ask("name_taken", name="Mira Holt"))

    def test_areas(self):
        zones.register(self.root, "Harbour", purpose="where the ships tie up")
        self.assertIn("where the ships tie up", self.ask("list_zones"))
        self.assertIn("where the ships tie up",
                      self.ask("zone_info", zone="Harbour"))

    def test_rooms(self):
        self.assertIn("Harbour Office", self.ask("find_rooms"))

    def test_known_verbs(self):
        self.root.db.verb_rules = {"polish#thing": {"valid": True}}
        actions.declare(self.root, "launch", applies_to=[])
        said = self.ask("list_known_verbs")
        self.assertIn("polish", said)
        self.assertIn("launch", said)

    def test_remembering(self):
        with mock.patch("world.memory.available", return_value=True), \
                mock.patch("world.memory.where_for", return_value="bank"), \
                mock.patch("world.memory.recall_rows_sync",
                           return_value=[{"content": "Bram owes me a favour"}]):
            self.assertIn("Bram owes me a favour",
                          self.ask("recall", query="Bram"))

    def test_the_worlds_faults(self):
        self.assertIn("What", self.ask("world_faults"))
        self.assertTrue(self.ask("world_faults", verb="close"))
