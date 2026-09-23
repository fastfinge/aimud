"""
Settings: every preference in one register, reached by a command or a menu.

Most of this drives `settings` the way somebody with no menu would -- a whole
line at a time -- because that is the path an agent or a script takes, and
every menu point has to be reachable that way. `InTheMenu` walks the same
settings through the menu. See docs/commands-and-settings.md §5.
"""

from unittest import mock

from django.test import SimpleTestCase, tag

from commands.settings_cmds import CmdSettings
from commands.unknown_cmd import retired_spelling
from tests.base import GameCommandTest
from world import activity, busy, menus, preferences, pronouns, sponsor


class _Settings(GameCommandTest):
    # A preference is kept on the account, so there has to be one.
    accounts = True

    def settings(self, args=""):
        return self.call(CmdSettings(), args)


@tag("world")
class GeneralSettings(_Settings):

    def test_everything_is_listed_with_its_value_and_default(self):
        said = self.settings("list")
        self.assertIn("Still-working notices: every 10 seconds (the default)",
                      said)
        self.assertIn("settings busy", said)
        self.assertIn("Deleting a world: on (the default)", said)

    def test_with_nobody_to_show_a_menu_to_it_lists_them(self):
        self.assertIn("Still-working notices", self.settings(""))

    def test_one_setting_is_shown_with_its_help(self):
        said = self.settings("busy")
        self.assertIn("every 10 seconds", said)
        self.assertIn("still going", said)

    def test_setting_busy_is_kept_where_busy_reads_it(self):
        self.assertIn("every 30 seconds", self.settings("busy 30"))
        self.assertEqual(busy.interval_for(self.char1), 30)

    def test_off(self):
        self.settings("busy off")
        self.assertEqual(busy.interval_for(self.char1), 0)
        self.assertIn("never", self.settings("list"))

    def test_back_to_the_default(self):
        self.settings("busy 30")
        self.settings("busy default")
        self.assertIsNone(busy.chosen(self.account))

    def test_out_of_range_is_refused_and_nothing_changes(self):
        self.assertIn("from 5 to 120", self.settings("busy 2"))
        self.assertIsNone(busy.chosen(self.account))

    def test_a_group_can_be_named_on_the_way(self):
        self.settings("general busy 45")
        self.assertEqual(busy.interval_for(self.char1), 45)

    def test_view_menus(self):
        self.settings("viewmenus close")
        self.assertEqual(menus.view_mode(self.account), menus.CLOSE_VIEW)
        self.settings("viewmenus default")
        self.assertEqual(menus.view_mode(self.account), menus.WALK_AWAY)

    def test_show_commands(self):
        self.settings("showcommands off")
        self.assertFalse(menus.shows_commands(self.account))

    def test_something_that_is_not_a_setting(self):
        self.assertIn("no setting called", self.settings("sparkles 3"))


@tag("world")
class ConfirmationSettings(_Settings):

    def test_one_can_be_turned_off(self):
        self.settings("delete_world off")
        self.assertFalse(menus.confirmation_wanted(self.account, "delete_world"))
        self.assertTrue(menus.confirmation_wanted(self.account, "reset_world"))

    def test_and_on_again(self):
        self.settings("delete_world off")
        self.settings("delete_world on")
        self.assertTrue(menus.confirmation_wanted(self.account, "delete_world"))

    def test_all_at_once(self):
        self.settings("alloff")
        for key, _label, _why in preferences.CONFIRMATIONS:
            self.assertFalse(menus.confirmation_wanted(self.account, key))
        self.settings("allon")
        for key, _label, _why in preferences.CONFIRMATIONS:
            self.assertTrue(menus.confirmation_wanted(self.account, key))


