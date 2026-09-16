"""
A world's word lists: what may be kept, what is chosen, and where it lives.

The ball is the acceptance test and the reason for the design. "This is a
{color} ball." chooses a colour when the ball is made, the colour is a state,
a look reads the state back -- and so a rule that paints the ball red changes
what every later look says, with nothing else written.
"""

import pathlib
import re

from django.test import SimpleTestCase, tag

from tests.base import GameCommandTest, GameTest
from world import token_lists, tokens, verbs

GAME = pathlib.Path(__file__).resolve().parent.parent

COLOR = {
    "means": "the colour of a small painted thing",
    "group": "color",
    "entries": [
        {"text": "blue", "sets": {"states": ["blue"]}},
        {"text": "pink", "sets": {"states": ["pink"]}},
        {"text": "yellow", "sets": {"states": ["yellow"]}},
    ],
}

SMELL = {"means": "what a dockside place smells of",
         "entries": ["brine", "tar", "old rope", "fish", "smoke"]}


class World(GameTest):

    def setUp(self):
        super().setUp()
        self.room1.db.world_root = self.room1
        self.room1.db.is_world_root = True
        self.root = self.room1

    def make(self, description, name="ball"):
        from world import clothing

        return clothing.create({"name": name, "description": description},
                               location=self.room1)

    def look(self, obj, viewer=None):
        return obj.get_display_desc(viewer or self.char1)


@tag("world")
class WhatMayBeKept(World):

    def test_a_complete_list_is_kept_under_its_name(self):
        self.assertEqual(token_lists.register(self.root, "smell", SMELL), "smell")
        self.assertIn("smell", token_lists.vocabulary(self.root))

    def test_a_list_with_no_meaning_is_refused(self):
        self.assertEqual(token_lists.register(
            self.root, "smell", {"entries": ["tar"]}), "")

    def test_a_reserved_name_is_refused(self):
        for name in ("actor", "user", "self", "pick"):
            self.assertEqual(token_lists.register(self.root, name, SMELL), "", name)

    def test_a_list_that_can_never_finish_is_refused_at_the_door(self):
        self.assertEqual(token_lists.register(
            self.root, "color", {"means": "x", "entries": ["{color}"]}), "")

    def test_but_one_that_refers_to_itself_and_can_stop_is_kept(self):
        self.assertEqual(token_lists.register(
            self.root, "shade", {"means": "a colour, perhaps doubled",
                                 "entries": ["red", "{shade} and {shade}"]}),
            "shade")
        words = tokens.text("{shade}", tokens.Context(world_root=self.root))
        self.assertNotIn("{", words)

    def test_a_list_naming_nothing_anyone_answers_is_refused(self):
        self.assertEqual(token_lists.register(
            self.root, "sign", {"means": "x", "entries": ["The {nobody}"]}), "")

    def test_lists_declared_together_may_name_each_other(self):
        used = token_lists.declare(self.root, [
            {"name": "inn", "means": "an inn's name",
             "entries": ["The {beast} and Anchor"]},
            {"name": "beast", "means": "an animal", "entries": ["Goat", "Crow"]},
        ])
        self.assertEqual(used, {"inn": "inn", "beast": "beast"})

    def test_a_plural_folds_onto_the_list_already_kept(self):
        token_lists.register(self.root, "smell", SMELL)
        self.assertEqual(token_lists.register(self.root, "smells", SMELL), "smell")

    def test_a_list_without_a_group_may_not_invent_states(self):
        self.assertEqual(token_lists.register(self.root, "hue", {
            "means": "x", "entries": [{"text": "mauve",
                                       "sets": {"states": ["mauve"]}}]}), "")

    def test_a_list_with_a_group_declares_its_states(self):
        token_lists.register(self.root, "color", COLOR)
        self.assertEqual(verbs.group_of(self.root, "blue"), "color")
        self.assertTrue(verbs.group_rules(self.root, "color").get("exclusive"))

    def test_a_list_nobody_uses_can_be_taken_away(self):
        token_lists.register(self.root, "smell", SMELL)
        token_lists.register(self.root, "air", {"means": "x",
                                                "entries": ["{smell}"]})
        removed, complaint = token_lists.unregister(self.root, "smell")
        self.assertFalse(removed)
        self.assertIn("air", complaint)
        self.assertTrue(token_lists.unregister(self.root, "air")[0])
        self.assertTrue(token_lists.unregister(self.root, "smell")[0])


