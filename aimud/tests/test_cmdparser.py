"""
Builders' commands and the world's verbs, when they share a name.

On a self-hosted server the player is usually the superuser, so Evennia's
building commands were always in reach -- and `open door` in a generated world
made an exit called "door", `examine lantern` dumped the lantern's attributes,
and `force the lock` tried to make somebody run a command. Inside a generated
world those commands now need their prefix; outside one nothing changes.
"""

from unittest import mock

from django.test import tag
from evennia import CmdSet
from evennia.commands.default.admin import CmdForce
from evennia.commands.default.building import CmdExamine, CmdOpen
from evennia.utils.test_resources import EvenniaTest

from server.conf import cmdparser as parser


class Staff(CmdSet):
    key = "staff"

    def at_cmdset_creation(self):
        from commands.look_take_cmds import CmdAILook

        self.add(CmdOpen())
        self.add(CmdExamine())
        self.add(CmdForce())
        self.add(CmdAILook())


class Parsing(EvenniaTest):

    def setUp(self):
        super().setUp()
        self.cmdset = Staff()
        self.room1.db.world_root = self.room1
        self.room1.db.world_description = "A harbour town."

    def matched(self, raw, caller=None):
        return [match[2].key for match in
                parser.cmdparser(raw, self.cmdset, caller or self.char1)]


@tag("world")
class InsideAWorld(Parsing):

    def test_a_bare_building_command_is_left_for_the_world(self):
        for raw in ("open door", "examine lantern", "force the lock"):
            self.assertEqual(self.matched(raw), [], raw)

    def test_with_its_prefix_it_is_the_building_command(self):
        self.assertEqual(self.matched("@open door"), ["@open"])
        self.assertEqual(self.matched("@examine lantern"), ["@examine"])
        self.assertEqual(self.matched("@force the lock"), ["force"])

    def test_the_games_own_commands_need_no_prefix(self):
        self.assertEqual(self.matched("look lantern"), ["look"])

    def test_an_account_caller_is_placed_by_what_it_puppets(self):
        account = mock.Mock(spec=["puppet"])
        account.puppet = self.char1
        self.assertTrue(parser.in_generated_world(account))


@tag("world")
class OutsideAWorld(Parsing):

    def setUp(self):
        super().setUp()
        self.room1.db.world_description = None

    def test_nothing_changes(self):
        self.assertEqual(self.matched("open door"), ["@open"])
        self.assertEqual(self.matched("examine lantern"), ["@examine"])


@tag("world")
class TheHint(Parsing):

    def test_which_spelling_a_bare_name_is_offered(self):
        self.assertEqual(parser.staff_spelling(self.cmdset, self.char1, "open"),
                         "@open")
        self.assertEqual(parser.staff_spelling(self.cmdset, self.char1, "force"),
                         "@force")
        self.assertEqual(parser.staff_spelling(self.cmdset, self.char1, "look"),
                         "")
        self.assertEqual(parser.staff_spelling(self.cmdset, self.char1, "dance"),
                         "")


@tag("world")
class TypedInAWorld(EvenniaTest):
    """End to end, through the real command handler and the real settings."""

    def setUp(self):
        super().setUp()
        self.room1.db.world_root = self.room1
        self.room1.db.is_world_root = True
        self.room1.db.world_description = "A harbour town."

    def test_open_door_is_an_attempt_and_makes_no_exit(self):
        from evennia.objects.objects import DefaultExit

        said, attempted = [], []
        self.char1.msg = lambda text="", **kwargs: said.append(str(text))
        exits_before = [obj for obj in self.room1.contents
                        if isinstance(obj, DefaultExit)]

        def attempt(caller, raw, *args, **kwargs):
            attempted.append(raw)
            caller.ndb.attempting = None

        # A character with no key is refused before anything is attempted,
        # and that refusal is not what is being tested here.
        paying = mock.Mock()
        paying.key.return_value = "a key"
        with mock.patch("world.attempt.attempt", attempt), \
                mock.patch("commands.unknown_cmd._sponsor_for",
                           return_value=paying):
            self.char1.execute_cmd("open door")
            self.char1.execute_cmd("open door")
        self.assertEqual(attempted, ["open door", "open door"])
        exits_after = [obj for obj in self.room1.contents
                       if isinstance(obj, DefaultExit)]
        self.assertEqual(exits_after, exits_before)
        hints = [line for line in said if "@open" in line]
        self.assertEqual(len(hints), 1, "the hint is given once")
