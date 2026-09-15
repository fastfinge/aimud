"""
Conditions that are words, never letters.

From the first soak of the tool loops: a world came out of an afternoon with
`d`, `e`, `h`, `s`, `t` and `x` among the conditions nothing could ever unset.
`worldcheck` reported them faithfully, and `help x` had nothing to say about
any of them, because there was nothing to say.

A `set_state` effect had been written `"add": "sharpened"` rather than
`["sharpened"]`, and read as written that is not one condition but nine, one
per letter -- each registered on the way in, with a meaning nobody wrote and a
group nothing shares.

`conditions._listed` had learned this years earlier for a rule's requirements.
The lesson was never carried to the dozen other places that read a list of
words out of what a model wrote, so it is one function now, and the register
refuses a slug too short to be a word at all.
"""

from django.test import SimpleTestCase, tag
from evennia.utils.test_resources import EvenniaTest

from world import clothing, effects, goals, model_json, verbs


@tag("unit")
class AListHoweverItWasWritten(SimpleTestCase):

    def test_one_word_is_one_thing_and_not_its_letters(self):
        self.assertEqual(model_json.listed("sharpened"), ["sharpened"])

    def test_a_list_is_itself_without_its_blanks(self):
        self.assertEqual(model_json.listed(["lit", "", None, "wet"]),
                         ["lit", "wet"])

    def test_nothing_is_nothing(self):
        self.assertEqual(model_json.listed(None), [])
        self.assertEqual(model_json.listed(""), [])
        self.assertEqual(model_json.listed([]), [])

    def test_a_condition_written_as_one_object_is_one_thing(self):
        self.assertEqual(model_json.listed({"subject": "direct"}),
                         [{"subject": "direct"}])


@tag("world")
class WhatAThingIsPutInto(EvenniaTest):

    def setUp(self):
        super().setUp()
        self.root = self.room1
        self.root.db.world_root = self.root
        self.root.db.is_world_root = True

    def test_a_state_written_as_a_word(self):
        verbs.apply_states(self.obj1, add="sharpened", world_root=self.root)
        self.assertEqual(verbs.states(self.obj1), {"sharpened"})
        self.assertNotIn("s", verbs.vocabulary(self.root))

    def test_an_effect_written_the_same_way(self):
        effects.apply(self.char1, self.root,
                      [{"type": "set_state", "role": "direct",
                        "add": "sharpened"}],
                      bound={"direct": self.obj1}, world_root=self.root)
        self.assertEqual(verbs.states(self.obj1), {"sharpened"})
        self.assertEqual([slug for slug in verbs.vocabulary(self.root)
                          if len(slug) < 2], [])

    def test_and_taking_one_away_again(self):
        verbs.apply_states(self.obj1, add=["sharpened"], world_root=self.root)
        verbs.apply_states(self.obj1, remove="sharpened", world_root=self.root)
        self.assertEqual(verbs.states(self.obj1), set())

    def test_a_thing_made_with_one(self):
        item = clothing.create({"name": "Whetstone", "description": "Grey.",
                                "kind": "whetstone", "states": "chipped"},
                               location=self.root)
        self.assertEqual(item.db.states, ["chipped"])

    def test_a_goal_asking_for_one(self):
        kept = goals.sanitise([{"type": "state", "object": "lamp",
                                "is": "lit", "lacks": "broken"}])
        self.assertEqual(kept[0]["is"], ["lit"])
        self.assertEqual(kept[0]["lacks"], ["broken"])

    def test_the_register_refuses_a_letter(self):
        """The belt to the braces: nothing this short is ever a condition."""
        self.assertEqual(verbs.register_state(self.root, "x", means="?"), "")
        self.assertNotIn("x", verbs.vocabulary(self.root))


@tag("world")
class ClearingUpAfterAWorldThatMetIt(EvenniaTest):

    def setUp(self):
        super().setUp()
        self.root = self.room1
        self.root.db.world_root = self.root
        self.root.db.is_world_root = True
        self.root.db.state_vocabulary = {
            "x": {"means": ""}, "d": {"means": ""},
            "sharpened": {"means": "given an edge"}}
        self.root.db.kind_specs = {
            "blade": {"states": ["x", "sharpened"], "affordances": {}}}
        self.obj1.db.states = ["d", "sharpened", "x"]

    def test_the_letters_go_and_the_words_stay(self):
        from world.housekeeping import prune_letter_states

        worlds, things = prune_letter_states()
        self.assertEqual((worlds, things), (1, 1))
        self.assertEqual(sorted(self.root.db.state_vocabulary), ["sharpened"])
        self.assertEqual(self.root.db.kind_specs["blade"]["states"],
                         ["sharpened"])
        self.assertEqual(self.obj1.db.states, ["sharpened"])

    def test_and_a_world_that_never_met_it_is_left_alone(self):
        from world.housekeeping import prune_letter_states

        prune_letter_states()
        worlds, things = prune_letter_states()
        self.assertEqual((worlds, things), (0, 0))
