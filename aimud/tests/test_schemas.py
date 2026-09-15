"""
The shapes finish tools will ask for, and the words they will send back.

Phase 4c of docs/generator-tool-loops.md: §4.1's shared schemas, the enum
cap, and §3.3's near-duplicate complaints. Nothing here uses them yet; they
are what the generators in phases 5 to 7 are built from, so they are held
still first.
"""

from django.test import SimpleTestCase, tag
from evennia.utils.test_resources import EvenniaTest

from world import (clothing, conditions, effects, gear, goals, kinds, pronouns,
                   relations, token_lists, traits, verbs, vocabulary)
from world import toolbox as tb

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


def every_schema(ctx=None):
    return {
        "effects": effects.schema(ctx),
        "conditions": conditions.schema(ctx),
        "goals": goals.schema(ctx),
        "item": clothing.spec_schema(ctx),
        "garment": clothing.spec_schema(ctx, worn=True),
        "word list": token_lists.schema(ctx),
        "pronoun set": pronouns.set_schema(ctx),
        "trait": traits.declaration_schema(ctx),
        "state": verbs.state_declaration_schema(ctx),
    }


@tag("unit")
class TheShapes(SimpleTestCase):

    def test_every_schema_stays_in_the_conservative_dialect(self):
        for name, schema in every_schema().items():
            self.assertEqual(set(_keys(schema)) & OUTSIDE_THE_DIALECT, set(),
                             name)

    def test_every_required_field_is_one_it_describes(self):
        for name, schema in every_schema().items():
            self.assertLessEqual(set(schema["required"]),
                                 set(schema["properties"]), name)

    def test_each_closed_field_is_closed_to_what_the_code_accepts(self):
        self.assertEqual(effects.schema()["properties"]["type"]["enum"],
                         sorted(effects.VOCABULARY))
        self.assertEqual(goals.schema()["properties"]["type"]["enum"],
                         list(goals.CONDITION_TYPES))
        self.assertEqual(
            clothing.spec_schema(worn=True)["properties"]["clothing_type"]["enum"],
            list(clothing.GARMENT_TYPES))
        # Never "" for "not a garment": Google refuses an empty enum member
        # and the whole call with it. Left out is said by leaving it out.
        self.assertNotIn(
            "", clothing.spec_schema()["properties"]["clothing_type"]["enum"])
        self.assertEqual(
            clothing.spec_schema()["properties"]["holds"]["items"]["enum"],
            list(kinds.PLACEMENT))
        self.assertLessEqual(set(gear.CONDITIONS), set(
            clothing.spec_schema()["properties"]["bonus_when"]["enum"]))
        self.assertEqual(
            traits.declaration_schema()["properties"]["trait_type"]["enum"],
            list(traits.TRAIT_TYPES))
        self.assertEqual(token_lists.schema()["properties"]["scope"]["enum"],
                         list(token_lists.SCOPES))
        self.assertEqual(goals.schema()["properties"]["preposition"]["enum"],
                         list(relations.PREPOSITIONS))
        self.assertEqual(set(pronouns.set_schema()["required"]),
                         set(pronouns.REQUIRED))

    def test_a_garment_must_say_what_sort_it_is(self):
        self.assertIn("clothing_type",
                      clothing.spec_schema(worn=True)["required"])
        self.assertNotIn("clothing_type", clothing.spec_schema()["required"])


@tag("unit")
class TheEnumCap(SimpleTestCase):

    def test_a_few_values_are_an_enum(self):
        field = tb.choice(["a", "b", "b", ""], "pick one")
        self.assertEqual(field["enum"], ["a", "b"])

    def test_too_many_are_left_open_and_say_where_to_look(self):
        field = tb.choice([f"trait_{n}" for n in range(tb.ENUM_MOST + 1)],
                          "The figure.", ask="list_traits")
        self.assertNotIn("enum", field)
        self.assertIn(f"There are {tb.ENUM_MOST + 1} to choose from",
                      field["description"])
        self.assertIn("list_traits", field["description"])

    def test_nothing_to_choose_from_is_simply_open(self):
        self.assertNotIn("enum", tb.choice([], "anything"))


