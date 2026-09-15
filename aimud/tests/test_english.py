"""
What English does to a word, with a dictionary and without one.

The word table is built from what was measured while planning: the plurals
`inflect` gets wrong on its own (glasses, water, Raldor), the verbs Evennia's
table has never heard of (airlock, teleport, holster, reboot), and the ones it
knows irregularly (go, take, be, have). Every row that does not need WordNet
is asserted again with WordNet taken away, and the rows that do need it are
asserted to fall back to what the game said before -- which is the lexicon's
promise, tested rather than trusted.
"""

from unittest import mock

from django.test import SimpleTestCase, tag
from evennia.utils.test_resources import EvenniaTest

from world import english, events, lexicon, pronouns, tokens

#: (function, arguments, expected) that hold whether or not WordNet is here.
EITHER_WAY = [
    (english.count, (3, "coin"), "three coins"),
    (english.count, (2, "tooth"), "two teeth"),
    (english.count, (13, "coin"), "13 coins"),
    (english.count, (1, "sword"), "a sword"),
    (english.plural, ("bottle of soju",), "bottles of soju"),
    (english.plural, ("sheep",), "sheep"),
    (english.with_article, ("hour",), "an hour"),
    (english.with_article, ("honest man",), "an honest man"),
    (english.with_article, ("the Crown",), "the Crown"),
    (english.with_article, ("sword",), "a sword"),
    (english.with_article, ("sword", None, True), "the sword"),
    (english.conjugate, ("hand",), "hands"),
    (english.conjugate, ("hand", 3, True), "hand"),
    (english.conjugate, ("hand", 2), "hand"),
    (english.conjugate, ("be",), "is"),
    (english.conjugate, ("be", 3, True), "are"),
    (english.conjugate, ("pick up",), "picks up"),
    (english.conjugate, ("airlock",), "airlocks"),
    (english.past, ("go",), "went"),
    (english.past, ("take",), "took"),
    (english.past, ("have",), "had"),
    (english.past, ("be",), "was"),
    (english.past, ("be", 3, True), "were"),
    (english.past, ("be", 2), "were"),
    (english.past, ("pry",), "pried"),
    (english.past, ("stop",), "stopped"),
    (english.past, ("airlock",), "airlocked"),
    (english.past, ("teleport",), "teleported"),
    (english.past, ("holster",), "holstered"),
    (english.past, ("reboot",), "rebooted"),
    (english.conjugate, ("pick up", 3, False, "past"), "picked up"),
    (english.base_form, ("tries",), "try"),
    (english.base_form, ("watches",), "watch"),
    (english.base_form, ("is",), "be"),
    (english.base_form, ("has",), "have"),
    (english.base_form, ("picked",), ""),
    (english.count, (1, "pair of boots"), "a pair of boots"),
    (english.count, (3, "pair of boots"), "three pairs of boots"),
]


@tag("unit")
class TheWordTable(SimpleTestCase):

    def check(self, rows):
        for function, arguments, expected in rows:
            with self.subTest(function=function.__name__, arguments=arguments):
                self.assertEqual(function(*arguments), expected)

    def test_with_a_dictionary(self):
        self.check(EITHER_WAY)
        self.check([
            (english.plural, ("glasses",), "glasses"),
            (english.count, (1, "glasses"), "some glasses"),
            # Irregular pasts Evennia's table has never heard of.
            (english.past, ("bind",), "bound"),
            (english.past, ("bear",), "bore"),
            (english.past, ("baby-sit",), "baby-sat"),
            (english.past, ("co-star",), "co-starred"),
        ])

    def test_without_one(self):
        """The same table, and what the game said before for the rest."""
        with mock.patch.object(lexicon, "_wordnet", lambda: None):
            self.check(EITHER_WAY)
            self.check([
                (english.is_plural, ("glasses",), False),
                (english.count, (1, "glasses"), "a glasses"),
                (english.past, ("bind",), "binded"),
            ])

    def test_is_after_the_actor_is_wrapped_as_be(self):
        """
        It was wrapped as "i", whose third person is "is" by the suffix rule,
        and the actor was told "You i tired."
        """
        self.assertEqual(events.repair("{actor} is tired."),
                         "{actor} $pconj(be) tired.")

    def test_lighted_is_what_evennias_table_says(self):
        """
        Recorded rather than fixed. WordNet says "lit", but its tables cannot
        be trusted for a past -- see the module docstring on "sown" -- and
        "lighted" is English.
        """
        self.assertEqual(english.past("light"), "lighted")


