"""
`~`: a model fills a menu field in, and `?`: a menu reads the help system.

Every model reply here is scripted (`tests.support.replying`), so this costs
nothing. What is tested is the contract: what the model is shown and not
shown, that its answer passes the field's own check, and that nothing is
written until the player keeps it. docs/commands-and-settings.md §6 and §9.
"""

from unittest import mock

from django.test import SimpleTestCase, tag

from commands.verbs import CmdCreate
from tests.base import GameCommandTest, GameTest
from tests.support import FakeSponsor, immediately, replying, tool_call, tool_reply
from world import menus, preferences, suggesting


def a_form(sponsor=None):
    """A form with one of each field `~` can fill, and a secret it cannot."""
    return menus.Form(
        key="ship", title="A ship", intro="Somewhere to live aboard.",
        sponsor=(lambda ctx: sponsor) if sponsor else None,
        context=lambda ctx: "The world is a drowned city.",
        items=[
            menus.Field("name", "Name", suggestible=True,
                        help="What the ship is called."),
            menus.Field("crew", "Crew", kind=menus.NUMBER, minimum=1,
                        maximum=40, suggestible=True, help="How many aboard."),
            menus.Field("hull", "Hull", kind=menus.CHOICE, suggestible=True,
                        choices=[menus.Choice("wood", "Wooden"),
                                 menus.Choice("iron", "Iron")]),
            menus.Field("code", "Launch code", kind=menus.SECRET,
                        suggestible=True, help="Never to be told."),
            menus.Field("notes", "Notes", help="Only the player writes these."),
        ])


@tag("unit")
class WhatCanBeFilled(SimpleTestCase):

    def test_a_secret_never_is(self):
        field = menus.Field("key", "Key", kind=menus.SECRET, suggestible=True)
        self.assertFalse(field.suggestible)

    def test_menus_is_a_job_with_its_own_model(self):
        self.assertIn("menus", preferences.JOB_NAMES)


@tag("world")
class WhatTheModelIsShown(GameTest):

    def setUp(self):
        super().setUp()
        self.ctx = menus.Context(self.char1, draft={"name": "Heron",
                                                    "code": "1234"})
        self.form = a_form()

    def test_the_form_every_field_and_what_it_holds(self):
        fields = suggesting.fillable(self.ctx, self.form)
        sent = "\n".join(m["content"] for m in
                         suggesting.prompt(self.ctx, self.form, fields[1:2]))
        self.assertIn("A ship", sent)
        self.assertIn("drowned city", sent)
        self.assertIn("name (Name): What the ship is called.", sent)
        self.assertIn("now: Heron", sent)
        self.assertIn("options: Wooden, Iron", sent)
        self.assertIn("Fill in: crew.", sent)

    def test_never_a_secret_not_even_its_name(self):
        fields = suggesting.fillable(self.ctx, self.form)
        sent = "\n".join(m["content"] for m in
                         suggesting.prompt(self.ctx, self.form, fields))
        self.assertNotIn("1234", sent)
        self.assertNotIn("Launch code", sent)
        self.assertNotIn("code", [field.key for field in fields])

    def test_the_tool_closes_a_choice_to_its_options(self):
        fields = suggesting.fillable(self.ctx, self.form)
        tool = suggesting.fill_tool(self.ctx, fields)
        properties = tool.parameters["properties"]
        self.assertEqual(properties["hull"]["enum"], ["wood", "iron"])
        self.assertEqual(properties["crew"]["maximum"], 40)
        self.assertEqual(sorted(tool.parameters["required"]),
                         ["crew", "hull", "name"])


