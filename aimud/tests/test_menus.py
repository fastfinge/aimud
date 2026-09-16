"""
The menu engine: the keys every menu shares, and how each kind of form ends.

Driven the way a player drives one -- a line of input at a time, reading back
what was sent -- through `Driving.type`, rather than by calling node
functions, because the keys are the contract and node functions are not.
See docs/commands-and-settings.md §3.
"""

from unittest import mock

from django.test import SimpleTestCase, tag

from tests.base import GameTest
from world import menus


class Recorder(menus.Presenter):
    """A presenter that writes down every hook it is called with."""

    def __init__(self):
        self.calls = []

    def opened(self, menu):
        self.calls.append(("opened",))

    def shown(self, menu, text):
        self.calls.append(("shown",))
        return text

    def chose(self, menu, item):
        self.calls.append(("chose", item.key))

    def refused(self, menu, text):
        self.calls.append(("refused",))

    def confirmed(self, menu, key, answer):
        self.calls.append(("confirmed", key, answer))

    def closed(self, menu, why):
        self.calls.append(("closed", why))

    def named(self, name):
        return [call for call in self.calls if call[0] == name]


class Driving(GameTest):
    """A character with a menu open, and everything sent to them kept."""

    def setUp(self):
        super().setUp()
        self.said = []
        self.char1.msg = self._heard
        self.presenter = Recorder()
        patcher = mock.patch.object(menus, "PRESENTER", self.presenter)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _heard(self, text="", **kwargs):
        if isinstance(text, tuple):
            text = text[0]
        self.said.append(str(text))

    def open(self, form, **kwargs):
        kwargs.setdefault("interactive_only", False)
        self.menu = menus.open_menu(self.char1, form, **kwargs)
        return self.menu

    def type(self, line):
        """Send one line to whatever menu is open, and return what came back."""
        before = len(self.said)
        menu = self.char1.ndb._evmenu
        self.assertIsNotNone(menu, f"no menu is open to type {line!r} into")
        menu.parse_input(line)
        return "\n".join(self.said[before:])

    @property
    def last(self):
        return self.said[-1] if self.said else ""

    @property
    def is_open(self):
        return self.char1.ndb._evmenu is not None


def a_form(**kwargs):
    """A small edit form with one of each thing."""
    ran = kwargs.pop("ran", [])
    items = [
        menus.Field("title", "Title", help="What world listings show."),
        menus.Field("size", "Size", kind=menus.NUMBER, minimum=1, maximum=9),
        menus.Action("go", "Generate it", run=lambda ctx: ran.append("go")
                     or "Generated.", after=menus.CLOSE,
                     command=lambda ctx: "create world"),
        menus.Action("wipe", "Wipe it", run=lambda ctx: ran.append("wipe")
                     or "Wiped.", confirm="delete_world",
                     question="Wipe everything?"),
    ]
    return menus.Form(key="test", title="A world", items=items, **kwargs)


@tag("unit")
class NamingChoices(SimpleTestCase):

    def test_a_choice_may_not_take_a_key_every_menu_uses(self):
        for word in ("b", "quit", "look", "?", "next"):
            with self.assertRaises(ValueError):
                menus.Action(word, "Anything", run=lambda ctx: None)

    def test_nor_by_an_alias(self):
        with self.assertRaises(ValueError):
            menus.Action("fine", "Anything", run=lambda ctx: None,
                         aliases=("q",))


