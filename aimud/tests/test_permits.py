"""
What a world lets a model make for itself.

Three things are held down here.

**The register answers the question it was built for.** Five things, three
settings, and `asked` -- the one that is neither on nor off -- turning on
whether a *player* reached for it rather than whether anything did.

**Every generator asks.** Not by inspection: the test walks the modules and
insists that each one that spends a key has a gate above it, because a
generator that forgot is one that costs money in a world whose creator said it
should not, and nothing anywhere would say so.

**A world with its rooms turned off is made without a model at all.** That is
the whole point for a hand-built world: `create world` today plans zones, names
a room, describes it, fills it and opens a frontier, and somebody building
endless alchemy wants none of it and does not want to pay for undoing it.
"""

from unittest import mock

from django.test import SimpleTestCase, tag

from tests.base import GameTest
from world import permits


@tag("unit")
class TheRegister(GameTest):
    """
    What the register says, for the answers that do not depend on who asked.

    `asked` is the one that does, and it is `WhoCountsAsAPlayer` below --
    which pays for a session, because "is anybody at the keyboard" cannot be
    answered by a stand-in without testing the stand-in instead.
    """

    def setUp(self):
        super().setUp()
        self.root = self.room1
        self.root.db.is_world_root = True
        self.room1.db.world_root = self.root

    def test_a_world_that_has_said_nothing_generates_everything(self):
        """No world in play changes because a register gained a default."""
        for making in permits.MADE:
            self.assertEqual(permits.setting(self.root, making),
                             permits.ALWAYS, making)
            self.assertTrue(permits.allows(self.root, making, self.char1))

    def test_never_means_never_however_it_was_reached(self):
        permits.choose(self.root, "rooms", "never")
        for actor in (self.char1, None):
            self.assertFalse(permits.allows(self.root, "rooms", actor))

    def test_and_only_that_one(self):
        permits.choose(self.root, "rooms", "never")
        self.assertTrue(permits.allows(self.root, "items", self.char1))

    def test_asked_refuses_a_body_nobody_is_driving(self):
        permits.choose(self.root, "items", "asked")
        self.assertFalse(permits.allows(self.root, "items", self.char1))
        self.assertFalse(permits.allows(self.root, "items", None))

    def test_a_setting_nobody_recognises_is_the_default(self):
        permits.choose(self.root, "rooms", "sometimes")
        self.assertEqual(permits.setting(self.root, "rooms"), permits.ALWAYS)

    def test_a_world_outside_any_world_allows_everything(self):
        """Limbo is not a world with its rooms turned off."""
        for making in permits.MADE:
            self.assertTrue(permits.allows(None, making, self.char1))

    def test_every_one_has_a_label_and_a_sentence_for_being_off(self):
        for name, label, off in permits.MAKES:
            self.assertTrue(label, name)
            self.assertTrue(off, name)
            self.assertNotIn("|", off, f"{name}: markup belongs in the report")

    def test_why_it_was_refused_says_which_of_the_two_it_was(self):
        permits.choose(self.root, "rooms", "never")
        self.assertIn("somebody built",
                      permits.refused(self.root, "rooms", self.char1))
        permits.choose(self.root, "items", "asked")
        self.assertIn("a player goes looking",
                      permits.refused(self.root, "items", self.char1))

    def test_a_spec_carries_the_choice_and_a_reset_keeps_it(self):
        from world import lore

        lore.store(self.root, {"generation": {"rooms": "never",
                                              "items": "asked"}})
        self.assertEqual(permits.setting(self.root, "rooms"), permits.NEVER)
        self.assertEqual(permits.setting(self.root, "items"), permits.ASKED)
        self.assertEqual(permits.setting(self.root, "people"), permits.ALWAYS)

    def test_and_a_spec_that_says_nothing_changes_nothing(self):
        from world import lore

        permits.choose(self.root, "rooms", "never")
        lore.store(self.root, {"description": "A different world."})
        self.assertEqual(permits.setting(self.root, "rooms"), permits.NEVER)


@tag("world")
class WhoCountsAsAPlayer(GameTest):
    """
    The middle setting, which is the whole reason there are three.

    A session, because the question is literally whether anybody is at the
    keyboard -- the expensive fixture is the one that answers it, and a
    stand-in that only answered `sessions` would have tested the stand-in.
    """

    session = True

    def setUp(self):
        super().setUp()
        self.root = self.room1
        self.root.db.is_world_root = True
        self.room1.db.world_root = self.root
        permits.choose(self.root, "items", "asked")

    def test_a_player_at_the_keyboard_is_one(self):
        self.assertTrue(permits.is_player(self.char1))
        self.assertTrue(permits.allows(self.root, "items", self.char1))
        self.assertEqual(permits.refused(self.root, "items", self.char1), "")

    def test_a_character_is_not_one_however_many_sessions_it_has(self):
        from evennia import create_object

        npc = create_object("typeclasses.npcs.NPC", key="Hob",
                            location=self.room1)
        npc.db.is_npc = True
        self.assertFalse(permits.is_player(npc))
        self.assertFalse(permits.allows(self.root, "items", npc))