@tag("world")
class TheApi(_Settings):

    def test_a_key_is_kept_and_never_shown_whole(self):
        self.settings("apikey sk-abcdefgh12345678")
        self.assertEqual(self.account.db.openrouter_api_key,
                         "sk-abcdefgh12345678")
        said = self.settings("list")
        self.assertNotIn("sk-abcdefgh12345678", said)
        self.assertIn("sk-a", said)

    def test_clearing_it_asks_first(self):
        self.account.db.openrouter_api_key = "sk-abcdefgh12345678"
        said = self.settings("apikey clear")
        self.assertIn("settings apikey clear yes", said)
        self.assertTrue(self.account.db.openrouter_api_key)
        self.settings("apikey clear yes")
        self.assertFalse(self.account.attributes.has("openrouter_api_key"))

    def test_unless_that_confirmation_is_off(self):
        self.account.db.openrouter_api_key = "sk-abcdefgh12345678"
        self.settings("clear_apikey off")
        self.settings("apikey clear")
        self.assertFalse(self.account.attributes.has("openrouter_api_key"))

    def test_the_address_is_kept_beside_the_key(self):
        self.account.db.openrouter_api_key = "sk-abcdefgh12345678"
        self.account.ndb.openrouter_models_cache = [{"id": "old/model"}]
        said = self.settings("apiurl https://nano-gpt.com/api/v1/")
        self.assertEqual(sponsor.of_account(self.account).base_url,
                         "https://nano-gpt.com/api/v1")
        self.assertIsNone(self.account.ndb.openrouter_models_cache)
        self.assertIn("set that too", said)

    def test_an_address_has_to_be_one(self):
        self.assertIn("starts with https://", self.settings("apiurl nano-gpt"))
        self.assertFalse(self.account.attributes.has("api_base_url"))


@tag("world")
class ChoosingAModel(_Settings):
    """Every job uses tools, so a model that cannot is not offered."""

    def setUp(self):
        super().setUp()
        self.account.db.openrouter_api_key = "sk-abcdefgh12345678"
        self.account.ndb.openrouter_models_cache = [
            {"id": "a/tools", "supported_parameters": ["tools", "seed"]},
            {"id": "b/none", "supported_parameters": ["temperature"]},
            {"id": "c/unlisted"},
        ]

    def job(self, name="dialogue"):
        ctx = menus.Context(self.char1)
        return ctx.child(job=name)

    def test_a_model_that_cannot_use_tools_is_not_offered(self):
        ctx = self.job()
        offered = [choice.value for choice in preferences.MODEL.choices_for(ctx)]
        self.assertEqual(offered, ["a/tools", "c/unlisted"])
        self.assertIn("1 model that cannot use tools is not listed",
                      preferences.MODEL.prompt(ctx))

    def test_nor_can_it_be_chosen_by_typing_it(self):
        said = self.settings("models dialogue model b/none")
        self.assertIn("not one of the choices", said)
        self.assertFalse((self.account.db.ai_models or {}).get("dialogue"))

    def test_a_model_is_chosen_for_one_job(self):
        self.settings("models dialogue model a/tools")
        self.assertEqual(self.account.db.ai_models["dialogue"], "a/tools")
        self.assertEqual(self.account.model_for("dialogue"), "a/tools")

    def test_and_cleared_again(self):
        self.settings("models dialogue model a/tools")
        self.settings("models dialogue model clear")
        self.assertNotIn("dialogue", self.account.db.ai_models)

    def test_a_setting_for_one_job_is_sent_with_it(self):
        self.settings("models dialogue temperature 0.9")
        self.assertEqual(self.account.model_for("dialogue").params,
                         {"temperature": 0.9})

    def test_out_of_range_is_refused(self):
        self.assertIn("cannot go above", self.settings(
            "models dialogue temperature 5"))

    def test_only_the_settings_a_model_takes_are_offered(self):
        self.settings("models dialogue model a/tools")
        self.assertIn("no setting called", self.settings(
            "models dialogue temperature 0.9"))
        self.settings("models dialogue seed 4")
        self.assertEqual(self.account.model_for("dialogue").params, {"seed": 4})

    def test_without_the_list_and_without_a_key_it_says_why(self):
        self.account.ndb.openrouter_models_cache = None
        self.account.attributes.remove("openrouter_api_key")
        self.assertIn("settings apikey", self.settings("models dialogue"))


