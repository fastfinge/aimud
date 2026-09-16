"""
The one grammar, and what it is kept from doing.

Two tiers. The reading of a template is pure -- a string in, nodes out -- and
is `unit`. What a slot comes to needs somebody to be named, a world for their
pronouns to live in and a room for an event to happen in, and is `world`.

The injection table is the reason the module exists as much as the grammar
is. A template is author text and expands; what somebody said, and names, are
bound as quotes and never read. Before phase 1 an NPC's words were spliced
into its narration, so a line containing `{target}` said somebody's name.
"""

from django.test import SimpleTestCase, tag

from tests.base import GameTest
from world import events, lore, ownership, pronouns, referents, tokens
from world.tokens import Call, Slot, Text


def kinds(template):
    return [type(node).__name__ for node in tokens.parse(template)]


@tag("unit")
class ReadingATemplate(SimpleTestCase):

    def test_a_narration_reads_as_slots_calls_and_words(self):
        self.assertEqual(
            kinds("{actor} $pconj(hand) {target} {direct}."),
            ["Slot", "Text", "Call", "Text", "Slot", "Text", "Slot", "Text"])

    def test_both_possessive_spellings(self):
        for template in ("{target's}", "{target}'s"):
            node = tokens.parse(template)[0]
            self.assertEqual((node.name, node.possessive), ("target", True))

    def test_fields(self):
        node = tokens.parse("{self.state.color}")[0]
        self.assertEqual((node.name, node.fields), ("self", ("state", "color")))

    def test_escapes(self):
        self.assertEqual(tokens.parse(r"\{actor} costs \$pconj(x)"),
                         (Text("{actor} costs $pconj(x)"),))

    def test_a_stray_backslash_is_kept(self):
        self.assertEqual(tokens.parse(r"a\b"), (Text("a\\b"),))

    def test_money_is_not_a_call(self):
        self.assertEqual(tokens.parse("costs $5 or $ 5"),
                         (Text("costs $5 or $ 5"),))

    def test_a_call_that_never_closes_is_words(self):
        self.assertEqual(tokens.parse("$pconj(hand stays"),
                         (Text("$pconj(hand stays"),))

    def test_a_quoted_argument_keeps_its_commas(self):
        call = tokens.parse('$pick("a, b", as=stripes)')[0]
        self.assertEqual(call.args, ((Text("a, b"),),))
        self.assertEqual(dict(call.kwargs)["as"], (Text("stripes"),))

    def test_a_call_inside_a_call(self):
        call = tokens.parse("$outer($inner(x), key=value)")[0]
        self.assertIsInstance(call.args[0][0], Call)
        self.assertEqual(call.args[0][0].name, "inner")

    def test_a_comma_inside_braces_does_not_split(self):
        call = tokens.parse("$f({a, b}, c)")[0]
        self.assertEqual(len(call.args), 2)
        self.assertEqual(call.args[0], (Text("{a, b}"),))

    def test_every_spelling_of_the_player_is_one_slot(self):
        for spelling in ("<user>", "{{user}}", "$user", "< USER >", "{user}"):
            self.assertEqual(tokens.parse(spelling),
                             (Slot("user", (), False, "{user}"),), spelling)


@tag("unit")
class WhatAPluginMayAdd(SimpleTestCase):

    def test_a_reserved_name_is_refused(self):
        for name in ("actor", "user", "self", "quote"):
            with self.assertRaises(ValueError):
                tokens.provide(name, lambda context, **kw: "x")
        with self.assertRaises(ValueError):
            tokens.provide("pick", lambda context, *a, **kw: "x", call=True)

    def test_so_is_something_that_is_not_a_name(self):
        with self.assertRaises(ValueError):
            tokens.provide("not a name", lambda context, **kw: "x")

    def test_a_provided_slot_and_call_are_answered(self):
        tokens.provide("weather", lambda context, **kw: tokens.Phrase("raining"))
        tokens.provide("shout", lambda context, *args, **kw: args[0].upper(),
                       call=True)
        self.addCleanup(tokens.withdraw, "weather")
        self.addCleanup(tokens.withdraw, "shout")
        self.assertEqual(tokens.text("It is {weather}. $shout(hi)",
                                     tokens.Context()),
                         "It is raining. HI")

    def test_and_a_slot_nobody_answers_is_left_as_written(self):
        self.assertEqual(tokens.text("A {strange} $nope(x) day.",
                                     tokens.Context()),
                         "A {strange} $nope(x) day.")


class Stage(GameTest):
    """Jessica, a sword, and somebody watching."""

    characters = 2
    loose_objects = 1

    def setUp(self):
        super().setUp()
        self.room1.db.world_root = self.room1
        self.room1.db.is_world_root = True
        self.jessica = self.char1
        self.jessica.key = "Jessica"
        self.watcher = self.char2
        self.watcher.key = "Watcher"
        self.sword = self.obj1
        self.sword.key = "sword"
        pronouns.give(self.jessica, "she", self.room1)
        for who in (self.jessica, self.watcher):
            referents.clear(who)

    def drops(self, **fields):
        base = dict(actor=self.jessica, room=self.room1, verb="drop",
                    roles={"direct": self.sword},
                    room_template="{actor} $pconj(drop) {direct}.")
        base.update(fields)
        return events.Event(**base)