@tag("world")
class EditingAForm(Driving):

    def test_the_form_lists_its_choices_by_number_with_values(self):
        self.open(a_form(), draft={"title": "Harbour"})
        shown = self.last
        self.assertIn("1. Title: Harbour", shown)
        self.assertIn("2. Size: not set", shown)
        self.assertIn("3. Generate it", shown)
        self.assertIn("b goes back", shown)

    def test_nothing_rules_lines_around_it(self):
        """EvMenu's borders are read aloud one underscore at a time."""
        self.open(a_form())
        self.assertNotIn("___", self.last)

    def test_a_field_is_set_by_number_then_value(self):
        self.open(a_form())
        self.assertIn("Type the title", self.type("1"))
        self.type("Harbour town")
        self.assertEqual(self.menu.stack[0].ctx.draft["title"], "Harbour town")
        self.assertIn("1. Title: Harbour town", self.last)

    def test_or_by_name(self):
        self.open(a_form())
        self.type("title")
        self.assertIn("Type the title", self.last)

    def test_a_bad_value_is_refused_and_the_field_stays_open(self):
        self.open(a_form())
        self.type("2")
        self.assertIn("at most 9", self.type("12"))
        self.type("4")
        self.assertEqual(self.menu.stack[0].ctx.draft["size"], 4)

    def test_a_slash_types_a_key_as_text(self):
        self.open(a_form())
        self.type("1")
        self.type("/b")
        self.assertEqual(self.menu.stack[0].ctx.draft["title"], "b")

    def test_back_leaves_a_field_unchanged(self):
        self.open(a_form(), draft={"title": "Harbour"})
        self.type("1")
        self.type("b")
        self.assertEqual(self.menu.stack[0].ctx.draft["title"], "Harbour")
        self.assertEqual(len(self.menu.stack), 1)

    def test_clear_removes_a_value(self):
        self.open(a_form(), draft={"title": "Harbour"})
        self.type("1")
        self.type("clear")
        self.assertNotIn("title", self.menu.stack[0].ctx.draft)

    def test_look_draws_it_again(self):
        self.open(a_form())
        self.assertIn("1. Title", self.type("l"))

    def test_anything_else_is_refused_with_what_to_do(self):
        self.open(a_form())
        self.assertIn("l lists them again", self.type("fly"))
        self.assertEqual(self.presenter.named("refused"), [("refused",)])

    def test_quit_closes_it(self):
        self.open(a_form())
        self.type("q")
        self.assertFalse(self.is_open)
        self.assertIn(("closed", "quit"), self.presenter.calls)

    def test_back_from_the_top_closes_it(self):
        self.open(a_form())
        self.type("b")
        self.assertFalse(self.is_open)

    def test_an_action_that_finishes_closes_it_and_says_how_to_type_it(self):
        ran = []
        self.open(a_form(ran=ran))
        said = self.type("3")
        self.assertEqual(ran, ["go"])
        self.assertIn("Generated.", said)
        self.assertIn("Next time you can type |wcreate world|n", said)
        self.assertFalse(self.is_open)
        self.assertIn(("closed", "finished"), self.presenter.calls)

    def test_not_if_the_player_turned_that_off(self):
        self.open(a_form())
        with mock.patch.object(menus, "shows_commands", return_value=False):
            self.assertNotIn("Next time", self.type("3"))

    def test_path_opens_it_partway_and_back_still_climbs_out(self):
        self.open(a_form(), path=["title"])
        self.assertIn("Type the title", self.last)
        self.type("b")
        self.assertIn("1. Title", self.last)


@tag("world")
class Confirming(Driving):

    def test_no_comes_first(self):
        self.open(a_form())
        said = self.type("4")
        self.assertIn("Wipe everything?", said)
        self.assertLess(said.index("1. No"), said.index("2. Yes"))

    def test_yes_does_it(self):
        ran = []
        self.open(a_form(ran=ran))
        self.type("4")
        self.type("2")
        self.assertEqual(ran, ["wipe"])
        self.assertIn(("confirmed", "delete_world", True), self.presenter.calls)

    def test_no_does_not(self):
        ran = []
        self.open(a_form(ran=ran))
        self.type("4")
        self.assertIn("Nothing changed", self.type("no"))
        self.assertEqual(ran, [])
        self.assertEqual(len(self.menu.stack), 1)

    def test_turned_off_it_is_not_asked(self):
        ran = []
        self.open(a_form(ran=ran))
        with mock.patch.object(menus, "confirmation_wanted",
                               return_value=False):
            self.type("4")
        self.assertEqual(ran, ["wipe"])

    def test_quitting_with_changes_asks_first(self):
        self.open(a_form())
        self.type("1")
        self.type("Harbour")
        self.assertIn("Throw away", self.type("q"))
        self.assertTrue(self.is_open)
        self.type("1")
        self.assertTrue(self.is_open)
        self.type("q")
        self.type("yes")
        self.assertFalse(self.is_open)

    def test_quitting_with_nothing_changed_does_not(self):
        self.open(a_form())
        self.type("q")
        self.assertFalse(self.is_open)

    def test_a_command_can_ask_outside_any_menu(self):
        done = []
        menus.confirm(self.char1, "Delete it?", lambda: done.append(1),
                      key="delete_world", interactive_only=False)
        self.assertIn("1. No", self.last)
        self.type("yes")
        self.assertEqual(done, [1])
        self.assertFalse(self.is_open)

    def test_and_no_leaves_it_alone(self):
        done = []
        menus.confirm(self.char1, "Delete it?", lambda: done.append(1),
                      interactive_only=False)
        self.type("1")
        self.assertEqual(done, [])
        self.assertFalse(self.is_open)

    def test_nobody_connected_is_told_how_to_confirm_by_typing(self):
        done = []
        menus.confirm(self.char1, "Delete it?", lambda: done.append(1),
                      command="delete world 2")
        self.assertIn("delete world 2 yes", self.last)
        self.assertEqual(done, [])


