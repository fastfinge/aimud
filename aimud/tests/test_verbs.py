"""
The verb commands and their subjects: create, edit, delete, reset, view and
enter world, enter start, and the parser rule that leaves every other use of
those words to the world. See docs/commands-and-settings.md §2 and §4.
"""

from unittest import mock

from django.test import SimpleTestCase, tag
from evennia import create_object

from commands import subjects, world_subject
from commands.unknown_cmd import retired_spelling
from commands.verbs import CmdCreate, CmdDelete, CmdEdit, CmdEnter, CmdReset, CmdView
from server.conf import cmdparser as parser
from tests.base import GameCommandTest, GameTest
from world import activity, menus, sponsor, verbs


# ---------------------------------------------------------------------------
# Which input a verb command takes
# ---------------------------------------------------------------------------

@tag("unit")
class NamingASubject(SimpleTestCase):

    def test_a_subject_word_is_claimed(self):
        self.assertTrue(subjects.claims("reset", "world 2"))
        self.assertTrue(subjects.claims("view", "worlds"))

    def test_the_verb_alone_is_claimed(self):
        self.assertTrue(subjects.claims("reset", ""))

    def test_anything_else_is_not(self):
        self.assertFalse(subjects.claims("reset", "the trap"))
        self.assertFalse(subjects.claims("view", "the mural"))
        self.assertFalse(subjects.claims("create", "fire"))
        self.assertFalse(subjects.claims("reset", "worldly goods"))

    def test_the_rest_of_the_line_is_handed_on(self):
        subject, rest = subjects.named("delete", "world  2 yes")
        self.assertEqual(subject.key, "world")
        self.assertEqual(rest, "2 yes")

    def test_a_verb_only_answers_for_its_own_subjects(self):
        # `import` reaches a world and the commonsense lexicon, and nothing
        # else. This was `import world` until a world could be imported, which
        # is the way this assertion is meant to change: a pair stops being an
        # example the moment the pair becomes real.
        self.assertFalse(subjects.claims("import", "rules"))
        self.assertFalse(subjects.claims("import", "tokens"))
        self.assertTrue(subjects.claims("import", "world"))


class _Verbs(GameTest):
    def setUp(self):
        super().setUp()
        from evennia import CmdSet

        class Verbs(CmdSet):
            key = "verbs"

            def at_cmdset_creation(self):
                for command in (CmdCreate, CmdReset, CmdView, CmdEnter):
                    self.add(command())

        self.cmdset = Verbs()

    def matched(self, raw):
        return [match[2].key for match in
                parser.cmdparser(raw, self.cmdset, self.char1)]


@tag("world")
class TheParserRule(_Verbs):

    def setUp(self):
        super().setUp()
        self.room1.db.world_root = self.room1
        self.room1.db.world_description = "A harbour town."

    def test_in_a_world_a_verb_with_a_subject_is_the_command(self):
        self.assertEqual(self.matched("reset world 2"), ["reset"])
        self.assertEqual(self.matched("view worlds"), ["view"])
        self.assertEqual(self.matched("create"), ["create"])

    def test_and_without_one_it_is_left_for_the_world(self):
        for raw in ("reset the trap", "view the mural", "create fire",
                    "enter the cave"):
            self.assertEqual(self.matched(raw), [], raw)

    def test_outside_a_world_the_command_takes_everything(self):
        self.room1.db.world_description = None
        self.assertEqual(self.matched("reset the trap"), ["reset"])


@tag("world")
class TypedInAWorld(GameTest):
    """End to end, through the real command handler."""

    def setUp(self):
        super().setUp()
        self.room1.db.world_root = self.room1
        self.room1.db.world_description = "A harbour town."

    def test_reset_the_trap_is_an_attempt_and_reset_world_is_not(self):
        attempted = []

        def attempt(caller, raw, *args, **kwargs):
            attempted.append(raw)
            caller.ndb.attempting = None

        paying = mock.Mock()
        paying.key.return_value = "a key"
        self.char1.msg = lambda text="", **kwargs: None
        with mock.patch("world.attempt.attempt", attempt), \
                mock.patch("commands.unknown_cmd._sponsor_for",
                           return_value=paying):
            self.char1.execute_cmd("reset the trap")
            self.char1.execute_cmd("reset world")
        self.assertEqual(attempted, ["reset the trap"])


@tag("unit")
class WhatTheEngineReserves(SimpleTestCase):

    def test_the_verb_commands_do_not_reserve_their_words(self):
        """
        A world may still write rules for reset or view, so generators must
        not be told those words are the engine's -- and the attempt pipeline
        must not hand them back to the command, which would bounce for ever.
        """
        for command in (CmdCreate, CmdReset, CmdView, CmdEnter):
            self.assertFalse(verbs.reserves_word(command()))

    def test_an_unflagged_command_falls_back_to_its_category(self):
        playing = mock.Mock(spec=["help_category"], help_category="General")
        building = mock.Mock(spec=["help_category"], help_category="Building")
        self.assertTrue(verbs.reserves_word(playing))
        self.assertFalse(verbs.reserves_word(building))