@tag("world")
class Asking(GameTest):

    def setUp(self):
        super().setUp()
        self.ctx = menus.Context(self.char1, draft={})
        self.form = a_form(FakeSponsor())
        self.fields = suggesting.fillable(self.ctx, self.form)
        self.got = []

    def ask(self, *replies):
        with immediately(), replying(*replies) as recorder:
            suggesting.fill(self.ctx, self.form, self.fields,
                            on_done=lambda values: self.got.append(values),
                            on_error=lambda why: self.got.append(why))
        return recorder

    def test_a_good_answer_is_every_value_read_by_its_field(self):
        self.ask(tool_reply(tool_call("fill", name="Heron", crew=12,
                                      hull="iron")))
        self.assertEqual(self.got, [{"name": "Heron", "crew": 12,
                                     "hull": "iron"}])

    def test_a_value_the_field_refuses_is_sent_back_to_be_fixed(self):
        recorder = self.ask(
            tool_reply(tool_call("fill", name="Heron", crew=900, hull="iron")),
            tool_reply(tool_call("fill", name="Heron", crew=9, hull="iron")))
        self.assertEqual(recorder.count, 2)
        self.assertIn("at most 40", recorder.sent(1))
        self.assertEqual(self.got[0]["crew"], 9)

    def test_it_is_asked_as_the_menus_job(self):
        sponsor = FakeSponsor()
        self.form = a_form(sponsor)
        with mock.patch.object(sponsor, "model_for",
                               wraps=sponsor.model_for) as asked:
            self.ask(tool_reply(tool_call("fill", name="Heron", crew=2,
                                          hull="wood")))
        asked.assert_called_with("menus")

    def test_with_no_key_nothing_is_asked(self):
        self.form = a_form(FakeSponsor(key=""))
        recorder = self.ask(tool_reply(tool_call("fill", name="Heron")))
        self.assertEqual(recorder.count, 0)
        self.assertIsInstance(self.got[0], str)


class _Menu(GameTest):

    def setUp(self):
        super().setUp()
        self.heard = []
        self.char1.msg = lambda text="", **kw: self.heard.append(
            str(text[0] if isinstance(text, tuple) else text))

    def type(self, line, *replies):
        with immediately(), replying(*replies) as recorder:
            self.char1.ndb._evmenu.parse_input(line)
        return recorder

    @property
    def draft(self):
        return self.char1.ndb._evmenu.stack[0].ctx.draft


@tag("world")
class InAMenu(_Menu):

    def setUp(self):
        super().setUp()
        menus.open_menu(self.char1, a_form(FakeSponsor()),
                        interactive_only=False)

    def test_the_keys_line_offers_it(self):
        self.assertIn("~ fills one in for you", self.heard[-1])

    def test_tilde_asks_which(self):
        self.type("~")
        self.assertIn("Fill in which?", self.heard[-1])
        self.assertIn("All empty fields", self.heard[-1])

    def test_a_proposal_is_shown_and_nothing_written_until_yes(self):
        self.type("~1", tool_reply(tool_call("fill", name="Heron")))
        self.assertIn("Heron", self.heard[-1])
        self.assertIn("1. No (the default)", self.heard[-1])
        self.assertNotIn("name", self.draft)
        self.type("yes")
        self.assertEqual(self.draft["name"], "Heron")

    def test_no_keeps_what_was_there(self):
        self.type("~ name", tool_reply(tool_call("fill", name="Heron")))
        self.type("no")
        self.assertNotIn("name", self.draft)

    def test_try_again_asks_again(self):
        self.type("~1", tool_reply(tool_call("fill", name="Heron")))
        recorder = self.type("3", tool_reply(tool_call("fill", name="Osprey")))
        self.assertEqual(recorder.count, 1)
        self.assertIn("Osprey", self.heard[-1])

    def test_all_empty_fields_in_one_conversation(self):
        self.draft["name"] = "Heron"
        recorder = self.type("~ all", tool_reply(
            tool_call("fill", crew=6, hull="wood")))
        self.assertEqual(recorder.count, 1)
        self.assertNotIn("Fill in: name", recorder.sent(0))
        self.type("2")
        self.assertEqual((self.draft["crew"], self.draft["hull"]), (6, "wood"))

    def test_from_inside_a_field_it_fills_that_field(self):
        self.type("1")
        self.type("~", tool_reply(tool_call("fill", name="Heron")))
        self.type("yes")
        self.assertEqual(self.draft["name"], "Heron")
        self.assertEqual(self.char1.ndb._evmenu.top.kind, "form")

    def test_a_field_that_is_not_suggestible_says_so(self):
        self.type("5")
        self.type("~")
        self.assertIn("Nothing here can be filled in", self.heard[-1])

    def test_without_asking_when_that_confirmation_is_off(self):
        with mock.patch.object(menus, "confirmation_wanted",
                               side_effect=lambda who, key: key != "suggestion"):
            self.type("~1", tool_reply(tool_call("fill", name="Heron")))
        self.assertEqual(self.draft["name"], "Heron")

    def test_an_answer_after_the_menu_closed_is_not_used(self):
        caught = {}

        def fill(ctx, form, fields, on_done, on_error, wait=None):
            caught["done"] = on_done

        with mock.patch.object(suggesting, "fill", fill):
            self.char1.ndb._evmenu.parse_input("~1")
        self.char1.ndb._evmenu.parse_input("q")
        caught["done"]({"name": "Heron"})
        self.assertIn("arrived after the menu closed", self.heard[-1])