@tag("world")
class Helping(Driving):

    def test_question_mark_and_a_number_explains_that_choice(self):
        self.open(a_form())
        self.assertIn("What world listings show.", self.type("?1"))

    def test_or_a_name(self):
        self.open(a_form())
        self.assertIn("What world listings show.", self.type("? title"))

    def test_with_one_choice_that_has_help_it_goes_straight_there(self):
        self.open(a_form())
        self.assertIn("What world listings show.", self.type("?"))

    def test_with_several_it_asks_which(self):
        form = a_form()
        form.items[1].help = "How many rooms."
        self.open(form)
        self.assertIn("Help on which?", self.type("?"))
        self.assertIn("How many rooms.", self.type("2"))
        self.assertEqual(len(self.menu.stack), 1)

    def test_inside_a_field_it_explains_the_field(self):
        self.open(a_form())
        self.type("1")
        self.assertIn("What world listings show.", self.type("?"))

    def test_the_tilde_is_a_key_even_before_it_does_anything(self):
        self.open(a_form())
        self.type("1")
        self.assertIn("filled in", self.type("~"))
        self.assertNotIn("title", self.menu.stack[0].ctx.draft)


def a_long_list(count=25):
    names = [f"model-{index:02}" for index in range(count)]
    return menus.Form(key="long", title="Models", items=[
        menus.Action(name, name, run=lambda ctx, name=name: f"chose {name}")
        for name in names
    ])


@tag("world")
class LongLists(Driving):

    def test_a_long_list_is_shown_a_page_at_a_time(self):
        self.open(a_long_list())
        self.assertIn("10. model-09", self.last)
        self.assertNotIn("11. model-10", self.last)
        self.assertIn("Page 1 of 3", self.last)
        self.assertIn("11. model-10", self.type("n"))

    def test_numbers_are_the_same_whichever_page_is_showing(self):
        self.open(a_long_list())
        self.type("n")
        self.assertIn("chose model-00", self.type("1"))

    def test_typing_filters_it(self):
        self.open(a_long_list())
        said = self.type("model-2")
        self.assertIn("1. model-20", said)
        self.assertIn("5 matches", said)
        self.assertIn("chose model-21", self.type("2"))

    def test_an_empty_line_clears_the_filter(self):
        self.open(a_long_list())
        self.type("model-2")
        self.assertIn("1. model-00", self.type(""))

    def test_a_slash_filters_for_a_key(self):
        form = menus.Form(key="letters", title="Letters", items=[
            menus.Action(f"item{index}", f"{letter} item", run=lambda ctx: "")
            for index, letter in enumerate("abcdefghijklmnop")
        ])
        self.open(form)
        said = self.type("/b")
        self.assertIn("1. b item", said)
        self.assertTrue(self.is_open)

    def test_a_short_list_does_not_filter(self):
        self.open(a_form())
        self.assertIn("l lists them again", self.type("tit"))


def a_score(shown=None):
    """A view form: what score would be."""
    return menus.Form(
        key="score", title="Your score", kind=menus.VIEW,
        intro="Composure 12\nStamina 8",
        items=[
            menus.Action("composure", "composure",
                         run=lambda ctx: "Composure is 12, from training.",
                         command=lambda ctx: "score composure"),
            menus.Action("stamina", "stamina",
                         run=lambda ctx: "Stamina is 8.",
                         command=lambda ctx: "score stamina"),
        ])