# ---------------------------------------------------------------------------
# Worlds
# ---------------------------------------------------------------------------

class _Worlds(GameCommandTest):
    """An account with worlds of its own: room2 is world 1, room3 world 2."""

    accounts = True
    second_room = True

    def setUp(self):
        super().setUp()
        self.account.db.openrouter_api_key = "sk-abcdefgh12345678"
        self.world1 = self._world(self.room2, "Harbour")
        self.room3 = create_object("typeclasses.rooms.Room", key="Room3")
        self.world2 = self._world(self.room3, "Freighter")
        self.account.db.created_worlds = [self.room2.id, self.room3.id]

    def _world(self, room, title):
        room.db.world_root = room
        room.db.is_world_root = True
        room.db.world_title = title
        room.db.world_description = f"The {title.lower()}."
        room.tags.add(str(room.id), category="ai_world")
        sponsor.claim(room, self.account)
        return room

    def said_into(self, command, args):
        return self.call(command(), args)


@tag("world")
class EnteringWorlds(_Worlds):

    def test_enter_world_by_number(self):
        self.said_into(CmdEnter, "world 2")
        self.assertIs(self.char1.location, self.room3)

    def test_or_by_title(self):
        self.said_into(CmdEnter, "world harbour")
        self.assertIs(self.char1.location, self.room2)

    def test_back_where_you_last_were(self):
        inner = create_object("typeclasses.rooms.Room", key="Cellar")
        inner.db.world_root = self.room2
        self.account.db.world_last_locations = {str(self.room2.id): inner}
        self.said_into(CmdEnter, "world 1")
        self.assertIs(self.char1.location, inner)

    def test_a_number_that_is_not_a_world(self):
        self.assertIn("Choose 1 to 2", self.said_into(CmdEnter, "world 9"))

    def test_enter_start_is_the_way_out(self):
        self.char1.move_to(self.room2, quiet=True)
        with mock.patch.object(world_subject, "start_room",
                               return_value=self.room1):
            self.said_into(CmdEnter, "start")
        self.assertIs(self.char1.location, self.room1)

    def test_the_start_room_answers_to_its_own_name(self):
        with mock.patch.object(world_subject, "start_room",
                               return_value=self.room1):
            subject, rest = subjects.named("enter", "room")
        self.assertEqual(subject.key, "start")

    def test_leaving_a_world_running_always_says_so(self):
        self.char1.move_to(self.room2, quiet=True)
        activity.set_mode(self.room2, activity.ALWAYS)
        with mock.patch.object(world_subject, "start_room",
                               return_value=self.room1):
            said = self.said_into(CmdEnter, "start")
        self.assertIn("still running always", said)
        self.assertEqual(activity.mode(self.room2), activity.ALWAYS)


@tag("world")
class DeletingWorlds(_Worlds):

    def test_it_asks_first(self):
        said = self.said_into(CmdDelete, "world 2")
        self.assertIn("delete world 2 yes", said)
        self.assertTrue(self.room3.pk)

    def test_yes_deletes_it(self):
        said = self.said_into(CmdDelete, "world 2 yes")
        self.assertIn("Deleted world", said)
        self.assertEqual(self.account.db.created_worlds, [self.room2.id])

    def test_not_the_one_you_are_standing_in_and_nothing_is_asked(self):
        self.char1.move_to(self.room3, quiet=True)
        said = self.said_into(CmdDelete, "world 2")
        self.assertIn("standing in", said)
        self.assertNotIn("yes", said)
        self.assertIn(self.room3.id, self.account.db.created_worlds)

    def test_a_world_somebody_else_made_is_not_offered(self):
        self.account.db.created_worlds = [self.room2.id]
        self.assertIn("None of your worlds",
                      self.said_into(CmdDelete, "world freighter yes"))

    def test_through_the_menu(self):
        heard = []
        self.account.msg = lambda text="", **kw: heard.append(
            str(text[0] if isinstance(text, tuple) else text))
        menus.open_menu(self.char1, subjects.verb_form("delete"),
                        path=["world"], interactive_only=False)
        self.assertIn("1. Harbour, 1 room", heard[-1])
        menu = self.account.ndb._evmenu
        menu.parse_input("2")
        self.assertIn("Permanently delete Freighter", heard[-1])
        menu.parse_input("yes")
        self.assertEqual(self.account.db.created_worlds, [self.room2.id])
        self.assertIsNone(self.account.ndb._evmenu)


@tag("world")
class ResettingWorlds(_Worlds):

    def test_it_rebuilds_from_the_worlds_own_setup(self):
        with mock.patch("world.worldgen.generate_first_room") as generating:
            self.said_into(CmdReset, "world 1 yes")
        spec = generating.call_args[0][1]
        self.assertEqual(spec["title"], "Harbour")
        self.assertEqual(spec["description"], "The harbour.")

    def test_it_asks_first(self):
        with mock.patch("world.worldgen.generate_first_room") as generating:
            said = self.said_into(CmdReset, "world 1")
        generating.assert_not_called()
        self.assertIn("reset world 1 yes", said)