@tag("world")
class InAWorld(_Settings):

    def setUp(self):
        super().setUp()
        self.room1.db.world_root = self.room1
        self.room1.db.world_description = "A harbour town."
        sponsor.claim(self.room1, self.account)

    def test_you_are_named_here(self):
        self.settings("name Aria")
        self.assertEqual(self.char1.world_name(self.room1), "Aria")

    def test_a_name_that_will_not_do_is_refused(self):
        self.assertIn("at least", self.settings("name A"))

    def test_pronouns_come_from_the_world(self):
        self.assertIn("she/her/hers", self.settings("pronouns she"))
        self.assertEqual(pronouns.of(self.char1, self.room1)["subject"], "she")

    def test_the_world_runs_always_only_once_asked(self):
        said = self.settings("mode always")
        self.assertIn("settings mode always yes", said)
        self.assertEqual(activity.mode(self.room1), activity.NORMAL)
        self.settings("mode always yes")
        self.assertEqual(activity.mode(self.room1), activity.ALWAYS)

    def test_only_its_creator_sees_how_it_runs(self):
        self.room1.db.world_creator = self.account2
        self.assertNotIn("How the world runs", self.settings("list"))
        self.assertIn("no setting called", self.settings("mode always yes"))

    def test_outside_a_world_there_is_no_you_here(self):
        self.room1.attributes.remove("world_root")
        self.assertNotIn("Your name here", self.settings("list"))


@tag("world")
class InTheMenu(_Settings):
    """The same settings, reached by choosing rather than typing."""

    def setUp(self):
        super().setUp()
        self.said = []
        self.account.msg = self._heard

    def _heard(self, text="", **kwargs):
        if isinstance(text, tuple):
            text = text[0]
        self.said.append(str(text))

    def open(self):
        menus.open_menu(self.char1, preferences.SETTINGS,
                        interactive_only=False)

    def type(self, line):
        before = len(self.said)
        self.account.ndb._evmenu.parse_input(line)
        return "\n".join(self.said[before:])

    def test_groups_then_settings_then_a_value(self):
        self.open()
        self.assertIn("1. General", self.said[-1])
        self.assertIn("Still-working notices: every 10 seconds", self.type("1"))
        self.type("busy")
        self.type("30")
        self.assertEqual(busy.interval_for(self.char1), 30)
        self.assertIn("every 30 seconds", "\n".join(self.said[-2:]))

    def test_a_live_setting_does_not_ask_to_be_thrown_away(self):
        self.open()
        self.type("1")
        self.type("1")
        self.type("30")
        self.type("q")
        self.assertIsNone(self.account.ndb._evmenu)

    def test_a_value_that_needs_asking_asks(self):
        self.account.db.openrouter_api_key = "sk-abcdefgh12345678"
        self.open()
        self.type("api")
        self.type("apikey")
        self.assertIn("Remove your API key?", self.type("clear"))
        self.type("no")
        self.assertTrue(self.account.db.openrouter_api_key)
        self.type("clear")
        self.type("yes")
        self.assertFalse(self.account.attributes.has("openrouter_api_key"))

    def test_models_are_fetched_before_their_menu_opens(self):
        from tests.support import immediately

        self.account.db.openrouter_api_key = "sk-abcdefgh12345678"
        listed = [{"id": "a/tools", "supported_parameters": ["tools"]}]
        with immediately(), \
                mock.patch("world.llm.models", return_value=listed):
            self.open()
            said = self.type("models")
        self.assertIn("dialogue:", said)
        self.assertEqual(self.account.ndb.openrouter_models_cache, listed)
        self.type("dialogue")
        self.type("model")
        self.type("1")
        self.assertEqual(self.account.db.ai_models["dialogue"], "a/tools")


@tag("unit")
class RetiredCommands(SimpleTestCase):

    def test_each_says_where_it_went(self):
        self.assertEqual(retired_spelling("busy 30"), "settings busy")
        self.assertEqual(retired_spelling("apikey set sk-1"), "settings apikey")
        self.assertEqual(retired_spelling("models"), "settings models")

    def test_anything_else_is_left_alone(self):
        self.assertEqual(retired_spelling("pry crate"), "")
        self.assertEqual(retired_spelling(""), "")


@tag("world")
class HelpForEachSetting(_Settings):

    def test_every_setting_has_a_topic_of_its_own(self):
        topics = dict(preferences.help_entries())
        self.assertIn("busy", topics)
        self.assertIn("apiurl", topics)
        self.assertIn("delete_world", topics)
        self.assertIn("settings busy", topics["busy"].entrytext)


