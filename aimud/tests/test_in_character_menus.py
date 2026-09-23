"""
The in-character commands, typed on their own: goal, remember, quests, score,
name and pronouns -- and `choosing.ask`, which puts a choice up as a menu.

Each one did something with no arguments before, and the old default is now
the first thing its menu offers. docs/commands-and-settings.md §7.2.
"""

from unittest import mock

from django.test import tag

from commands.goal_cmds import CmdGoal
from commands.memory_cmds import CmdRemember
from commands.name_cmds import CmdName
from commands.quest_cmds import CmdQuests
from commands.trait_cmds import CmdScore, _row
from tests.base import GameCommandTest
from world import choosing, menus


class _Menus(GameCommandTest):
    """Somebody connected, so bare commands open menus."""

    def setUp(self):
        super().setUp()
        self.heard = []
        self.char1.msg = self._heard
        patcher = mock.patch.object(menus, "interactive", return_value=True)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _heard(self, text="", **kwargs):
        self.heard.append(str(text[0] if isinstance(text, tuple) else text))

    def bare(self, command):
        command.caller = self.char1
        command.args = ""
        command.session = None
        command.parse()
        command.func()
        return self.heard[-1] if self.heard else ""

    def type(self, line):
        before = len(self.heard)
        self.char1.ndb._evmenu.parse_input(line)
        return "\n".join(self.heard[before:])

    @property
    def is_open(self):
        return self.char1.ndb._evmenu is not None


@tag("world")
class Goal(_Menus):

    def setUp(self):
        super().setUp()
        self.room1.db.is_ai_room = True

    def test_with_a_goal_giving_it_up_comes_first(self):
        self.char1.db.goal = [{"subject": "actor", "at": "somewhere"}]
        with mock.patch("world.goals.describe", return_value="be somewhere"):
            shown = self.bare(CmdGoal())
        self.assertIn("You are trying to be somewhere.", shown)
        self.assertIn("1. Give up your goal (the default)", shown)
        with mock.patch("world.hints.describe_goal", return_value="be there"):
            self.type("1")
        self.assertFalse(self.char1.db.goal)
        self.assertFalse(self.is_open)

    def test_a_new_goal_is_typed_and_worked_out(self):
        with mock.patch("world.quest_gen.formalise_goal") as formalising, \
                mock.patch("world.sponsor.of") as of:
            of.return_value.key.return_value = "sk-test"
            self.bare(CmdGoal())
            self.type("1")
            self.type("go to the library")
        self.assertEqual(formalising.call_args[0][2], "go to the library")
        self.assertFalse(self.is_open)

    def test_goal_clear_is_what_bare_goal_used_to_do(self):
        self.char1.db.goal = [{"subject": "actor", "at": "somewhere"}]
        with mock.patch("world.hints.describe_goal", return_value="be there"):
            self.call(CmdGoal(), "clear")
        self.assertFalse(self.char1.db.goal)

    def test_goal_next_with_no_goal(self):
        self.assertIn("no goal set", self.call(CmdGoal(), "next"))


@tag("world")
class Remember(_Menus):

    def test_it_asks_the_question_and_asks_it(self):
        with mock.patch("commands.memory_cmds.recall") as recalling:
            shown = self.bare(CmdRemember())
            self.assertIn("What do you want to remember?", shown)
            self.type("have I met Cherrie before?")
        recalling.assert_called_once_with(self.char1,
                                          "have I met Cherrie before?")
        self.assertFalse(self.is_open)


@tag("world")
class Quests(_Menus):

    def test_the_list_then_only_what_applies(self):
        with mock.patch("commands.quest_cmds.listing",
                        return_value="You have no quests."), \
                mock.patch("world.quests.offered_to", return_value=None), \
                mock.patch("world.quests.current", return_value=None):
            shown = self.bare(CmdQuests())
        self.assertIn("You have no quests.", shown)
        self.assertIn("1 What to do next", shown)
        self.assertNotIn("Accept", shown)

    def test_an_offer_can_be_answered_by_number(self):
        with mock.patch("commands.quest_cmds.listing", return_value="An offer."), \
                mock.patch("world.quests.offered_to", return_value={"id": 1}), \
                mock.patch("world.quests.current", return_value=None), \
                mock.patch("commands.quest_cmds.answer",
                           return_value="You accept.") as answering:
            shown = self.bare(CmdQuests())
            self.assertIn("2 Accept the offer", shown)
            self.assertIn("You accept.", self.type("2"))
        answering.assert_called_once_with(self.char1, "accept")