@tag("world")
class ViewingWorlds(_Worlds):

    def test_a_list_numbered_as_they_were_made(self):
        said = self.said_into(CmdView, "worlds")
        self.assertIn("1. Harbour", said)
        self.assertIn("2. Freighter", said)

    def test_the_one_you_are_in_is_marked_not_moved(self):
        self.char1.move_to(self.room3, quiet=True)
        said = self.said_into(CmdView, "worlds")
        self.assertIn("2. Freighter, 1 room (you are here)", said)

    def test_one_world(self):
        self.assertIn("enter world 2", self.said_into(CmdView, "world 2"))


@tag("world")
class TheWizard(_Worlds):
    """create world and edit world, through the menu they open."""

    def setUp(self):
        super().setUp()
        self.heard = []
        self.account.msg = lambda text="", **kw: self.heard.append(
            str(text[0] if isinstance(text, tuple) else text))
        patcher = mock.patch.object(menus, "interactive", return_value=True)
        patcher.start()
        self.addCleanup(patcher.stop)

    def type(self, line):
        self.account.ndb._evmenu.parse_input(line)
        return self.heard[-1] if self.heard else ""

    def test_a_description_on_the_line_is_filled_in(self):
        self.call(CmdCreate(), "world A drowned city")
        self.assertIn("Description: A drowned city", self.heard[-1])

    def test_nothing_generates_without_a_description(self):
        self.call(CmdCreate(), "world")
        with mock.patch("world.worldgen.generate_first_room") as generating:
            self.assertIn("needs a description", self.type("generate"))
        generating.assert_not_called()

    def test_generating_hands_over_everything_entered(self):
        self.call(CmdCreate(), "world A drowned city")
        self.type("title")
        self.type("Drowned")
        with mock.patch("world.worldgen.generate_first_room") as generating:
            self.type("generate")
        spec = generating.call_args[0][1]
        self.assertEqual(spec["title"], "Drowned")
        self.assertEqual(spec["description"], "A drowned city")
        self.assertIsNone(self.account.ndb._evmenu)

    def test_long_fields_open_the_editor_and_come_back(self):
        self.call(CmdCreate(), "world")
        captured = {}

        def editor(caller, loadfunc, savefunc, quitfunc, **kwargs):
            captured.update(load=loadfunc, save=savefunc, quit=quitfunc)

        with mock.patch("evennia.utils.eveditor.EvEditor", editor):
            self.type("description")
        self.assertIsNone(self.account.ndb._evmenu)
        captured["save"](self.char1, "A city under the sea.\n")
        captured["quit"](self.char1)
        self.assertIn("Description: A city under the sea.", self.heard[-1])
        self.assertIsNotNone(self.account.ndb._evmenu)

    def test_edit_world_starts_from_what_it_was_set_up_with(self):
        self.call(CmdEdit(), "world 1")
        self.assertIn("Title: Harbour", self.heard[-1])
        self.type("title")
        self.type("Old Harbour")
        self.type("save")
        self.assertEqual(self.room2.db.world_title, "Old Harbour")

    def test_quitting_with_changes_asks(self):
        self.call(CmdEdit(), "world 1")
        self.type("title")
        self.type("Old Harbour")
        self.assertIn("Throw away", self.type("q"))


# ---------------------------------------------------------------------------
# Following across a world's edge
# ---------------------------------------------------------------------------

@tag("world")
class FollowingOutOfAWorld(GameTest):
    characters = 2
    second_room = True

    def setUp(self):
        super().setUp()
        self.room1.db.world_root = self.room1
        self.char2.db.following = self.char1
        self.char2.msg = lambda text="", **kw: None
        self.char1.msg = lambda text="", **kw: None

    def test_an_npc_stays_in_its_world(self):
        self.char2.db.is_npc = True
        self.char1.move_to(self.room2, quiet=True)
        self.assertIs(self.char2.location, self.room1)
        self.assertIsNone(self.char2.db.following)

    def test_a_player_comes_along(self):
        self.char1.move_to(self.room2, quiet=True)
        self.assertIs(self.char2.location, self.room2)

    def test_within_a_world_an_npc_still_follows(self):
        self.room2.db.world_root = self.room1
        self.char2.db.is_npc = True
        self.char1.move_to(self.room2, quiet=True)
        self.assertIs(self.char2.location, self.room2)


@tag("unit")
class RetiredWorldCommands(SimpleTestCase):

    def test_each_says_where_it_went(self):
        self.assertEqual(retired_spelling("worldgen a city"), "create world")
        self.assertEqual(retired_spelling("worldremove 2 confirm"),
                         "delete world")
        self.assertIn("enter world", retired_spelling("worlds 3"))
