"""
Reading a world rather than only running one.

`rules` has always answered "which rule won, and why", which is the question
somebody has after being surprised. It never answered the one asked first:
what will happen if I type this. A rule's conditions were printed in plain
words from the day conditions existed and its effects were printed in none --
so the single most useful fact about a verb was legible only as JSON.

And a contest was invisible from both ends. The roll went to the log, with
`checks.describe` saying in as many words that players are never shown it, so
a verb that could never be passed and a verb that was merely hard looked
exactly alike from inside. You could only tell them apart by trying eleven
times.

One register under the answer to both: `effects.VOCABULARY` says what each
sort of change means, `effects.say` renders a particular one, and `checks.odds`
counts the faces of the die that go your way. Everything that has to put an
effect into words reads the same entries, which is what stops them drifting
into separate accounts of what `set_state` does.
"""

from django.test import SimpleTestCase, tag
from evennia.utils.test_resources import EvenniaTest

from tests.support import FakeAccount, as_json, immediately, replying
from world import attempt as attempt_mod
from world import checks, conditions as C, effects, standard_rules, verbs
from world import rulebooks as R


@tag("unit")
class TheRegisterCoversTheCode(SimpleTestCase):
    """
    The claim `effects.VOCABULARY` makes about itself, asserted.

    A register that documents eleven of twelve effects is worse than none: the
    twelfth is then the one somebody looks up, finds missing, and concludes the
    game cannot do. So the two directions are both tested -- nothing is
    described that cannot be written, and nothing can be written that is not
    described.
    """

    def test_every_effect_a_rule_may_use_is_described(self):
        from world import rule_gen

        missing = sorted(set(rule_gen.EFFECTS) - set(effects.VOCABULARY))
        self.assertEqual(missing, [])

    def test_and_nothing_is_described_that_a_rule_may_not_use(self):
        from world import rule_gen

        extra = sorted(set(effects.VOCABULARY) - set(rule_gen.EFFECTS))
        self.assertEqual(extra, [])

    def test_stop_is_gone(self):
        """
        It was permitted and applied by nothing anywhere, so a rule using it
        would have been accepted, stored, and silently done nothing for the
        life of the world. The register found it by being written down.
        """
        from world import rule_gen

        self.assertNotIn("stop", rule_gen.EFFECTS)

    def test_every_entry_says_all_four_things(self):
        for name, entry in effects.VOCABULARY.items():
            self.assertTrue(entry.get("means"), name)
            self.assertTrue(entry.get("takes"), name)
            self.assertIn("backwards", entry, name)
            self.assertIn("answers", entry, name)

    def test_what_speaks_for_itself_is_read_off_the_register(self):
        """One statement of it, rather than a tuple that has to agree."""
        self.assertEqual(effects.SPEAKS_FOR_ITSELF, ("describe",))

    def test_an_entry_reads_as_a_sentence_about_the_effect(self):
        """`help set_state` says "It {means}", so every means is a verb phrase."""
        for name, entry in effects.VOCABULARY.items():
            first = entry["means"].split()[0]
            self.assertFalse(first.endswith("ing"), f"{name}: {entry['means']}")


@tag("unit")
class SayingWhatAnEffectDoes(SimpleTestCase):
    """Present tense, second person: everybody reading is being told what
    will happen to them."""

    def said(self, **effect):
        return effects.say(effect)

    def test_a_state_going_on_and_coming_off(self):
        self.assertEqual(
            self.said(type="set_state", role="direct",
                      add=["burning"], remove=["damp"]),
            "makes what you act on burning, and no longer damp")

    def test_a_state_only_coming_off(self):
        self.assertEqual(
            self.said(type="set_state", role="direct", remove=["dead"]),
            "leaves what you act on no longer dead")

    def test_a_figure_that_costs_you_something(self):
        self.assertEqual(
            self.said(type="set_trait", role="actor", trait="stamina",
                      change=-5),
            "costs you 5 stamina")

    def test_a_figure_that_drains(self):
        self.assertIn("drain", self.said(type="set_trait", role="actor",
                                         trait="poison", set_to=20, rate=-1))

    def test_the_four_places_a_thing_can_go(self):
        self.assertEqual(self.said(type="move_object", name_role="direct",
                                   to="actor"),
                         "puts what you act on in your hands")
        self.assertEqual(self.said(type="move_object", name_role="direct",
                                   to="room"),
                         "sets what you act on down here")
        self.assertIn("in what it goes in",
                      self.said(type="move_object", name_role="direct",
                                to="container", preposition="in"))
        self.assertEqual(self.said(type="move_object", name_role="direct",
                                   to="Orbital Dock"),
                         "sends what you act on to Orbital Dock")

    def test_a_verb_that_only_happens(self):
        self.assertEqual(self.said(type="narrate"),
                         "nothing but what you see happen")

    def test_an_effect_this_game_does_not_know_is_said_as_itself(self):
        """
        Hidden would be worse. This listing exists to be checked by somebody,
        and a line quietly dropped from it is the one they needed.
        """
        self.assertIn("summon_dragon", self.said(type="summon_dragon"))

    def test_something_that_is_not_an_effect_at_all(self):
        self.assertEqual(effects.say("nonsense"), "something unreadable")