@tag("world")
class ViewMenus(Driving):

    def test_it_shows_what_it_is_for_straight_away_with_its_choices(self):
        self.open(a_score())
        self.assertIn("Composure 12", self.last)
        self.assertIn("For one of them: 1 composure, 2 stamina.", self.last)

    def test_a_number_shows_that_one_and_draws_nothing_else(self):
        self.open(a_score())
        said = self.type("2")
        self.assertEqual(said, "Stamina is 8.")
        self.assertTrue(self.is_open)

    def test_anything_else_closes_it_and_runs_as_a_command(self):
        self.open(a_score())
        with mock.patch.object(self.char1, "execute_cmd") as ran:
            self.type("north")
        self.assertFalse(self.is_open)
        ran.assert_called_once()
        self.assertEqual(ran.call_args[0][0], "north")
        self.assertIn(("closed", "walked away"), self.presenter.calls)

    def test_look_means_look_not_show_the_menu_again(self):
        self.open(a_score())
        with mock.patch.object(self.char1, "execute_cmd") as ran:
            self.type("l")
        self.assertEqual(ran.call_args[0][0], "l")

    def test_quit_closes_it_and_never_reaches_the_quit_command(self):
        """Handed on, `quit` would disconnect the player."""
        self.open(a_score())
        with mock.patch.object(self.char1, "execute_cmd") as ran:
            self.type("quit")
        self.assertFalse(self.is_open)
        ran.assert_not_called()

    def test_in_close_mode_no_menu_opens_and_choices_are_commands(self):
        with mock.patch.object(menus, "view_mode",
                               return_value=menus.CLOSE_VIEW):
            self.assertIsNone(self.open(a_score()))
        self.assertFalse(self.is_open)
        self.assertIn("Composure 12", self.last)
        self.assertIn("|wscore composure|n", self.last)

    def test_in_stay_mode_it_holds_input_until_quit(self):
        with mock.patch.object(menus, "view_mode",
                               return_value=menus.STAY_OPEN):
            self.open(a_score())
            with mock.patch.object(self.char1, "execute_cmd") as ran:
                self.assertIn("not one of the choices", self.type("north"))
                self.assertIn("For one of them", self.type("1"))
                self.type("q")
        ran.assert_not_called()
        self.assertFalse(self.is_open)


@tag("world")
class WhoIsShownAMenu(Driving):

    def test_nobody_connected_is_told_the_commands_instead(self):
        self.assertIsNone(menus.open_menu(self.char1, a_form()))
        self.assertFalse(self.is_open)
        self.assertIn("A world", self.last)
        self.assertIn("|wcreate world|n: Generate it", self.last)

    def test_a_choice_the_lock_refuses_is_not_offered(self):
        form = a_form()
        form.items[3].lock = lambda ctx: False
        self.open(form)
        self.assertNotIn("Wipe it", self.last)
        self.assertIn("not one of the choices", self.type("4"))


@tag("world")
class ThePresenter(Driving):

    def test_every_hook_is_called_where_a_protocol_would_want_it(self):
        self.open(a_form())
        self.type("1")
        self.type("Harbour")
        self.type("fly")
        self.type("4")
        self.type("yes")
        self.type("3")
        names = [call[0] for call in self.presenter.calls]
        for hook in ("opened", "shown", "chose", "refused", "confirmed",
                     "closed"):
            self.assertIn(hook, names)
        self.assertEqual(names[0], "opened")
        self.assertEqual(names[-1], "closed")


@tag("world")
class ANewPronounSet(Driving):
    """`pronouns new`, the first real form, asked the way it always was."""

    def setUp(self):
        super().setUp()
        self.room1.db.world_root = self.room1

    def start(self):
        from commands.pronoun_cmds import NEW_SET

        return self.open(NEW_SET, world_root=self.room1)

    def test_it_asks_each_form_in_turn(self):
        self.start()
        self.assertIn("___ picks up the sword|n (1 of 6)", self.last)
        self.assertIn("(2 of 6)", self.type("xe"))

    def test_then_the_number_in_words(self):
        self.start()
        for word in ("xe", "xem", "xyr", "xyrs", "xemself"):
            self.type(word)
        self.assertIn("xe picks up the sword", self.last)
        self.assertIn("xe pick up the sword", self.last)

    def test_and_keeps_it_once_it_is_complete(self):
        from world import pronouns

        self.start()
        for word in ("xe", "xem", "xyr", "xyrs", "xemself", "1"):
            self.type(word)
        self.assertIn("Keep this set", self.last)
        said = self.type("keep")
        self.assertIn("This world now keeps", said)
        self.assertEqual(pronouns.get(self.room1, "xe")["reflexive"], "xemself")
        self.assertEqual(self.char1.db.pronouns, "xe")
        self.assertFalse(self.is_open)

    def test_something_that_is_not_a_word_is_asked_again(self):
        self.start()
        self.assertIn("not a word", self.type("123"))
        self.assertIn("(1 of 6)", self.type("l"))

    def test_a_form_can_be_corrected_before_it_is_kept(self):
        self.start()
        for word in ("xe", "xem", "xyr", "xyrs", "xemself", "2"):
            self.type(word)
        self.type("2")
        self.type("xir")
        self.assertIn("xir", self.last)
        self.assertEqual(self.menu.stack[0].ctx.draft["object"], "xir")


