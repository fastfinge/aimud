"""
Items on finish tools: the first part of phase 6 of
docs/generator-tool-loops.md.

Whether a thing could be here, whether it can be picked up, and what it is are
three tool loops now. What was silently resolved or dropped -- a name carrying
a condition, a sense that contradicts the thing, a word list nothing keeps, a
second word for a state the world has -- is sent back to be put right.
"""

from unittest import mock

from django.test import tag

from tests.base import GameTest
from tests.support import (FakeSponsor, finishing, immediately, replying,
                           tool_call, tool_reply)
from world import item_gen, token_lists, verbs


def _offered(recorder, index, name):
    for schema in recorder.tools(index) or ():
        if schema["function"]["name"] == name:
            return schema["function"]
    return None


def _results(recorder, index):
    return "\n".join(message["content"]
                     for message in recorder.tool_results(index))


#: A plain item, as a model making one would send it.
LAMP = {"name": "Brass Lamp", "description": "A squat brass lamp.",
        "kind": "lamp", "takeable": True}


class _Room(GameTest):

    def setUp(self):
        super().setUp()
        self.root = self.room1
        self.root.db.is_world_root = True
        self.root.db.world_root = self.root

    def make(self, phrase, *replies):
        made, failed = [], []
        with immediately(), replying(*replies) as recorder:
            item_gen.generate_item(FakeSponsor(), self.root, phrase,
                                   on_success=made.append,
                                   on_error=failed.append)
        return (made[0] if made else None), failed, recorder


@tag("world")
class Judging(_Room):
    loose_objects = 1

    def test_whether_a_thing_could_be_here(self):
        said = []
        with immediately(), replying(finishing(judge_existence={
                "valid": False, "reason": "not in a cellar"})) as recorder:
            item_gen.validate_object_existence(
                FakeSponsor(), self.root, "a spaceship",
                on_valid=lambda r: said.append(("valid", r)),
                on_invalid=lambda r: said.append(("invalid", r)),
                on_error=self.fail)
        self.assertEqual(said, [("invalid", "not in a cellar")])
        self.assertIsNotNone(_offered(recorder, 0, "judge_existence"))

    def test_whether_it_can_be_picked_up(self):
        said = []
        with immediately(), replying(finishing(judge_takeable={
                "valid": True, "reason": "it is loose"})):
            item_gen.validate_object_takeable(
                FakeSponsor(), self.root, self.obj1,
                on_valid=lambda r: said.append(("valid", r)),
                on_invalid=lambda r: said.append(("invalid", r)),
                on_error=self.fail)
        self.assertEqual(said, [("valid", "it is loose")])

    def test_no_answer_is_an_error_and_not_a_guess(self):
        errors = []
        with immediately(), replying("I think probably yes?"):
            item_gen.validate_object_existence(
                FakeSponsor(), self.root, "a lamp",
                on_valid=self.fail, on_invalid=self.fail,
                on_error=errors.append)
        self.assertEqual(len(errors), 1)