@tag("world")
class TheBall(World):
    characters = 2

    def setUp(self):
        super().setUp()
        token_lists.register(self.root, "color", COLOR)
        self.ball = self.make("This is a {color} ball.")

    def colour(self):
        found = [s for s in verbs.states(self.ball)
                 if verbs.group_of(self.root, s) == "color"]
        self.assertEqual(len(found), 1, verbs.states(self.ball))
        return found[0]

    def test_it_is_a_colour_from_the_moment_it_exists(self):
        colour = self.colour()
        self.assertIn(f"This is a {colour} ball.", self.look(self.ball))

    def test_every_look_and_every_viewer_agree(self):
        first = self.look(self.ball, self.char1)
        self.assertEqual(self.look(self.ball, self.char1), first)
        self.assertEqual(self.look(self.ball, self.char2), first)

    def test_painting_it_changes_what_a_look_says(self):
        verbs.register_state(self.root, "red", group="color")
        verbs.apply_states(self.ball, add=["red"], world_root=self.root,
                           announce=False)
        self.assertIn("This is a red ball.", self.look(self.ball))

    def test_a_model_is_shown_the_colour_not_the_brace(self):
        self.assertNotIn("{", tokens.text_of(self.ball))
        self.assertIn(self.colour(), tokens.text_of(self.ball))


@tag("world")
class Decoration(World):
    characters = 2

    def setUp(self):
        super().setUp()
        token_lists.register(self.root, "smell", SMELL)

    def test_a_choice_with_no_fact_is_kept_all_the_same(self):
        crate = self.make("It smells of {smell}.", name="crate")
        first = self.look(crate, self.char1)
        for _ in range(3):
            self.assertEqual(self.look(crate, self.char1), first)
            self.assertEqual(self.look(crate, self.char2), first)
        self.assertIn("smell", crate.db.token_choices)

    def test_two_references_are_one_choice(self):
        crate = self.make("{smell}, and more {smell}.", name="crate")
        words = self.look(crate)
        first, second = re.match(r"(.+), and more (.+)\.", words).groups()
        self.assertEqual(first.lower(), second.lower())

    def test_and_a_label_is_a_second_choice(self):
        crate = self.make("{smell}; $pick(smell, as=under).", name="crate")
        self.look(crate)
        self.assertEqual(set(crate.db.token_choices), {"smell", "smell#under"})

    def test_a_viewer_scope_is_kept_once_per_person(self):
        token_lists.register(self.root, "rumour", {
            "means": "what somebody has heard", "scope": "viewer",
            "entries": [f"rumour {n}" for n in range(20)]})
        board = self.make("Somebody says: {rumour}.", name="notice board")
        mine = self.look(board, self.char1)
        theirs = self.look(board, self.char2)
        self.assertEqual(self.look(board, self.char1), mine)
        self.assertEqual(self.look(board, self.char2), theirs)
        self.assertEqual(
            {key.split("@")[0] for key in board.db.token_choices}, {"rumour"})
        self.assertEqual(len(board.db.token_choices), 2)

    def test_a_render_scope_keeps_nothing(self):
        token_lists.register(self.root, "weather", {
            "means": "x", "scope": "render", "entries": ["rain", "sun"]})
        vane = self.make("It says {weather}.", name="weather vane")
        self.look(vane)
        self.assertFalse(vane.db.token_choices)


@tag("world")
class TheCommand(GameCommandTest):
    accounts = True

    def setUp(self):
        super().setUp()
        self.room1.db.world_root = self.room1
        self.room1.db.is_world_root = True
        self.room1.db.world_creator = self.account

    def test_add_show_try_and_remove(self):
        from commands.verbs import CmdCreate, CmdDelete, CmdView

        self.call(CmdCreate(), "tokens smell: what docks smell of = brine | tar",
                  "This world now keeps")
        self.call(CmdView(), "tokens", "Word lists")
        self.call(CmdView(), "tokens smell", "{smell}")
        self.call(CmdView(), "tokens try It smells of {smell}.",
                  "That comes to:")
        self.call(CmdDelete(), "tokens smell yes", "smell is gone")

    def test_only_the_maker_may_change_them(self):
        from commands.verbs import CmdCreate

        self.room1.db.world_creator = None
        self.account.is_superuser = False
        self.call(CmdCreate(), "tokens smell = tar",
                  "Only whoever made this world")


@tag("unit")
class NoPromptReadsARawDescription(SimpleTestCase):
    """
    The structural guard. A description keeps its tokens, so a module that
    puts `db.desc` straight into a prompt hands a model "{color}" -- and the
    model invents one. Writes are fine; reads go through `tokens.text_of`.
    """

    def test_nothing_in_world_reads_desc_directly(self):
        read = re.compile(r"\.db\.desc\b(?!\s*=[^=])")
        offences = []
        for path in sorted((GAME / "world").glob("*.py")):
            if path.name == "tokens.py":
                continue
            for number, line in enumerate(
                    path.read_text(encoding="utf-8").splitlines(), 1):
                if read.search(line) and not line.lstrip().startswith("#"):
                    offences.append(f"world/{path.name}:{number}: {line.strip()}")
        self.assertEqual(offences, [], "\n" + "\n".join(offences))
