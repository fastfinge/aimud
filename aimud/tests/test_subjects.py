"""
The subjects phase 4 moved onto the verbs: rules, suggestions, effects,
faults, verbs, zones, npcs, word lists, pronouns, the lexicon, memory and
rounds -- who may use each, what asks first, and what the menus offer.

What each one reports is tested where it always was (`test_rules_command`,
`test_examining`, `test_rounds`, `test_token_lists`, `test_paying_commands`).
This is the part that is new. docs/commands-and-settings.md §4, §7 and §8.
"""

from unittest import mock

from django.test import SimpleTestCase, tag

from commands import subjects
from commands.pronoun_cmds import CmdPronouns
from commands.quest_cmds import CmdQuests
from commands.settings_cmds import CmdSettings
from commands.unknown_cmd import retired_spelling
from commands.verbs import (CmdCreate, CmdDelete, CmdEdit, CmdImport,
                            CmdReset, CmdView)
from tests.base import GameCommandTest
from world import menus, sponsor


class _InAWorld(GameCommandTest):
    accounts = True

    def setUp(self):
        super().setUp()
        self.root = self.room1
        self.root.db.is_world_root = True
        self.room1.db.world_root = self.root
        self.room1.db.world_description = "A harbour town."
        self.room1.db.is_ai_room = True
        sponsor.claim(self.root, self.account)

    def offered(self, verb):
        ctx = menus.Context(self.char1)
        return [item.key for item in subjects.verb_form(verb).items_for(ctx)]


@tag("world")
class WhoMayChangeAWorld(_InAWorld):

    def test_its_maker_may(self):
        self.assertNotIn("Only whoever made",
                         self.call(CmdEdit(), "rules dead yes"))

    def test_somebody_else_may_read_but_not_change(self):
        self.root.db.world_creator = self.account2
        self.assertIn("Only whoever made this world can change its rules",
                      self.call(CmdEdit(), "rules dead yes"))
        self.assertIn("Only whoever made this world can add people to it",
                      self.call(CmdCreate(), "npc"))
        self.assertNotIn("Only whoever made", self.call(CmdView(), "rules"))

    def test_and_is_not_offered_what_they_may_not_do(self):
        self.assertIn("rules", self.offered("edit"))
        self.root.db.world_creator = self.account2
        self.assertNotIn("rules", self.offered("edit"))
        self.assertIn("rules", self.offered("view"))


@tag("world")
class WhatIsOfferedWhere(_InAWorld):

    def test_outside_a_world_only_what_needs_no_world(self):
        self.room1.attributes.remove("world_root")
        offered = self.offered("view")
        self.assertIn("worlds", offered)
        self.assertIn("rounds", offered)
        self.assertNotIn("rules", offered)
        self.assertNotIn("zones", offered)

    def test_builders_tools_are_for_builders(self):
        self.assertIn("faults", self.offered("view"))
        self.char1.permissions.remove("Developer")
        self.account.permissions.clear()
        self.assertNotIn("faults", self.offered("view"))
        self.assertNotIn("memory", self.offered("edit"))
        self.assertIn("That is for builders",
                      self.call(CmdView(), "commonsense"))