@tag("world")
class Score(_Menus):

    def test_a_row_reads_as_words_not_dots(self):
        self.assertEqual(_row("composure", "12"), "  |wcomposure|n: 12")

    def test_with_nothing_measured_it_says_so(self):
        self.assertIn("Nothing about you is measured yet",
                      self.bare(CmdScore()))

    def test_each_trait_is_a_choice(self):
        trait = mock.Mock(value=12, max=None, rate=0)
        trait.name = "Composure"
        with mock.patch("world.traits.all_of",
                        return_value=[("composure", trait)]), \
                mock.patch("world.traits.vocabulary", return_value={}), \
                mock.patch("world.traits._worded", return_value=""), \
                mock.patch("world.gear.describe", return_value=""):
            shown = self.bare(CmdScore())
        self.assertIn("|wComposure|n: 12", shown)
        self.assertIn("One of them: 1 Composure.", shown)


@tag("world")
class ScoreAsASubject(_Menus):
    """`view score` is `score`, and `view score <trait>` is `score <trait>`."""

    def _one_trait(self):
        trait = mock.Mock(value=12, max=None, rate=0)
        trait.name = "Composure"
        return mock.patch("world.traits.all_of",
                          return_value=[("composure", trait)]), \
            mock.patch("world.traits.vocabulary", return_value={}), \
            mock.patch("world.traits._worded", return_value=""), \
            mock.patch("world.gear.describe", return_value="")

    def _view(self, args):
        from commands.verbs import CmdView

        command = CmdView()
        command.caller = self.char1
        command.args = args
        command.session = None
        command.parse()
        command.func()
        return self.heard[-1] if self.heard else ""

    def test_view_score_shows_the_whole_score(self):
        for patcher in self._one_trait():
            patcher.start()
            self.addCleanup(patcher.stop)
        self.assertIn("|wComposure|n: 12", self._view("score"))

    def test_view_score_takes_a_trait_the_way_score_does(self):
        for patcher in self._one_trait():
            patcher.start()
            self.addCleanup(patcher.stop)
        said = self._view("score composure")
        self.assertIn("|wComposure|n: 12", said)
        # One trait, not the menu of all of them.
        self.assertNotIn("One of them:", said)

    def test_view_offers_it(self):
        from commands import subjects

        keys = [item.key for item in
                subjects.verb_form("view").items_for(menus.Context(self.char1))]
        self.assertIn("score", keys)


@tag("world")
class NameAndPronouns(_Menus):
    accounts = True

    def setUp(self):
        super().setUp()
        self.room1.db.world_root = self.room1
        self.account.msg = self._heard

    def test_bare_name_opens_the_setting(self):
        self.bare(CmdName())
        menu = self.account.ndb._evmenu
        self.assertEqual(menu.top.item.key, "name")
        self.assertIn("Your name here", self.heard[-1])


@tag("world")
class ChoosingAsAMenu(_Menus):

    def test_with_a_callback_it_is_a_menu_and_the_choice_comes_back(self):
        chosen = []
        choosing.ask(self.char1, "her", ["Jessica", "Britney"],
                     on_chosen=chosen.append)
        self.assertIn("Which her do you mean?", self.heard[-1])
        self.assertIn("2. Britney", self.heard[-1])
        self.type("2")
        self.assertEqual(chosen, ["Britney"])
        self.assertFalse(self.is_open)

    def test_by_name_too(self):
        chosen = []
        choosing.ask(self.char1, "her", ["Jessica", "Britney"],
                     on_chosen=chosen.append)
        self.type("jessica")
        self.assertEqual(chosen, ["Jessica"])

    def test_without_a_callback_it_is_still_the_question(self):
        choosing.ask(self.char1, "her", ["Jessica", "Britney"])
        self.assertEqual(self.heard[-1],
                         "Which her do you mean -- Jessica or Britney?")
        self.assertFalse(self.is_open)