@tag("unit")
class TheSponsorIsWhereItIsAsked(GameTest):

    def setUp(self):
        super().setUp()
        self.root = self.room1
        self.root.db.is_world_root = True
        self.room1.db.world_root = self.root

    def sponsor(self, key="sk-test"):
        from world import sponsor as sponsor_mod

        account = mock.Mock()
        account.db.openrouter_api_key = key
        return sponsor_mod.Sponsor(world_root=self.root, account=account,
                                   actor=self.char1)

    def test_will_is_answers_and_may_together(self):
        paying = self.sponsor()
        self.assertTrue(paying.will("rooms"))

        permits.choose(self.root, "rooms", "never")
        self.assertTrue(paying.answers)
        self.assertFalse(paying.may("rooms"))
        self.assertFalse(paying.will("rooms"))

    def test_and_no_key_still_stops_everything(self):
        self.assertFalse(self.sponsor(key="").will("items"))

    def test_the_refusal_is_about_the_world_not_the_money(self):
        """A world that has said no is not a world that has not paid."""
        self.assertEqual(self.sponsor(key="").refusal("rooms"), "")

        permits.choose(self.root, "rooms", "never")
        self.assertIn("somebody built", self.sponsor().refusal("rooms"))


@tag("unit")
class EveryGeneratorAsks(SimpleTestCase):
    """
    A generator that spends a key has a gate above it, and this looks.

    Not a matter of trust: a generator with no gate costs money in a world
    whose creator turned that sort of thing off, and nothing anywhere would
    say so -- the world would simply keep growing and the bill keep running.
    Adding a generator without a gate fails here.
    """

    #: Where a model is asked for one of the five, and which of the five it
    #: is. The function named is the one that builds the prompt.
    GATED = (
        ("world/item_gen.py", "items"),
        ("world/npc_gen.py", "people"),
        ("world/verb_gen.py", "verbs"),
        ("world/rule_gen.py", "verbs"),
        ("world/quest_gen.py", "quests"),
        ("world/actions.py", "verbs"),
        ("world/worldgen.py", "items"),
    )

    def source(self, path):
        import pathlib

        from tests.test_token_lists import GAME

        return pathlib.Path(GAME / path).read_text(encoding="utf-8")

    def test_each_one_names_what_it_is_making(self):
        for path, making in self.GATED:
            with self.subTest(path=path):
                self.assertIn(f'will("{making}")', self.source(path))

    def test_the_door_asks_before_a_room_is_written(self):
        said = self.source("typeclasses/exits.py")
        self.assertIn('will("rooms")', said)

    def test_and_a_world_that_does_not_grow_opens_no_new_ways(self):
        said = self.source("world/worldgen.py")
        self.assertIn("permits.NEVER", said)


@tag("world")
class AWorldThatWritesNoRooms(GameTest):
    """
    `create world` with rooms off: one plain room, and no model call at all.

    The case the whole switch exists for. Today it plans zones, names a room,
    describes it, fills it with things and opens a frontier -- five calls and
    a world somebody building by hand has to undo before they can start.
    """

    def setUp(self):
        super().setUp()
        self.calls = []
        from world import llm

        def refuse(*args, **kwargs):
            self.calls.append(args)
            raise AssertionError("a world built by hand called a model")

        for name in ("fetch", "converse", "complete"):
            if hasattr(llm, name):
                patcher = mock.patch.object(llm, name, refuse)
                patcher.start()
                self.addCleanup(patcher.stop)

    def make(self, **spec):
        from world import sponsor as sponsor_mod
        from world import worldgen

        account = mock.Mock()
        account.db.openrouter_api_key = "sk-test"
        account.db.created_worlds = []
        spec.setdefault("title", "Endless Alchemy")
        spec.setdefault("description", "A kitchen at the end of the world.")
        spec.setdefault("generation", {"rooms": "never"})
        made, failed = [], []
        worldgen.generate_first_room(
            sponsor_mod.Sponsor(world_root=None, account=account),
            spec, made.append, failed.append,
            creator_character=self.char1)
        self.assertEqual(failed, [], failed)
        self.assertEqual(len(made), 1)
        return made[0]

    def test_it_is_made_at_once_and_costs_nothing(self):
        room = self.make()
        self.assertTrue(room.db.is_world_root)
        self.assertEqual(self.calls, [])

    def test_it_is_called_what_the_world_is_called(self):
        self.assertEqual(self.make().key, "Endless Alchemy")

    def test_and_says_what_to_do_next_rather_than_describing_nothing(self):
        said = self.make().db.desc
        self.assertIn("edit room", said)
        self.assertIn("create room", said)

    def test_it_keeps_the_world_and_its_text(self):
        from world import lore

        room = self.make()
        self.assertEqual(lore.title(room), "Endless Alchemy")
        self.assertIn("kitchen", lore.raw_description(room))
        self.assertIs(room.db.world_root, room)

    def test_and_remembers_the_choice_that_made_it(self):
        room = self.make()
        self.assertEqual(permits.setting(room, "rooms"), permits.NEVER)

    def test_it_has_no_way_out_it_did_not_ask_for(self):
        room = self.make()
        ways = [obj for obj in room.contents
                if getattr(obj, "destination", None)]
        self.assertEqual(ways, [])

    def test_and_nothing_opens_one_behind_your_back(self):
        from world import worldgen

        room = self.make()
        self.assertIsNone(worldgen.ensure_frontier(room, near=room))

    def test_the_other_four_are_still_on_unless_they_were_turned_off(self):
        room = self.make()
        for making in ("items", "people", "verbs", "quests"):
            self.assertEqual(permits.setting(room, making), permits.ALWAYS)

    def test_and_a_world_that_keeps_its_rooms_is_generated_as_it_always_was(self):
        """The switch is off by default, so nothing changes for anybody."""
        from world import worldgen

        account = mock.Mock()
        account.db.openrouter_api_key = "sk-test"
        from world import sponsor as sponsor_mod

        with mock.patch.object(worldgen, "_generate_plan") as planning:
            worldgen.generate_first_room(
                sponsor_mod.Sponsor(world_root=None, account=account),
                {"title": "Ordinary", "description": "A town."},
                lambda room: None, lambda err: None)
        planning.assert_called_once()