@tag("world")
class Spans(Stage):
    loose_objects = 2

    def test_spans_carry_what_they_name(self):
        event = self.drops(room_template="{actor} $pconj(drop) {direct}.")
        rendering = tokens.render(event.room_template,
                                  tokens.Context(event=event))
        self.assertEqual(str(rendering), "Jessica drops the sword.")
        self.assertEqual(rendering.refs(), [self.jessica, self.sword])

    def test_a_phrase_knows_its_number(self):
        coins = self.obj2
        coins.key = "coins"
        event = self.drops(actor=coins, room_template="{actor} $pconj(scatter).")
        rendering = tokens.render(event.room_template,
                                  tokens.Context(event=event))
        self.assertTrue(rendering.spans[0].plural)


@tag("world")
class NothingSaidIsRead(Stage):
    """The injection table."""

    SAID = "Tell {actor} to $pconj(die), <user>."

    def test_a_quote_is_inserted_as_said(self):
        event = self.drops(verb="say",
                           room_template='{actor} $pconj(say), "{quote}"',
                           quotes={"quote": self.SAID})
        self.assertEqual(events.render(event.template(), self.watcher, event),
                         f'Jessica says, "{self.SAID}"')

    def test_an_effect_line_is_a_quote_too(self):
        event = self.drops(effects=["{actor} is now here."])
        self.assertEqual(events.render(event.template(), None, event),
                         "Jessica drops the sword. {actor} is now here.")

    def test_an_effect_line_on_its_own_is_seen_and_gets_no_subject(self):
        """
        Joined onto the narration, an effect line with no narration in front
        of it was repaired as a fragment and read "Jessica a lamp is now here."
        """
        event = self.drops(room_template="", effects=["a lamp is now here."])
        self.assertTrue(event.seen)
        self.assertEqual(events.render(event.template(), None, event),
                         "A lamp is now here.")

    def test_an_npc_says_exactly_what_it_said(self):
        from evennia import create_object

        from typeclasses.npcs import NPC

        npc = create_object(NPC, key="Barnaby", location=self.room1)
        npc.db.is_npc = True
        heard = []
        self.watcher.msg = lambda text="", **kw: heard.append(text)
        npc._execute_one("say", {"message": self.SAID}, self.room1)
        self.assertTrue(heard, "the watcher heard nothing")
        self.assertIn(self.SAID, heard[0])


@tag("world")
class Fields(Stage):

    def rendered(self, template, viewer=None, event=None):
        event = event or self.drops()
        return events.render(template, viewer, event)

    def test_a_pronoun_form(self):
        self.assertEqual(self.rendered("{actor.subject}", self.watcher), "She")
        self.assertEqual(self.rendered("{actor.subject}", self.jessica), "You")

    def test_a_name_with_no_article(self):
        self.assertEqual(self.rendered("a {direct.name}"), "A sword")

    def test_a_state_by_its_group(self):
        self.room1.db.state_vocabulary = {
            "blue": {"means": "coloured blue", "group": "color"}}
        self.sword.db.states = ["blue"]
        self.assertEqual(self.rendered("It is {direct.state.color}."),
                         "It is blue.")

    def test_an_owner(self):
        ownership.claim(self.jessica, self.sword)
        self.assertEqual(self.rendered("{direct.owner}", self.watcher),
                         "Jessica")
        self.assertEqual(self.rendered("{direct.owner's} sword", self.jessica),
                         "Your sword")

    def test_a_field_that_is_not_in_the_table_is_left_alone(self):
        self.assertEqual(self.rendered("{direct.db.api_key}"),
                         "{direct.db.api_key}")

    def test_self_is_the_thing_the_text_belongs_to(self):
        self.room1.db.state_vocabulary = {
            "blue": {"means": "coloured blue", "group": "color"}}
        self.sword.db.states = ["blue"]
        context = tokens.Context(about=self.sword, world_root=self.room1)
        self.assertEqual(
            tokens.text("{self.name} is {self.state.color}.", context),
            "sword is blue.")


@tag("world")
class ThePlayer(Stage):

    def test_every_spelling_resolves_in_a_description(self):
        self.room1.db.world_description = (
            "<user> is the heir. {{user}}, $user and {user}. A {strange} land.")
        self.assertEqual(
            lore.description(self.room1, self.jessica),
            "Jessica is the heir. Jessica, Jessica and Jessica. "
            "A {strange} land.")

    def test_nobody_in_particular_is_the_visitor(self):
        self.room1.db.world_description = "<user> arrives."
        self.assertEqual(lore.description(self.room1), "the visitor arrives.")

    def test_guidance_too(self):
        self.room1.db.world_guidance = {"npcs": "Be kind to <user>."}
        self.assertEqual(lore.guidance(self.room1, "npcs", self.jessica),
                         "Be kind to Jessica.")

    def test_and_a_wizard_spec_before_the_world_exists(self):
        self.assertEqual(
            lore.description({"description": "{user} wakes."}, self.jessica),
            "Jessica wakes.")