@tag("world")
class ThroughARealSession(GameTest):
    """
    The route a player's input really takes: a session, an account running
    the menu, and a character being puppeted. Everything above drives the
    menu object directly; this is the check that the cmdset and the handing
    on work when nothing is patched.
    """

    session = True

    def setUp(self):
        super().setUp()
        import evennia

        self.account.puppet_object(self.session, self.char1)
        self.out = evennia.SESSION_HANDLER.data_out

    def sent(self):
        texts = []
        for call in self.out.call_args_list:
            text = call.kwargs.get("text")
            if isinstance(text, (tuple, list)):
                text = text[0]
            if text:
                texts.append(str(text))
        self.out.reset_mock()
        return "\n".join(texts)

    def type(self, line):
        self.char1.execute_cmd(line, session=self.session)
        return self.sent()

    def test_the_menu_runs_on_the_account_and_hears_what_is_typed(self):
        menu = menus.open_menu(self.char1, a_form(), session=self.session)
        self.assertIs(self.account.ndb._evmenu, menu)
        self.assertIn("1. Title", self.sent())
        self.type("1")
        self.type("Harbour")
        self.assertEqual(menu.stack[0].ctx.draft["title"], "Harbour")

    def test_a_view_menu_hands_a_command_to_the_character(self):
        menus.open_menu(self.char1, a_score(), session=self.session)
        self.sent()
        said = self.type("say hello there")
        self.assertIsNone(self.account.ndb._evmenu)
        self.assertIn("hello there", said)


@tag("world")
class HelpThenTheMenuAgain(Driving):
    """After help, the menu is shown again: the next thing wanted is to choose."""

    def test_help_on_a_choice_is_followed_by_the_choices(self):
        self.open(a_form())
        said = self.type("?1")
        self.assertIn("What world listings show.", said)
        self.assertLess(said.index("What world listings show."),
                        said.index("1. Title"))

    def test_so_is_help_chosen_from_the_list(self):
        form = a_form()
        form.items[1].help = "How many rooms."
        self.open(form)
        self.type("?")
        said = self.type("2")
        self.assertIn("How many rooms.", said)
        self.assertIn("1. Title", said)

    def test_help_on_a_field_is_followed_by_the_field(self):
        self.open(a_form())
        self.type("1")
        said = self.type("?")
        self.assertIn("Type the title", said)

    def test_a_view_menu_repeats_only_its_choices(self):
        self.open(a_score())
        said = self.type("?1")
        self.assertIn("For one of them", said)
        self.assertNotIn("Composure 12", said)


@tag("world")
class SayingItClosed(Driving):
    """Closing a menu yourself says so; being done with one does not need to."""

    def test_quit_says_so(self):
        self.open(a_form())
        self.assertIn(menus.CLOSED, self.type("q"))

    def test_backing_all_the_way_out_says_so(self):
        self.open(a_form(), path=["title"])
        self.type("b")
        self.assertIn(menus.CLOSED, self.type("b"))

    def test_finishing_something_does_not(self):
        self.open(a_form())
        self.assertNotIn(menus.CLOSED, self.type("3"))

    def test_nor_does_walking_away_from_a_view(self):
        self.open(a_score())
        with mock.patch.object(self.char1, "execute_cmd"):
            self.assertNotIn(menus.CLOSED, self.type("north"))

    def test_nor_quitting_a_view_that_would_have_closed_anyway(self):
        self.open(a_score())
        self.assertNotIn(menus.CLOSED, self.type("q"))

    def test_but_a_view_that_stays_open_does(self):
        with mock.patch.object(menus, "view_mode",
                               return_value=menus.STAY_OPEN):
            self.open(a_score())
            self.assertIn(menus.CLOSED, self.type("q"))

    def test_answering_no_to_a_question_does_not(self):
        menus.confirm(self.char1, "Delete it?", lambda: None,
                      interactive_only=False)
        said = self.type("no")
        self.assertIn("Nothing changed", said)
        self.assertNotIn(menus.CLOSED, said)
