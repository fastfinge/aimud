"""
Who pays when a command asks a model something.

`npcgen` and `rules judge` each handed a generator an account where it takes a
sponsor, and neither had ever worked. `npcgen` raised after it had marked the
room as busy, so the room refused `npcgen` until a reload; `rules judge` called
`key()` on an account, whose `key` is its name. Both now pay the way every
other command in a world does, through `sponsor.of(caller)`: the world pays.

The generators are replaced here. What is being tested is what the commands
hand them, and what the commands do with the answer.
"""

from unittest import mock

from django.test import tag

from tests.base import GameCommandTest
from commands.world_cmds import CmdNPCGen, CmdRules
from tests.support import FakeSponsor


@tag("world")
class MakingACharacter(GameCommandTest):
    characters = 2

    def setUp(self):
        super().setUp()
        self.room1.db.is_ai_room = True
        self.sponsor = FakeSponsor()

    def npcgen(self, generate):
        with mock.patch("commands.world_cmds.sponsor_mod.of",
                        return_value=self.sponsor) as of, \
                mock.patch("world.npc_gen.generate_npc", generate):
            said = self.call(CmdNPCGen(), "")
        return said, of

    def test_the_generator_is_handed_the_worlds_sponsor(self):
        asked = {}

        def generate(**kwargs):
            asked.update(kwargs)

        said, of = self.npcgen(generate)
        of.assert_called_once_with(self.char1)
        self.assertIs(asked["sponsor"], self.sponsor)
        self.assertIs(asked["room"], self.room1)
        self.assertIn("Generating NPC", said)

    def test_the_room_is_free_again_once_somebody_arrives(self):
        def generate(sponsor, room, on_success, on_error):
            on_success(self.char2)

        self.npcgen(generate)
        self.assertFalse(self.room1.ndb.generating_npc)

    def test_and_after_a_failure(self):
        def generate(sponsor, room, on_success, on_error):
            on_error("the model would not answer")

        said, _of = self.npcgen(generate)
        self.assertFalse(self.room1.ndb.generating_npc)
        self.assertIn("NPC generation failed", said)

    def test_with_no_key_nothing_is_asked_and_the_room_stays_free(self):
        self.sponsor = FakeSponsor(key="")
        asked = []

        said, _of = self.npcgen(lambda **kwargs: asked.append(kwargs))
        self.assertEqual(asked, [])
        self.assertFalse(self.room1.ndb.generating_npc)
        self.assertIn("No OpenRouter API key", said)


@tag("world")
class JudgingSuggestions(GameCommandTest):

    def setUp(self):
        super().setUp()
        self.root = self.room1
        self.root.db.is_world_root = True
        self.room1.db.world_root = self.root
        self.room1.db.is_ai_room = True
        self.sponsor = FakeSponsor()

    def test_the_judge_is_handed_the_worlds_sponsor(self):
        asked = []

        def judge(sponsor, world_root, on_success, on_error):
            asked.append((sponsor, world_root))
            on_success(["r1"], [])

        with mock.patch("commands.world_cmds.sponsor_mod.of",
                        return_value=self.sponsor) as of, \
                mock.patch("world.suggest.queue",
                           return_value=[{"id": "r1"}]), \
                mock.patch("world.suggest.judge", judge):
            said = self.call(CmdRules(), "judge")

        of.assert_called_once_with(self.char1)
        self.assertEqual(asked, [(self.sponsor, self.root)])
        self.assertIn("Accepted: r1", said)