@tag("world")
class WhatAsksFirst(_InAWorld):
    """Every confirmation from §8 this phase brought in."""

    def test_suspending_every_dead_rule(self):
        self.assertIn("edit rules dead yes", self.call(CmdEdit(), "rules dead"))

    def test_judging_suggestions(self):
        with mock.patch("world.suggest.queue", return_value=[{"id": "r1"}]), \
                mock.patch("world.suggest.judge") as judging:
            said = self.call(CmdEdit(), "suggestions judge")
        judging.assert_not_called()
        self.assertIn("edit suggestions judge yes", said)

    def test_resetting_a_verb(self):
        self.assertIn("reset verb respawn yes",
                      self.call(CmdReset(), "verb respawn"))

    def test_deleting_a_word_list(self):
        self.call(CmdCreate(), "tokens smell = brine | tar")
        said = self.call(CmdDelete(), "tokens smell")
        self.assertIn("delete tokens smell yes", said)
        self.assertIn("{smell}", self.call(CmdView(), "tokens smell"))

    def test_clearing_round_counts(self):
        self.assertIn("reset rounds yes", self.call(CmdReset(), "rounds"))

    def test_sweeping_memory(self):
        with mock.patch("world.memory.available", return_value=True), \
                mock.patch("world.memory._bank_names", return_value=[]), \
                mock.patch("world.memory.orphaned_banks", return_value=[]):
            self.assertIn("edit memory sweep yes",
                          self.call(CmdEdit(), "memory sweep"))

    def test_downloading_the_lexicon(self):
        with mock.patch("world.commonsense.download") as downloading:
            said = self.call(CmdImport(), "commonsense")
        downloading.assert_not_called()
        self.assertIn("import commonsense yes", said)

    def test_abandoning_a_quest(self):
        with mock.patch("world.quests.abandon") as abandoning:
            said = self.call(CmdQuests(), "abandon")
        abandoning.assert_not_called()
        self.assertIn("quests abandon yes", said)

    def test_unless_it_is_turned_off(self):
        self.call(CmdSettings(), "reset_rounds off")
        self.assertIn("Round counts cleared", self.call(CmdReset(), "rounds"))


@tag("world")
class AWordListThroughTheMenu(_InAWorld):

    def test_its_fields_then_keep(self):
        heard = []
        self.account.msg = lambda text="", **kw: heard.append(
            str(text[0] if isinstance(text, tuple) else text))
        menus.open_menu(self.char1, subjects.verb_form("create"),
                        path=["tokens"], interactive_only=False)
        menu = self.account.ndb._evmenu
        for line in ("name", "smell", "entries", "brine | tar", "keep"):
            menu.parse_input(line)
        self.assertIn("This world now keeps", "\n".join(heard))
        self.assertIsNone(self.account.ndb._evmenu)

    def test_a_list_with_no_entries_is_not_kept(self):
        heard = []
        self.account.msg = lambda text="", **kw: heard.append(
            str(text[0] if isinstance(text, tuple) else text))
        menus.open_menu(self.char1, subjects.verb_form("create"),
                        path=["tokens"], interactive_only=False)
        menu = self.account.ndb._evmenu
        menu.parse_input("name")
        menu.parse_input("smell")
        menu.parse_input("keep")
        self.assertIsNotNone(self.account.ndb._evmenu)


@tag("world")
class EditWorldOpensAWay(_InAWorld):

    def test_the_action_is_in_the_editing_form_only(self):
        from commands import world_subject

        editing = menus.Context(self.char1, draft={"mode": "edit",
                                                   "world_id": self.root.id})
        making = menus.Context(self.char1, draft={"mode": "create"})
        self.assertIn("open", [item.key for item in
                               world_subject.WIZARD.items_for(editing)])
        self.assertNotIn("open", [item.key for item in
                                  world_subject.WIZARD.items_for(making)])

    def test_a_world_with_ways_left_says_so(self):
        from commands import world_subject

        with mock.patch("world.worldgen.frontier", return_value=3), \
                mock.patch("world.worldgen.pending_exits", return_value=[]):
            said = world_subject.open_a_way(menus.Context(
                self.char1, draft={"world_id": self.root.id}))
        self.assertIn("still has 3 way(s)", said)


@tag("world")
class PronounsNew(_InAWorld):

    def test_says_where_it_went(self):
        self.assertIn("create pronouns", self.call(CmdPronouns(), "new"))


@tag("unit")
class RetiredInPhaseFour(SimpleTestCase):

    def test_each_says_where_it_went(self):
        for typed, now in (("worldmode always", "settings mode"),
                           ("worldcheck", "view faults"),
                           ("zones", "view zones"),
                           ("rules suggest", "view rules"),
                           ("effects burn", "view effects"),
                           ("npcgen", "create npc"),
                           ("tokens add smell", "create tokens"),
                           ("commonsense fetch", "import commonsense"),
                           ("memcheck sweep", "edit memory"),
                           ("rounds clear", "reset rounds")):
            self.assertIn(now, retired_spelling(typed), typed)
