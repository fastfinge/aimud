"""
Shared worlds: somebody else standing in a world, paid for by its creator.

docs/archived/shared-worlds.md. Who pays is held in `tests/test_sponsor.py`, beside the
rest of the sponsor; this is what a creator and a visitor see.
"""

from django.test import tag

from tests import support
from tests.base import GameCommandTest, GameTest
from world import activity, sharing, sponsor


class _World(GameTest):
    """`room1` is a world `account` made; `char2` is somebody visiting it."""

    characters = 2
    accounts = True

    def setUp(self):
        super().setUp()
        self.root = self.room1
        self.root.db.is_world_root = True
        self.root.db.world_root = self.root
        self.root.tags.add(str(self.root.id), category="ai_world")
        self.account.db.openrouter_api_key = "sk-creator"
        sponsor.claim(self.root, self.account)


@tag("world")
class AlwaysFollowsItsCreator(_World):
    """
    `always` used to hold while anybody at all was logged in. A visitor is not
    paying, so it now holds only while the creator is. 6.2.
    """

    def setUp(self):
        super().setUp()
        activity.set_mode(self.root, activity.ALWAYS)

    def test_it_runs_while_the_creator_is_here(self):
        support.logged_in(self, self.account)
        self.assertTrue(activity.always_on(self.root))

    def test_a_visitor_does_not_keep_it_running(self):
        from unittest import mock

        # Somebody is connected -- the visitor -- which was all `always` asked.
        support.logged_in(self, self.account2)
        with mock.patch("evennia.server.sessionhandler.SESSIONS.get_sessions",
                        return_value=[object()]):
            self.assertFalse(activity.always_on(self.root))
        self.assertEqual(activity.mode(self.root), activity.NORMAL)

    def test_and_only_that_world_goes_back(self):
        from evennia import create_object

        other = create_object("typeclasses.rooms.Room", key="Elsewhere")
        other.db.world_root = other
        sponsor.claim(other, self.account2)
        activity.set_mode(other, activity.ALWAYS)
        support.logged_in(self, self.account2)

        self.assertFalse(activity.always_on(self.root))
        self.assertTrue(activity.always_on(other))


@tag("world")
class SharingAWorld(_World):

    def test_a_world_starts_unshared(self):
        self.assertFalse(sharing.is_shared(self.root))

    def test_its_creator_shares_it(self):
        said = sharing.share(self.account, self.root, True)
        self.assertTrue(sharing.is_shared(self.root))
        self.assertIn("enter world public", said)

    def test_nobody_else_can(self):
        said = sharing.share(self.account2, self.root, True)
        self.assertIn("Only whoever made this world", said)
        self.assertFalse(sharing.is_shared(self.root))

    def test_not_even_the_superuser(self):
        self.account2.is_superuser = True
        sharing.share(self.account2, self.root, True)
        self.assertFalse(sharing.is_shared(self.root))

    def test_closing_it_sends_visitors_to_the_start(self):
        from commands.world_subject import start_room

        sharing.share(self.account, self.root, True)
        heard = []
        self.char2.msg = lambda text="", **kw: heard.append(str(text))
        said = sharing.share(self.account, self.root, False)
        self.assertFalse(sharing.is_shared(self.root))
        self.assertEqual(self.char2.location, start_room())
        self.assertIn("closed", " ".join(heard))
        self.assertIn("1 visitor", said)

    def test_and_leaves_its_creator_where_they_are(self):
        sharing.share(self.account, self.root, True)
        sharing.share(self.account, self.root, False)
        self.assertEqual(self.char1.location, self.root)

    def test_people_who_live_there_are_not_visitors(self):
        from evennia import create_object

        npc = create_object("typeclasses.npcs.NPC", key="Bram",
                            location=self.root)
        npc.db.is_npc = True
        self.assertEqual(sharing.visitors_in(self.root), [self.char2])

    def test_it_does_not_travel_in_a_document(self):
        from world import exchange

        self.assertIn("shared", exchange.LEFT)
        self.assertNotIn("shared", exchange.CARRIED)


@tag("world")
class WhoMayEnter(_World):

    def test_its_creator(self):
        self.assertTrue(sharing.may_enter(self.account, self.root))

    def test_nobody_else_while_it_is_unshared(self):
        self.assertFalse(sharing.may_enter(self.account2, self.root))

    def test_anybody_once_it_is_shared(self):
        sharing.share(self.account, self.root, True)
        self.assertTrue(sharing.may_enter(self.account2, self.root))

    def test_the_superuser_who_may_repair_it(self):
        self.account2.is_superuser = True
        self.assertTrue(sharing.may_enter(self.account2, self.root))


@tag("world")
class ThePublicList(_World):

    def world(self, key, account, shared=True):
        from evennia import create_object

        root = create_object("typeclasses.rooms.Room", key=key)
        root.db.world_root = root
        sponsor.claim(root, account)
        if shared:
            root.db.shared = True
        return root

    def test_lists_what_others_have_shared(self):
        sharing.share(self.account, self.root, True)
        self.assertEqual(sharing.public_worlds(self.account2), [self.root])

    def test_but_not_your_own(self):
        sharing.share(self.account, self.root, True)
        self.assertEqual(sharing.public_worlds(self.account), [])

    def test_nor_a_world_nobody_shared(self):
        self.assertEqual(sharing.public_worlds(self.account2), [])

    def test_in_order_of_who_made_them_and_then_when(self):
        sharing.share(self.account, self.root, True)
        later = self.world("Later", self.account)
        mine = self.world("Mine", self.account2)
        found = sharing.public_worlds(self.account2)
        self.assertEqual(found, [self.root, later])
        self.assertNotIn(mine, found)