@tag("unit")
class CountingTheFacesThatGoYourWay(SimpleTestCase):
    """
    `odds` asks `_band` about every face rather than doing the arithmetic, so
    there is one implementation of what a success is -- which matters here
    more than it looks, because the extremes overrule the sum.
    """

    def test_a_hopeless_attempt_is_not_impossible(self):
        """A natural twenty is never a failure, so nothing is ever nought."""
        self.assertEqual(checks.odds(0, 100), 1)

    def test_a_trivial_one_is_not_certain(self):
        """And a natural one is never a success, so nothing is ever twenty."""
        self.assertEqual(checks.odds(100, 0), 19)

    def test_an_even_contest_is_about_even(self):
        self.assertEqual(checks.odds(0, 10), 11)

    def test_a_point_of_a_trait_is_worth_having(self):
        self.assertEqual(checks.odds(5, 10) - checks.odds(4, 10), 1)

    def test_nonsense_counts_nothing(self):
        self.assertEqual(checks.odds(None, "hard"), 0)


@tag("world")
class ShowingTheRoll(EvenniaTest):
    """
    `checks.describe` said players are never shown this. They are now, and the
    reason is the one this whole file is about: a world has to be examinable by
    the person playing in it, and a verb that always fails looks exactly like a
    verb that is merely hard unless the numbers are on the page.
    """

    def setUp(self):
        super().setUp()
        self.root = self.room1
        self.root.db.is_world_root = True
        self.room1.db.world_root = self.root
        self.room1.db.is_ai_room = True
        self.obj1.key = "Gate"
        self.obj1.db.kinds = ["gate.n.01"]
        from world import kinds

        kinds.admit(self.root, self.obj1.db.kinds, "force", True)
        standard_rules.seed(self.root)
        R.add(self.root, R.blank(
            action="force", phase=R.CARRY_OUT, scope={"world": True},
            name="forcing it opens it",
            contest={"trait": "strength", "against": None, "difficulty": 12},
            effects=[{"type": "set_state", "role": "direct",
                      "add": ["forced"]}]))

    def forced(self):
        said = []
        with immediately(), replying(
                as_json({"applies_to": [{"role": "direct"}]}),
                as_json({"actor": "You heave at it.", "room": "{actor} heaves."})):
            attempt_mod.attempt(
                self.char1, "force gate", FakeAccount(),
                on_message=lambda actor_text, room_text=None:
                    said.append(actor_text or ""))
        return "\n".join(s for s in said if s)

    def test_the_numbers_are_shown_under_the_prose(self):
        said = self.forced()
        self.assertIn("You heave at it", said)
        self.assertIn("against 12", said)

    def test_and_are_not_cached_into_the_narration(self):
        """
        The narration is reused the next time anybody does this, so a die roll
        written into it would be somebody else's roll for ever.
        """
        self.forced()
        stored = dict(self.obj1.db.ai_commands or {}).get("force") or {}
        for entry in dict(stored).values():
            self.assertNotIn("against 12", dict(entry).get("actor", ""))

    def test_a_character_is_not_told_the_numbers(self):
        """
        An NPC's actor line becomes something it believes it noticed when
        nothing happened in the room, so a die roll there comes back as a
        character remembering arithmetic. `narration_hint` avoids exactly this
        a file away, and for the same reason.
        """
        self.char2.db.is_npc = True
        self.char2.move_to(self.room1, quiet=True)
        said = []
        with immediately(), replying(
                as_json({"actor": "It heaves at the gate.", "room": ""})):
            attempt_mod.attempt(
                self.char2, "force gate", FakeAccount(),
                on_message=lambda actor_text, room_text=None:
                    said.append(actor_text or ""))
        self.assertNotIn("against 12", "\n".join(said))

    def test_an_uncontested_verb_shows_no_numbers(self):
        """Most verbs have no check, and a line about one would be noise."""
        self.assertEqual(checks.said(None), "")


@tag("unit")
class TheOneRendererEverybodyUses(SimpleTestCase):
    """
    `suggest.said` had grown a third of a renderer of its own, with an
    `else: would: <type>` at the bottom that printed the raw type for
    everything nobody had got round to. Two accounts of what an effect means
    is one more than this design allows anywhere else.
    """

    def test_a_proposal_reads_the_same_words_as_the_listing(self):
        from world import suggest

        rule = R.blank(action="close", phase=R.CARRY_OUT,
                       name="closing a thing closes it",
                       effects=[{"type": "set_state", "role": "direct",
                                 "add": ["closed"], "remove": ["open"]}])
        rule["id"] = "r1"
        said = suggest.said(rule)
        self.assertIn(effects.say(rule["effects"][0]), said)

    def test_including_the_ones_it_never_had_a_line_for(self):
        from world import suggest

        rule = R.blank(action="send", phase=R.CARRY_OUT,
                       effects=[{"type": "move_object", "name_role": "direct",
                                 "to": "Orbital Dock"}])
        rule["id"] = "r2"
        self.assertIn("sends what you act on to Orbital Dock",
                      suggest.said(rule))
