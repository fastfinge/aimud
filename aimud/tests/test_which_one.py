"""
Which one: a name that several things here answer to.

It used to mean the oldest of them, silently, so a player with a peach soju
and a grapefruit soju drank whichever had been made first every time they
typed "drink soju". Now it is a question -- a menu for somebody who can be
shown one, where choosing carries on with what they typed, and the question in
words for a character, which it reads in its next prompt.

What is still not a question is worth holding as firmly: identical things,
counts, and a bulk action that already knows which thing each step is about.
"""

from unittest import mock

from evennia import create_object

from django.test import tag

from tests.base import GameCommandTest
from world import menus, ownership, verbs


class _TwoCoins(GameCommandTest):
    """A gold coin and a silver coin, carried, and somebody to give one to."""

    characters = 2

    def setUp(self):
        super().setUp()
        self.room1.db.world_root = self.room1
        self.gold = create_object(key="gold coin", location=self.char1)
        self.silver = create_object(key="silver coin", location=self.char1)
        self.char2.location = self.room1
        self.heard = []
        self.char1.msg = self._heard

    def _heard(self, text="", **kwargs):
        self.heard.append(str(text[0] if isinstance(text, tuple) else text))

    def connected(self):
        patcher = mock.patch.object(menus, "interactive", return_value=True)
        patcher.start()
        self.addCleanup(patcher.stop)

    def type(self, line):
        self.char1.ndb._evmenu.parse_input(line)

    def attempt(self, raw, said):
        from world import attempt as attempt_mod

        attempt_mod.attempt(
            self.char1, raw, None,
            lambda actor_text, event=None: said.append(actor_text or ""))


@tag("world")
class AskingWhichOne(_TwoCoins):

    def test_two_differently_named_things_are_a_question(self):
        _bound, unbound, questions = verbs.bind_all(
            self.char1, {"direct": "coin"})
        self.assertEqual(unbound, [])
        role, asked, several = questions[0]
        self.assertEqual(role, "direct")
        self.assertIn("gold coin", asked)
        self.assertIn("silver coin", asked)
        self.assertEqual(set(several), {self.gold, self.silver})

    def test_identical_things_are_not(self):
        self.silver.key = "gold coin"
        bound, _unbound, questions = verbs.bind_all(
            self.char1, {"direct": "coin"})
        self.assertEqual(questions, [])
        self.assertIs(bound["direct"], self.gold)

    def test_nor_is_a_count(self):
        bound, _unbound, questions = verbs.bind_all(
            self.char1, {"direct": "second coin"})
        self.assertEqual(questions, [])
        self.assertIs(bound["direct"], self.silver)

    def test_nor_a_name_only_one_thing_answers_to(self):
        bound, _unbound, questions = verbs.bind_all(
            self.char1, {"direct": "silver coin"})
        self.assertEqual(questions, [])
        self.assertIs(bound["direct"], self.silver)

    def test_what_you_carry_still_comes_before_the_room(self):
        """Only two in the same place are a question; "my letter" is carried."""
        create_object(key="copper coin", location=self.room1)
        self.silver.location = self.room1
        bound, _unbound, questions = verbs.bind_all(
            self.char1, {"direct": "coin"})
        self.assertEqual(questions, [])
        self.assertIs(bound["direct"], self.gold)

    def test_an_answer_already_given_is_not_asked_again(self):
        bound, _unbound, questions = verbs.bind_all(
            self.char1, {"direct": "coin"}, chosen={"direct": self.silver})
        self.assertEqual(questions, [])
        self.assertIs(bound["direct"], self.silver)


@tag("world")
class ChoosingCarriesOn(_TwoCoins):

    def test_choosing_from_the_menu_does_what_was_typed(self):
        self.connected()
        said = []
        self.attempt(f"give coin to {self.char2.key}", said)
        self.assertIn("Which coin do you mean?", "\n".join(self.heard))
        self.assertEqual(self.gold.location, self.char1)
        self.assertEqual(self.silver.location, self.char1)

        self.type("2")
        self.assertEqual(self.silver.location, self.char2)
        self.assertEqual(self.gold.location, self.char1)
        self.assertTrue(ownership.owns(self.char2, self.silver))

    def test_by_name_too(self):
        self.connected()
        self.attempt(f"give coin to {self.char2.key}", [])
        self.type("gold coin")
        self.assertEqual(self.gold.location, self.char2)

    def test_with_nobody_to_show_a_menu_it_is_the_question_in_words(self):
        """What a character is told, and reads back in its next prompt."""
        said = []
        self.attempt(f"give coin to {self.char2.key}", said)
        self.assertEqual(said, ["Which coin do you mean -- gold coin or "
                                "silver coin?"])
        self.assertEqual(self.gold.location, self.char1)
        self.assertEqual(self.silver.location, self.char1)


@tag("world")
class TheCommandsAskToo(_TwoCoins):
    """Take and drop bind for themselves, and took the oldest just the same."""

    def test_taking_asks_and_takes_the_one_chosen(self):
        from commands.look_take_cmds import CmdAIGet

        self.room1.db.world_root = None
        self.gold.location = self.room1
        self.silver.location = self.room1
        self.connected()
        self.call(CmdAIGet(), "coin")
        self.assertIsNotNone(self.char1.ndb._evmenu, "no question was put")
        self.assertEqual(self.gold.location, self.room1)
        self.assertEqual(self.silver.location, self.room1)
        self.type("2")
        self.assertEqual(self.silver.location, self.char1)
        self.assertEqual(self.gold.location, self.room1)

    def test_dropping_asks_and_drops_the_one_chosen(self):
        from commands.drop_cmds import CmdAIDrop

        self.connected()
        self.call(CmdAIDrop(), "coin")
        self.assertIsNotNone(self.char1.ndb._evmenu, "no question was put")
        self.assertEqual(self.gold.location, self.char1)
        self.type("1")
        self.assertEqual(self.gold.location, self.room1)
        self.assertEqual(self.silver.location, self.char1)
