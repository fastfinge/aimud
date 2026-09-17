"""
Telling the item generator why a thing is wanted.

A generator told only "a note" makes whatever a note usually is. Told who
reached for it, what they typed, what the note is in the sentence, and what
this world already says about the verb, it makes a note that fits -- and the
next rule that asks something of it finds what it expects. See
`item_gen.Wanted`.
"""

from django.test import tag

from tests.base import GameTest
from tests.support import FakeSponsor, finishing, immediately, replying
from world import item_gen
from world import rulebooks as R

LAMP = {"name": "Brass Lamp", "description": "A squat brass lamp.",
        "kind": "lamp", "takeable": True}


class WhyTest(GameTest):

    def setUp(self):
        super().setUp()
        self.root = self.room1
        self.root.db.is_world_root = True
        self.root.db.world_root = self.root

    def user_prompt(self, recorder, index=0):
        return "\n".join(message["content"]
                         for message in recorder.prompts[index]
                         if message["role"] == "user")


@tag("world")
class SayingWhy(WhyTest):

    def test_who_what_they_typed_and_what_it_is_in_the_sentence(self):
        said = item_gen.Wanted(self.char1, verb="burn", role="direct",
                               said="burn the note with the candle"
                               ).block(self.root)
        self.assertIn(f'{self.char1.key}, a player, tried: '
                      f'"burn the note with the candle".', said)
        self.assertIn("wanted as the thing acted on when they burn", said)

    def test_what_the_world_already_says_about_the_verb(self):
        R.add(self.root, R.blank(
            action="burn", phase=R.CARRY_OUT, name="burning sets it alight",
            effects=[{"type": "set_state", "role": "direct",
                      "add": ["burning"]}]))
        said = item_gen.Wanted(self.char1, verb="burn").block(self.root)
        self.assertIn("This world already says of burn: burning sets it "
                      "alight.", said)

    def test_deciding_whether_it_could_be_here_is_told_less(self):
        R.add(self.root, R.blank(
            action="burn", phase=R.CARRY_OUT, name="burning sets it alight",
            effects=[{"type": "set_state", "role": "direct",
                      "add": ["burning"]}]))
        said = item_gen.Wanted(self.char1, verb="burn").block(self.root,
                                                              brief=True)
        self.assertIn("burn", said)
        self.assertNotIn("already says", said)

    def test_a_character_says_what_it_is_working_towards(self):
        from evennia import create_object

        npc = create_object("typeclasses.npcs.NPC", key="Mira",
                            location=self.room1)
        npc.db.goal = [{"type": "holds", "object": "rope"}]
        said = item_gen.Wanted(npc, verb="climb", role="instrument",
                               said="climb down with the rope"
                               ).block(self.root)
        self.assertIn("Mira, a character in this world,", said)
        self.assertIn("the thing used to do it", said)
        self.assertIn("working towards", said)

    def test_nobody_said_why_says_nothing(self):
        self.assertEqual(item_gen.Wanted().block(self.root), "")


@tag("world")
class TheGeneratorIsTold(WhyTest):

    def test_the_item_prompt_carries_why(self):
        made = []
        wanted = item_gen.Wanted(self.char1, verb="light", role="direct",
                                 said="light the lamp")
        with immediately(), replying(finishing(make_item=LAMP)) as recorder:
            item_gen.generate_item(FakeSponsor(), self.root, "lamp",
                                   on_success=made.append,
                                   on_error=made.append, wanted=wanted)
        prompt = self.user_prompt(recorder)
        self.assertIn("Why it is wanted:", prompt)
        self.assertIn('"light the lamp"', prompt)
        self.assertEqual(made[0].key, "Brass Lamp")

    def test_and_without_why_it_is_asked_as_before(self):
        with immediately(), replying(finishing(make_item=LAMP)) as recorder:
            item_gen.generate_item(FakeSponsor(), self.root, "lamp",
                                   on_success=lambda item: None,
                                   on_error=lambda err: None)
        self.assertNotIn("Why it is wanted:", self.user_prompt(recorder))

    def test_a_verb_reaching_for_a_missing_thing_says_why(self):
        from unittest import mock

        from world import attempt

        parsed = {"verb": "burn", "roles": {"direct": "note",
                                            "instrument": "candle"}}
        with mock.patch("world.item_gen.conjure") as conjured:
            attempt._promote(self.char1, self.room1, FakeSponsor(), parsed,
                             {"instrument": self.char1}, ["direct"],
                             lambda: None, lambda *a, **k: None,
                             verb="burn", raw="burn the note with the candle")
        wanted = conjured.call_args.kwargs["wanted"]
        self.assertEqual((wanted.verb, wanted.role, wanted.said),
                         ("burn", "direct", "burn the note with the candle"))
        self.assertIs(wanted.actor, self.char1)

    def test_so_is_the_question_of_whether_it_could_be_here(self):
        wanted = item_gen.Wanted(self.char1, verb="climb", role="instrument",
                                 said="climb down the rope")
        with immediately(), replying(finishing(judge_existence={
                "valid": True, "reason": "a rope hangs here"})) as recorder:
            item_gen.validate_object_existence(
                FakeSponsor(), self.root, "rope", lambda why: None,
                lambda why: None, lambda why: None, wanted=wanted)
        prompt = self.user_prompt(recorder)
        self.assertIn('"climb down the rope"', prompt)
        self.assertIn("the thing used to do it", prompt)