@tag("world")
class MakingAnItem(_Room):

    def test_an_item_is_made_and_answers_to_what_was_asked_for(self):
        item, failed, _ = self.make("old lamp", finishing(make_item=LAMP))
        self.assertEqual(failed, [])
        self.assertEqual(item.key, "Brass Lamp")
        self.assertIn("old lamp", item.aliases.all())

    def test_a_name_carrying_a_condition_is_sent_back(self):
        verbs.register_state(self.root, "dusty", means="covered in dust")
        item, _failed, recorder = self.make(
            "lamp",
            tool_reply(tool_call("make_item", **dict(LAMP, name="Dusty Lamp"))),
            tool_reply(tool_call("make_item", **dict(LAMP, states=["dusty"]))))
        self.assertIn("dusty is a condition", _results(recorder, 1))
        self.assertEqual(item.key, "Brass Lamp")
        self.assertIn("dusty", verbs.states(item))

    def test_a_second_word_for_a_state_is_sent_back(self):
        verbs.register_state(self.root, "closed", means="not open")
        _item, _failed, recorder = self.make(
            "lamp",
            tool_reply(tool_call("make_item", **dict(LAMP, states=["shut"]))),
            tool_reply(tool_call("make_item", **dict(LAMP, states=["closed"]))))
        self.assertIn("already has the state 'closed'", _results(recorder, 1))
        self.assertNotIn("shut", verbs.vocabulary(self.root))

    def test_a_word_list_nothing_keeps_is_sent_back(self):
        smelly = dict(LAMP, description="A brass lamp smelling of {smell}.")
        declared = dict(smelly, new_token_lists=[{
            "name": "smell", "means": "what an old lamp smells of",
            "entries": ["oil", "soot"]}])
        item, _failed, recorder = self.make(
            "lamp", tool_reply(tool_call("make_item", **smelly)),
            tool_reply(tool_call("make_item", **declared)))
        self.assertIn("{smell}", _results(recorder, 1))
        self.assertIsNotNone(token_lists.get(self.root, "smell"))
        self.assertIsNotNone(item)

    def test_rounds_out_makes_the_last_item_as_it_stands(self):
        verbs.register_state(self.root, "dusty", means="covered in dust")
        item, failed, recorder = self.make(
            "lamp", finishing(make_item=dict(LAMP, name="Dusty Lamp")))
        self.assertEqual(recorder.count, item_gen.ITEM_ROUNDS)
        self.assertEqual(failed, [])
        self.assertEqual(item.key, "Dusty Lamp")

    def test_the_registers_are_looked_up_rather_than_pasted_in(self):
        token_lists.register(self.root, "patina", {
            "means": "the colour old brass has gone", "entries": ["green"]})
        _item, _failed, recorder = self.make("lamp", finishing(make_item=LAMP))
        self.assertIsNotNone(_offered(recorder, 0, "list_word_lists"))
        self.assertNotIn("patina", recorder.sent(0))

    def test_a_word_whose_senses_disagree_is_offered_them(self):
        from world import lexicon

        if not lexicon.needs_sense_choice("chest"):
            self.skipTest("no dictionary")
        _item, _failed, recorder = self.make(
            "chest", finishing(make_item=dict(LAMP, name="Oak Chest",
                                              kind="chest")))
        sense = _offered(recorder, 0, "make_item")["parameters"][
            "properties"]["sense"]
        self.assertNotIn("", sense["enum"])
        self.assertIn("chest.n.02", sense["enum"])
        self.assertIn("several different kinds of thing", recorder.sent(0))

    def test_a_bonus_to_a_trait_nothing_measures_is_sent_back(self):
        said = item_gen.item_complaints(
            dict(LAMP, trait_bonuses={"zorbitude": 1}), self.root)
        self.assertTrue(any("zorbitude" in line for line in said), said)

    def test_a_sense_that_contradicts_the_thing_is_sent_back(self):
        said = item_gen.item_complaints(
            dict(LAMP, sense="structure.n.01", takeable=True), self.root)
        self.assertTrue(any("structure" in line for line in said), said)


@tag("world")
class WhatTheItemMakerIsTold(_Room):

    def test_unused_words_in_a_familiar_group_are_a_hint(self):
        # Invented words, so no seeded group or dictionary guess moves them.
        verbs.register_state(self.root, "zorbled", means="zorbed",
                             group="zorb")
        verbs.register_state(self.root, "blarfed", means="blarfed",
                             group="zorb")
        self.assertEqual(verbs.group_of(self.root, "blarfed"),
                         verbs.group_of(self.root, "zorbled"))
        with mock.patch("world.kinds.states_of", return_value={"zorbled"}), \
                mock.patch("world.rulecheck.scan",
                           return_value={"dead_vocabulary": ["blarfed"]}):
            said = item_gen._state_hints(self.root, ["lamp"])
        self.assertIn("have been in before: zorbled.", said)
        self.assertIn("used by nothing yet: blarfed.", said)

    def test_nothing_to_say_about_a_sort_of_thing_never_seen(self):
        self.assertEqual(item_gen._state_hints(self.root, ["lamp"]), "")