class _World(EvenniaTest):

    def setUp(self):
        super().setUp()
        self.root = self.room1
        self.root.db.world_root = self.root
        self.root.db.is_world_root = True
        self.ctx = tb.ToolContext(world_root=self.root)


@tag("world")
class ShapesThatKnowTheirWorld(_World):

    def test_a_worlds_traits_close_the_trait_fields(self):
        traits.register(self.root, "swordsmanship", means="skill with a blade")
        for schema in (effects.schema(self.ctx), goals.schema(self.ctx),
                       conditions.schema(self.ctx)):
            self.assertIn("swordsmanship",
                          schema["properties"]["trait"]["enum"])

    def test_a_worlds_groups_are_offered_for_reuse(self):
        verbs.register_state(self.root, "tarnished", means="dulled",
                             group="shine")
        said = verbs.state_declaration_schema(self.ctx)["properties"]["group"]
        self.assertIn("shine", said["description"])


@tag("world")
class WordsThisWorldAlreadyHas(_World):

    def test_a_near_spelling_of_a_state(self):
        verbs.register_state(self.root, "open", means="not shut")
        self.assertEqual(verbs.near_duplicate_state(self.root, "opened"),
                         "open")

    def test_a_synonym_of_a_state(self):
        verbs.register_state(self.root, "closed", means="not open")
        self.assertEqual(verbs.near_duplicate_state(self.root, "shut"),
                         "closed")

    def test_a_new_word_is_not_a_duplicate_of_anything(self):
        verbs.register_state(self.root, "closed", means="not open")
        self.assertEqual(verbs.near_duplicate_state(self.root, "glowing"), "")
        self.assertEqual(verbs.near_duplicate_state(self.root, "closed"), "")

    def test_a_near_spelling_of_a_trait(self):
        traits.register(self.root, "stamina", means="how long one lasts")
        self.assertEqual(traits.near_duplicate(self.root, "stam"), "stamina")
        self.assertEqual(traits.near_duplicate(self.root, "cunning"), "")

    def test_a_word_list_under_another_number(self):
        token_lists.register(self.root, "smells", {
            "means": "what a place smells of", "entries": ["tar"]})
        self.assertEqual(token_lists.near_duplicate(self.root, "smell"),
                         "smells")

    def test_a_pronoun_set_already_kept(self):
        self.assertEqual(pronouns.near_duplicate(self.root,
                                                 {"subject": "she"}), "she")
        self.assertEqual(pronouns.near_duplicate(self.root,
                                                 {"subject": "xe"}), "")

    def test_a_whole_reply_is_told_what_it_duplicates(self):
        verbs.register_state(self.root, "closed", means="not open",
                             group="openness")
        traits.register(self.root, "stamina", means="how long one lasts")
        said = vocabulary.near_duplicates(
            self.root,
            new_states=[{"slug": "shut"}],
            new_traits=[{"slug": "stam"}],
            new_pronoun_set={"subject": "they"})
        joined = " ".join(said)
        self.assertIn("already has the state 'closed' (group: openness)",
                      joined)
        self.assertIn("already measures 'stamina'", joined)
        self.assertIn("('they')", joined)

    def test_a_trait_named_like_a_state_is_refused(self):
        verbs.register_state(self.root, "warm", means="comfortably hot")
        said = vocabulary.near_duplicates(self.root,
                                          new_traits=[{"slug": "warm"}])
        self.assertTrue(any("already a state" in line for line in said), said)

    def test_nothing_to_say_about_new_words(self):
        self.assertEqual(vocabulary.near_duplicates(
            self.root, new_states=[{"slug": "glowing"}],
            new_traits=[{"slug": "cunning"}]), [])