@tag("unit")
class RegularPast(SimpleTestCase):
    """The spelling rules, for verbs no table has heard of."""

    def test_the_rules(self):
        for verb, expected in [("glork", "glorked"), ("frizzle", "frizzled"),
                               ("zorby", "zorbied"), ("zot", "zotted"),
                               ("blay", "blayed"), ("snex", "snexed")]:
            with self.subTest(verb=verb):
                self.assertEqual(english.regular_past(verb), expected)


@tag("world")
class WhatTheThingKnows(EvenniaTest):

    def setUp(self):
        super().setUp()
        self.room1.db.world_root = self.room1
        self.sword = self.obj1
        self.sword.key = "sword"
        self.char1.key = "Jessica"

    def test_somebody_takes_no_article(self):
        self.assertEqual(english.count(1, "Jessica", obj=self.char1), "Jessica")
        self.assertEqual(
            self.char1.get_numbered_name(1, None, return_string=True),
            "Jessica")

    def test_stuff_is_some_however_much(self):
        water = self.obj2
        water.key = "water"
        water.db.kinds = ["water.n.01"]
        self.assertEqual(water.get_numbered_name(1, None, return_string=True),
                         "some water")
        self.assertEqual(water.get_numbered_name(3, None, return_string=True),
                         "some water")

    def test_a_thing_is_counted(self):
        self.assertEqual(self.sword.get_numbered_name(3, None),
                         ("a sword", "three swords"))

    def test_and_its_aliases_still_find_it(self):
        self.sword.get_numbered_name(3, None)
        self.assertTrue(self.sword.aliases.get(
            "three swords", category=self.sword.plural_category))

    def test_a_narration_still_says_the(self):
        self.assertEqual(events.plain_name(self.sword, None), "the sword")


@tag("world")
class ThePast(EvenniaTest):

    def setUp(self):
        super().setUp()
        self.room1.db.world_root = self.room1
        self.jessica, self.britney = self.char1, self.char2
        self.jessica.key, self.britney.key = "Jessica", "Britney"
        self.obj1.key = "sword"
        pronouns.give(self.jessica, "she", self.room1)

    def event(self, template):
        return events.Event(actor=self.jessica, room=self.room1, verb="hand",
                            roles={"direct": self.obj1,
                                   "target": self.britney},
                            room_template=template)

    def test_a_narration_in_the_past(self):
        event = self.event("{actor} $pconj(hand) {target} {direct}.")
        self.assertEqual(
            events.render(event.room_template, None, event, tense="past"),
            "Jessica handed Britney the sword.")

    def test_be_agrees_in_the_past(self):
        event = self.event("{actor} $pconj(be) tired.")
        self.assertEqual(
            events.render(event.room_template, None, event, tense="past"),
            "Jessica was tired.")
        self.assertEqual(
            events.render(event.room_template, self.jessica, event,
                          tense="past"),
            "You were tired.")

    def test_the_present_is_unchanged(self):
        event = self.event("{actor} $pconj(hand) {target} {direct}.")
        self.assertEqual(events.render(event.room_template, None, event),
                         "Jessica hands Britney the sword.")


@tag("unit")
class EnglishCalls(SimpleTestCase):

    def test_the_calls_a_template_or_list_can_write(self):
        context = tokens.Context()
        for template, expected in [("$an(hour)", "an hour"),
                                   ("$the(sword)", "the sword"),
                                   ("$plural(tooth)", "teeth"),
                                   ("$count(3, coin)", "three coins"),
                                   ("$count(many, coin)", "$count(many, coin)")]:
            with self.subTest(template=template):
                self.assertEqual(tokens.text(template, context), expected)