@tag("world")
class SettingsAsASubject(_Settings):
    """`settings` is short for `edit settings`, and both verbs offer it."""

    def test_edit_settings_is_the_same_as_settings(self):
        from commands.verbs import CmdEdit

        self.call(CmdEdit(), "settings busy 30")
        self.assertEqual(busy.interval_for(self.char1), 30)

    def test_view_settings_lists_them(self):
        from commands.verbs import CmdView

        self.assertIn("Still-working notices", self.call(CmdView(), "settings"))

    def test_the_whole_line_is_forwarded_word_for_word(self):
        """`edit settings <name> <value>` is `settings <name> <value>`."""
        from commands.verbs import CmdEdit

        self.call(CmdEdit(), "settings pagesize 25")
        self.assertEqual(menus.page_size(self.account), 25)
        self.call(CmdEdit(), "settings pagesize default")
        self.assertEqual(menus.page_size(self.account), menus.PAGE_SIZE)

    def test_view_settings_takes_a_name_like_view_effects_does(self):
        from commands.verbs import CmdView

        said = self.call(CmdView(), "settings busy")
        self.assertIn("Still-working notices", said)
        self.assertIn("settings busy", said)

    def test_view_settings_takes_a_group_name_too(self):
        from commands.verbs import CmdView

        said = self.call(CmdView(), "settings general")
        self.assertIn("Still-working notices", said)
        self.assertIn("Choices per page", said)

    def test_view_settings_says_so_when_there_is_no_such_setting(self):
        from commands.verbs import CmdView

        self.assertIn("no setting called", self.call(CmdView(),
                                                     "settings frobnicate"))

    def test_edit_and_view_both_offer_it(self):
        from commands import subjects

        ctx = menus.Context(self.char1)
        for verb in ("edit", "view"):
            keys = [item.key for item in
                    subjects.verb_form(verb).items_for(ctx)]
            self.assertIn("settings", keys, verb)


@tag("world")
class SetIsTheShortSpelling(_Settings):
    """`set` reaches the settings, without taking the word from a world."""

    def test_it_changes_a_setting(self):
        command = CmdSettings()
        command.cmdname = "set"
        self.assertIn("25 choices at a time",
                      self.call(command, "pagesize 25", cmdstring="set"))
        self.assertEqual(menus.page_size(self.account), 25)

    def test_typed_alone_or_before_a_setting_it_is_ours(self):
        command = CmdSettings()
        for args in ("", "list", "pagesize", "pagesize 25", "general",
                     "mode always"):
            self.assertTrue(command.claims_input("set", args), args)

    def test_before_anything_else_it_is_left_for_the_world(self):
        command = CmdSettings()
        for args in ("the table", "a trap", "the dial to three"):
            self.assertFalse(command.claims_input("set", args), args)

    def test_the_long_spellings_always_claim_what_they_matched(self):
        command = CmdSettings()
        for name in ("settings", "setting"):
            self.assertTrue(command.claims_input(name, "the table"), name)

    def test_every_setting_is_a_word_it_answers_to(self):
        words = preferences.setting_words()
        for group, field in preferences.static_fields():
            self.assertIn(field.key, words, field.key)
            self.assertIn(group, words, group)


@tag("world")
class ChoicesPerPageSetting(_Settings):

    def test_a_number(self):
        self.assertIn("25 choices at a time", self.settings("pagesize 25"))
        self.assertEqual(menus.page_size(self.account), 25)

    def test_nought_is_all_at_once(self):
        self.assertIn("every choice at once", self.settings("pagesize 0"))
        self.assertEqual(menus.page_size(self.account), 0)
        self.assertIn("Choices per page: all at once", self.settings("list"))

    def test_back_to_the_default(self):
        self.settings("pagesize 0")
        self.settings("pagesize default")
        self.assertEqual(menus.page_size(self.account), menus.PAGE_SIZE)
        self.assertIn("Choices per page: 10 at a time (the default)",
                      self.settings("list"))

    def test_not_a_number(self):
        self.assertIn("0 for all of them", self.settings("pagesize lots"))
        self.assertIn("0 or more", self.settings("pagesize -3"))