@tag("world")
class AFormWithNobodyToPay(_Menu):

    def test_has_no_tilde(self):
        menus.open_menu(self.char1, a_form(), interactive_only=False)
        self.assertNotIn("~", self.heard[-1])
        self.type("~")
        self.assertIn("Nothing here can be filled in", self.heard[-1])


@tag("world")
class ANewWorldFromADescription(GameCommandTest):
    """The done-when of phase 5: a description is enough to draft the rest."""

    accounts = True

    def test_title_and_guidance_are_filled_from_the_description(self):
        self.account.db.openrouter_api_key = "sk-abcdefgh12345678"
        heard = []
        self.account.msg = lambda text="", **kw: heard.append(
            str(text[0] if isinstance(text, tuple) else text))
        with mock.patch.object(menus, "interactive", return_value=True):
            self.call(CmdCreate(), "world A drowned city ruled by herons")
        menu = self.account.ndb._evmenu
        values = dict(title="Heronry", name="Wade", looks="Wet to the knee.",
                      rooms="Everything is half underwater.",
                      npcs="Herons speak; people listen.",
                      items="Nothing made of paper survives.",
                      dialogue="Nobody raises their voice.",
                      validation="Fire does not burn below the waterline.")
        with immediately(), replying(tool_reply(tool_call("fill", **values))) \
                as recorder:
            menu.parse_input("~ all")
        self.assertIn("A drowned city ruled by herons", recorder.sent(0))
        menu.parse_input("yes")
        draft = menu.stack[-1].ctx.draft
        self.assertEqual(draft["title"], "Heronry")
        self.assertEqual(draft["guidance"]["rooms"],
                         "Everything is half underwater.")
        self.assertIn("Title: Heronry", heard[-1])


@tag("world")
class HelpFromTheHelpSystem(GameTest):
    """`?` reads what `help` would say, so the two cannot disagree."""

    def test_a_command(self):
        from commands.help_cmds import topic_text

        self.assertIn("Change something you made", topic_text(self.char1,
                                                              "edit"))

    def test_a_setting(self):
        from commands.help_cmds import topic_text

        self.assertIn("still going", topic_text(self.char1, "busy"))

    def test_nothing(self):
        from commands.help_cmds import topic_text

        self.assertEqual(topic_text(self.char1, "no such topic at all"), "")

    def test_an_item_with_no_help_of_its_own_reads_its_topic(self):
        item = menus.Action("x", "Notices", run=lambda ctx: None, topic="busy")
        self.assertIn("still going", item.help_for(menus.Context(self.char1)))

    def test_help_of_its_own_comes_first(self):
        item = menus.Action("x", "Notices", run=lambda ctx: None,
                            help="Mine.", topic="busy")
        self.assertEqual(item.help_for(menus.Context(self.char1)), "Mine.")
