"""
Looking at what somebody here is wearing or carrying.

Looking at a person lists it -- "Bram is wearing a canvas vest" -- and then it
could not be looked at. `look Bram's vest` was refused for a vest Bram had on,
`look vest` went on to invent a second vest, and the rulebooks called the one
he was wearing out of sight. Everything made for a character when they were
created had a description nobody could read.
"""

from unittest import mock

from django.test import tag
from evennia import create_object

from tests.base import GameTest
from world import clothing, standard_rules


@tag("world")
class WhatSomebodyHasOn(GameTest):

    def setUp(self):
        super().setUp()
        from typeclasses.npcs import NPC

        self.room1.db.world_root = self.room1
        self.room1.db.world_description = "A horse farm."
        self.room1.db.is_ai_room = True
        standard_rules.seed(self.room1)
        self.bram = create_object(NPC, key="Bram", location=self.room1)
        self.vest = self.dress(self.bram, "canvas vest", "A heavy canvas vest.",
                               "vest", "top")
        self.heard = []
        self.char1.msg = lambda text="", **kw: self.heard.append(
            str(text[0] if isinstance(text, tuple) else text))

    @staticmethod
    def dress(person, name, description, kind, garment):
        return clothing.create({"name": name, "description": description,
                                "kind": kind, "clothing_type": garment},
                               location=person, worn_on=person)

    def look(self, line):
        self.heard.clear()
        paying = mock.Mock()
        paying.key.return_value = "a key"
        with mock.patch("commands.look_take_cmds._sponsor_for",
                        return_value=paying), \
                mock.patch("world.llm.call",
                           side_effect=AssertionError("nothing is conjured")):
            self.char1.execute_cmd(line)
        return "\n".join(self.heard)

    def test_by_whose_it_is(self):
        self.assertIn("A heavy canvas vest.", self.look("look Bram's vest"))

    def test_by_its_name_alone(self):
        self.assertIn("A heavy canvas vest.", self.look("look vest"))

    def test_by_its_whole_name(self):
        self.assertIn("A heavy canvas vest.",
                      self.look("look at the canvas vest"))

    def test_nothing_new_is_made_for_it(self):
        self.look("look vest")
        self.assertEqual([obj.key for obj in self.room1.contents
                          if obj.key == "canvas vest"], [])

    def test_two_people_with_one_each_are_asked_about(self):
        from typeclasses.npcs import NPC

        juno = create_object(NPC, key="Juno", location=self.room1)
        self.dress(juno, "straw hat", "A wide straw hat.", "hat", "hat")
        self.dress(self.bram, "felt hat", "A battered felt hat.", "hat", "hat")
        said = self.look("look hat")
        self.assertIn("Which hat do you mean", said)
        self.assertIn("Bram's felt hat", said)
        self.assertIn("Juno's straw hat", said)

    def test_a_multi_word_name_owns_things_too(self):
        from typeclasses.npcs import NPC

        kettle = create_object(NPC, key="Copper Kettle", location=self.room1)
        self.dress(kettle, "straw hat", "A wide straw hat.", "hat", "hat")
        self.assertIn("A wide straw hat.",
                      self.look("look Copper Kettle's hat"))

    def test_something_they_do_not_have_is_still_refused(self):
        self.assertIn("no boots of Bram's", self.look("look Bram's boots"))

    def test_somebody_who_has_left_takes_their_things_out_of_sight(self):
        self.bram.location = None
        said = self.look("look Bram's vest")
        self.assertNotIn("A heavy canvas vest.", said)