@tag("world")
class SharingFromSettings(GameCommandTest):
    """`settings shared`, which is where a creator does it. 3.1."""

    characters = 2
    accounts = True

    def setUp(self):
        super().setUp()
        self.room1.db.world_root = self.room1
        self.room1.tags.add(str(self.room1.id), category="ai_world")
        sponsor.claim(self.room1, self.account)

    def settings(self, args):
        from commands.settings_cmds import CmdSettings

        return self.call(CmdSettings(), args)

    def test_it_asks_first(self):
        said = self.settings("shared on")
        self.assertIn("settings shared on yes", said)
        self.assertFalse(sharing.is_shared(self.room1))

    def test_and_shares_once_answered(self):
        self.settings("shared on yes")
        self.assertTrue(sharing.is_shared(self.room1))

    def test_a_visitor_has_no_such_setting(self):
        self.room1.db.world_creator = self.account2
        self.assertIn("no setting called", self.settings("shared on yes"))
        self.assertFalse(sharing.is_shared(self.room1))


@tag("world")
class EnteringASharedWorld(GameCommandTest):
    """
    `char1` visits `room2`, a world `account2` made and shared. 4.

    `char1` starts in `room1`, outside every world.
    """

    characters = 2
    accounts = True
    second_room = True

    def setUp(self):
        super().setUp()
        self.room2.db.world_root = self.room2
        self.room2.db.is_world_root = True
        self.room2.db.world_title = "Harbour"
        self.room2.tags.add(str(self.room2.id), category="ai_world")
        sponsor.claim(self.room2, self.account2)
        self.account2.db.created_worlds = [self.room2.id]
        sharing.share(self.account2, self.room2, True)

    def enter(self, args):
        from commands.verbs import CmdEnter

        return self.call(CmdEnter(), args)

    def test_by_number(self):
        self.enter("world public 1")
        self.assertIs(self.char1.location, self.room2)

    def test_by_title(self):
        self.enter("world public harbour")
        self.assertIs(self.char1.location, self.room2)

    def test_a_number_that_is_not_one(self):
        self.assertIn("Choose 1 to 1", self.enter("world public 9"))
        self.assertIs(self.char1.location, self.room1)

    def test_it_is_not_among_your_own(self):
        self.assertIn("haven't made any worlds", self.enter("world 1"))

    def test_an_unshared_world_cannot_be_entered(self):
        from commands.world_subject import enter_world

        sharing.share(self.account2, self.room2, False)
        said = enter_world(self.char1, self.room2)
        self.assertIn("not shared", said)
        self.assertIs(self.char1.location, self.room1)

    def test_a_visitor_is_told_when_its_creator_is_away(self):
        said = self.enter("world public 1")
        self.assertIn("is away", said)

    def test_and_not_when_they_are_here(self):
        support.logged_in(self, self.account2)
        said = self.enter("world public 1")
        self.assertNotIn("is away", said)

    def test_the_menu_lists_it_with_who_made_it(self):
        from unittest import mock

        from commands import subjects
        from world import menus

        heard = []
        self.account.msg = lambda text="", **kw: heard.append(
            str(text[0] if isinstance(text, tuple) else text))
        with mock.patch.object(menus, "interactive", return_value=True):
            menus.open_menu(self.char1, subjects.verb_form("enter"),
                            path=["world"], interactive_only=False)
            self.assertIn("Public worlds", heard[-1])
            menu = self.account.ndb._evmenu
            menu.parse_input("public")
            self.assertIn(f"Harbour, by {self.account2.key}, away", heard[-1])
            menu.parse_input("1")
        self.assertIs(self.char1.location, self.room2)

    def test_the_submenu_is_not_offered_when_nothing_is_shared(self):
        from commands.world_subject import enter_world_items
        from world import menus

        sharing.share(self.account2, self.room2, False)
        ctx = menus.Context(self.char1)
        self.assertEqual([item.key for item in enter_world_items(ctx)], [])


@tag("world")
class TellingVisitors(_World):
    """When spending stops and starts again, visitors are told. 6.3."""

    def setUp(self):
        super().setUp()
        self.account.db.created_worlds = [self.root.id]
        sharing.share(self.account, self.root, True)
        self.heard = []
        self.char2.msg = lambda text="", **kw: self.heard.append(str(text))

    def test_when_the_creator_logs_out(self):
        self.account.at_post_disconnect()
        self.assertIn("logged out", " ".join(self.heard))

    def test_nobody_is_told_about_a_world_that_is_not_shared(self):
        sharing.share(self.account, self.root, False)
        self.heard.clear()
        self.assertEqual(sharing.tell_visitors(self.account, "hello"), 0)
        self.assertEqual(self.heard, [])

    def test_when_they_are_back(self):
        from unittest import mock

        with mock.patch.object(type(self.account.sessions), "count",
                               return_value=1):
            self.account.at_post_login()
        self.assertIn("is back", " ".join(self.heard))


@tag("world")
class AResetKeepsItShared(GameTest):
    """
    A reset builds a new root, and `shared` is not in a world's document.
    Without carrying it, visitors were moved into a world that had stopped
    being shared. 3.2.
    """

    characters = 2
    accounts = True

    def test_putting_an_imported_world_back(self):
        from commands.world_subject import _replay
        from tests.test_exchange import WorldTest
        from world import exchange

        made = WorldTest.world(self)
        account_root = exchange.build(exchange.document(made), self.account,
                                      self.char1)
        sharing.share(self.account, account_root, True)

        _replay(self.char1, account_root)
        new_root = self.char1.location.db.world_root
        self.assertIsNot(new_root, account_root)
        self.assertTrue(sharing.is_shared(new_root))
