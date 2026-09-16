"""
Characters on finish tools: the first part of phase 7 of
docs/generator-tool-loops.md.

Making a character and dressing one are tool loops now. The name check that
used to retry by hand is a complaint, and so is everything that used to be
dropped without a word: a pronoun set nobody keeps, a goal nothing can test,
a trait nothing measures, a garment nobody can put on.
"""

from django.test import tag
from evennia import create_object

from tests.base import GameTest
from tests.support import (FakeSponsor, finishing, immediately, replying,
                           tool_call, tool_reply)
from world import npc_gen, pronouns

BRAM = {"name": "Bram Holt", "description": "A broad man with grey eyes.",
        "manner": "Gruff, and fair with it.", "pronouns": "he", "goal": [],
        "traits": []}

COAT = {"name": "patched wool coat", "description": "A coat, much mended.",
        "kind": "coat", "clothing_type": "top", "affordances": {"wear": True}}

OUTFIT = {"worn": [COAT], "carried": []}


def _offered(recorder, index, name):
    for schema in recorder.tools(index) or ():
        if schema["function"]["name"] == name:
            return schema["function"]
    return None


def _results(recorder, index):
    return "\n".join(message["content"]
                     for message in recorder.tool_results(index))


class _World(GameTest):

    def setUp(self):
        super().setUp()
        self.root = self.room1
        self.root.db.world_root = self.root
        self.root.db.is_world_root = True

    def make(self, *replies):
        made, failed = [], []
        with immediately(), replying(*replies) as recorder:
            npc_gen.generate_npc(FakeSponsor(), self.root,
                                 on_success=made.append,
                                 on_error=failed.append)
        self.assertEqual(failed, [])
        return (made[0] if made else None), recorder

    def answers(self, *characters):
        """Each character in turn, and the same outfit whenever asked."""
        return [tool_reply(tool_call("make_character", **character))
                for character in characters[:-1]] + [
            finishing(make_character=characters[-1],
                      dress_character=OUTFIT)]


@tag("world")
class MakingACharacter(_World):

    def test_a_character_is_made_and_dressed(self):
        npc, recorder = self.make(*self.answers(BRAM))
        self.assertEqual(npc.key, "Bram Holt")
        self.assertEqual(pronouns.of(npc, self.root)["subject"], "he")
        self.assertIn("patched wool coat", [obj.key for obj in npc.contents])
        self.assertIsNotNone(_offered(recorder, 0, "list_traits"))

    def test_a_name_somebody_answers_to_is_sent_back(self):
        from typeclasses.npcs import NPC

        create_object(NPC, key="Bram Stone", location=self.root)
        npc, recorder = self.make(*self.answers(
            BRAM, dict(BRAM, name="Tamsin Holt", pronouns="she")))
        self.assertIn("already living in this world", _results(recorder, 1))
        self.assertEqual(npc.key, "Tamsin Holt")

    def test_a_trait_nothing_measures_is_sent_back(self):
        npc, recorder = self.make(*self.answers(
            dict(BRAM, traits=[{"slug": "zorbitude", "value": 3}]), BRAM))
        self.assertIn("zorbitude", _results(recorder, 1))
        self.assertIsNotNone(npc)

    def test_a_goal_nothing_can_test_is_sent_back(self):
        _npc, recorder = self.make(*self.answers(
            dict(BRAM, goal=[{"type": "dance", "object": "jig"}]),
            dict(BRAM, goal=[{"type": "holds", "object": "brass key"}])))
        self.assertIn("cannot be tested", _results(recorder, 1))

    def test_a_pronoun_set_nobody_keeps_must_be_declared_whole(self):
        ze = {"subject": "ze", "object": "zir", "adjective": "zir",
              "possessive": "zirs", "reflexive": "zirself", "plural": False,
              "means": "for the ship's mind"}
        npc, recorder = self.make(*self.answers(
            dict(BRAM, pronouns="ze"),
            dict(BRAM, pronouns="ze", new_pronoun_set=ze)))
        self.assertIn("keeps no pronoun set called ze", _results(recorder, 1))
        self.assertEqual(pronouns.of(npc, self.root)["subject"], "ze")

    def test_rounds_out_keeps_the_character_anyway(self):
        from typeclasses.npcs import NPC

        create_object(NPC, key="Bram Stone", location=self.root)
        npc, recorder = self.make(finishing(make_character=BRAM,
                                            dress_character=OUTFIT))
        self.assertEqual(npc.key, "Bram Holt")
        self.assertGreaterEqual(recorder.count, npc_gen.NPC_ROUNDS)


@tag("world")
class DressingACharacter(_World):
    second_room = True
    # What a player wants outranks what an NPC wants, and `goals` decides
    # which `char1` is by whether an account is behind it -- see the
    # `player = ...` line in world/goals.py.
    accounts = True

    def setUp(self):
        super().setUp()
        from typeclasses.npcs import NPC

        self.bram = create_object(NPC, key="Bram", location=self.root)

    def dress(self, *replies):
        with immediately(), replying(*replies) as recorder:
            npc_gen.dress_npc(FakeSponsor(), self.bram)
        return recorder

    def test_a_garment_nobody_can_put_on_is_sent_back(self):
        unwearable = dict(COAT, affordances={})
        recorder = self.dress(
            tool_reply(tool_call("dress_character", worn=[unwearable],
                                 carried=[])),
            tool_reply(tool_call("dress_character", **OUTFIT)))
        self.assertIn("has to afford wear", _results(recorder, 1))
        self.assertIn("patched wool coat",
                      [obj.key for obj in self.bram.contents])

    def test_what_somebody_else_wants_is_offered_to_carry(self):
        self.char1.db.goal = [{"type": "holds", "object": "raw ore"}]
        self.char1.move_to(self.room2, quiet=True)
        self.room2.db.world_root = self.root
        self.room2.tags.add(str(self.root.id), category="ai_world")
        recorder = self.dress(finishing(dress_character=OUTFIT))
        self.assertIn("named so that the name contains 'raw ore'",
                      recorder.sent(0))

    def test_but_never_what_they_want_themselves(self):
        self.bram.db.goal = [{"type": "holds", "object": "raw ore"}]
        recorder = self.dress(finishing(dress_character=OUTFIT))
        # What they want is still said -- it is who they are -- but not as
        # something to be given to carry.
        self.assertIn("What they want", recorder.sent(0))
        self.assertNotIn("named so that the name contains", recorder.sent(0))
