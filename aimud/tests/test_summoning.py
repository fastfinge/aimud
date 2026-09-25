"""
Reaching a rule for a thing that does not exist yet.

The shape a world of endless alchemy is built out of, and the one the engine
could not express. `summon air` has to find the rule that makes air, and at the
moment the sentence is read there is no air to find it by -- so every condition
there was (`kind`, `is`, `exists`) selected nothing, and an unmatched noun went
straight to `item_gen.conjure` instead, which a hand-built world refuses.

Three things had to change together and all three are tested here:

* `called` asks about the *word*, not the thing, so a guard can select a rule
  from the sentence alone;
* an unmatched noun consults the rulebooks before it is conjured, so such a
  rule is reachable at all -- and so `summon earth` in a world that already
  has earth stops producing two of it;
* the gate on making items is asked before the first thing that costs, so a
  world that writes none of its own is refused for free and in plain words.
"""

from django.test import tag

from tests.base import GameTest
from tests.support import FakeSponsor, deciding, immediately, replying
from world import actions, conditions, kinds, permits, rulebooks, rulesets


def _summoning(element):
    """The rule somebody writing endless alchemy means to write."""
    return {
        "name": f"summoning {element}",
        "phase": rulebooks.CARRY_OUT,
        "action": "summon",
        "scope": {rulebooks.WORLD: True},
        "when": [{"subject": "direct", "called": element}],
        "effects": [{"type": "create_object", "name": element,
                     "kind": element, "location": "room",
                     "description": f"A handful of {element}."}],
    }


class Alchemy(GameTest):
    """A world that writes nothing of its own, and summons the four elements."""

    def setUp(self):
        super().setUp()
        self.root = self.room1
        self.root.db.is_world_root = True
        self.room1.db.world_root = self.root
        self.room1.db.is_ai_room = True
        rulesets.apply_choice(self.root, ["default"])
        permits.apply_choice(
            self.root,
            {name: permits.NEVER for name, _label, _off in permits.MAKES})
        actions.declare(self.root, "summon", [
            {"role": "direct", "access": "visible", "optional": False}])

    def summon(self, what):
        from world import attempt as attempt_mod

        said = []
        with immediately(), deciding({"is_body_part": 0, "could_exist": 5}), \
                replying('{"valid": true, "effects": []}'):
            attempt_mod.attempt(
                self.char1, f"summon {what}",
                FakeSponsor(world_root=self.root, actor=self.char1),
                on_message=lambda actor_text, room_text=None:
                    said.append(actor_text))
        return " ".join(s for s in said if s)

    def here(self, kind):
        """What is in the room of that sort, by the word rather than the sense."""
        from world import lexicon

        return [obj for obj in self.room1.contents
                if kind in {lexicon.word_of(k) for k in kinds.of(obj)}]


@tag("world")
class SummoningWhatIsNotThere(Alchemy):

    def test_the_rule_is_reached_and_makes_it(self):
        rulebooks.add(self.root, _summoning("earth"))
        self.summon("earth")
        self.assertEqual(len(self.here("earth")), 1)

    def test_and_only_the_rule_for_that_word(self):
        """The whole complaint: summoning air summoned earth."""
        rulebooks.add(self.root, _summoning("earth"))
        rulebooks.add(self.root, _summoning("air"))
        self.summon("air")
        self.assertEqual(len(self.here("earth")), 0)
        self.assertEqual(len(self.here("air")), 1)

    def test_a_word_no_rule_knows_is_still_refused(self):
        rulebooks.add(self.root, _summoning("earth"))
        said = self.summon("aetherium")
        self.assertEqual(self.here("aetherium"), [])
        self.assertIn("conjured", said)

    def test_it_is_refused_in_plain_words_and_for_nothing(self):
        """The gate comes before the decision call, not two calls after it."""
        rulebooks.add(self.root, _summoning("earth"))
        said = self.summon("aetherium")
        self.assertNotIn("|r", said)
        self.assertNotIn("Could not resolve", said)

    def test_the_arity_question_steps_aside(self):
        """`summon` takes a direct object, and nothing bound to it."""
        rulebooks.add(self.root, _summoning("earth"))
        said = self.summon("earth")
        self.assertNotIn("Summon what?", said)

    def test_summoning_again_makes_a_second(self):
        """Endlessly: what the world is called."""
        rulebooks.add(self.root, _summoning("earth"))
        self.summon("earth")
        self.summon("earth")
        self.assertEqual(len(self.here("earth")), 2)

    def test_an_article_and_a_plural_reach_the_same_rule(self):
        rulebooks.add(self.root, _summoning("earth"))
        self.summon("some earth")
        self.assertEqual(len(self.here("earth")), 1)

    def test_a_word_this_world_folds_reaches_it_too(self):
        from world import folds

        rulebooks.add(self.root, _summoning("earth"))
        self.summon("earth")                      # so the kind exists to fold
        folds.fold(self.root, "loam", "earth", noun=True)
        self.summon("loam")
        self.assertEqual(len(self.here("earth")), 2)


@tag("world")
class SummoningWhatIsAlreadyThere(Alchemy):
    """
    The other half, and the reason the two are one change.

    With something already answering to the word, the noun binds and nothing
    is promoted -- so the same rule has to be selected by what it bound to.
    Before, `summon earth` beside a lump of earth conjured a second lump and
    then ran the rule, which made a third.
    """

    def test_one_rule_fires_and_makes_exactly_one(self):
        rulebooks.add(self.root, _summoning("earth"))
        self.summon("earth")
        self.assertEqual(len(self.here("earth")), 1)
        self.summon("earth")
        self.assertEqual(len(self.here("earth")), 2)

    def test_the_right_rule_still_wins(self):
        rulebooks.add(self.root, _summoning("earth"))
        rulebooks.add(self.root, _summoning("air"))
        self.summon("earth")
        self.summon("air")
        self.assertEqual(len(self.here("earth")), 1)
        self.assertEqual(len(self.here("air")), 1)


@tag("unit")
class TheWordItself(GameTest):
    """`called` on its own, away from the pipeline."""

    loose_objects = 1

    def setUp(self):
        super().setUp()
        self.root = self.room1
        self.root.db.is_world_root = True
        self.room1.db.world_root = self.root

    def held(self, clause, bound=None, words=None):
        ctx = conditions.context(bound, self.char1, self.root, "summon",
                                 words=words)
        return conditions.evaluate(clause, ctx)

    def test_it_is_true_of_a_word_nothing_answers_to(self):
        self.assertTrue(self.held({"subject": "direct", "called": "air"},
                                  words={"direct": "air"}))

    def test_it_is_false_of_another_word(self):
        self.assertFalse(self.held({"subject": "direct", "called": "air"},
                                   words={"direct": "earth"}))

    def test_it_is_false_when_nothing_was_said(self):
        self.assertFalse(self.held({"subject": "direct", "called": "air"}))

    def test_articles_and_plurals_do_not_matter(self):
        self.assertTrue(self.held({"subject": "direct", "called": "air"},
                                  words={"direct": "the air"}))

    def test_a_sense_is_read_down_to_its_word(self):
        self.assertTrue(self.held({"subject": "direct", "called": "air.n.01"},
                                  words={"direct": "air"}))

    def test_it_is_true_of_what_the_word_was_found_to_mean(self):
        self.obj1.db.kinds = ["earth"]
        self.assertTrue(self.held({"subject": "direct", "called": "earth"},
                                  bound={"direct": self.obj1}))

    def test_and_of_a_thing_going_by_that_name(self):
        self.assertTrue(self.held({"subject": "direct",
                                   "called": self.obj1.key},
                                  bound={"direct": self.obj1}))

    def test_it_has_no_opposite_and_says_why(self):
        self.assertIn("called", conditions.UNNEGATABLE)
        self.assertIsNone(
            conditions.negate({"subject": "direct", "called": "air"}))

    def test_it_reads_as_a_sentence(self):
        said = conditions.describe({"subject": "direct", "called": "air"},
                                   mood=conditions.ABSTRACT)
        self.assertIn("air", said)


@tag("world")
class AWorldWithNothingToAsk(Alchemy):
    """
    Running a hand-written rule where no model will answer.

    Two questions sit between a rule and the player, and both are asked after
    the rule has been found: whether that sort of thing admits the verb, and
    how to describe what happened. Neither is "what does this verb mean" --
    somebody wrote that down. Asked of a world that writes no verbs of its
    own, both used to come back as a refusal, which threw away the rule and
    every effect with it, in red.

    So a world built by hand and paid for with nothing runs its own rules and
    reads a little flatly. That is the trade its builder made; a silent
    refusal is not.
    """

    def test_the_effects_land(self):
        rulebooks.add(self.root, _summoning("earth"))
        self.summon("earth")
        self.assertEqual(len(self.here("earth")), 1)

    def test_and_it_is_described_in_the_words_it_was_asked_for(self):
        rulebooks.add(self.root, _summoning("earth"))
        self.assertEqual(self.summon("earth"), "You summon earth.")

    def test_nothing_red_is_said(self):
        rulebooks.add(self.root, _summoning("earth"))
        self.assertNotIn("|r", self.summon("earth"))

    def test_a_second_time_over_a_thing_that_now_exists(self):
        """Where the admission question is asked, and has nobody to ask."""
        rulebooks.add(self.root, _summoning("earth"))
        self.summon("earth")
        self.summon("earth")
        self.assertEqual(len(self.here("earth")), 2)

    def test_the_admission_answer_is_not_remembered(self):
        """A world given a key later still gets to ask properly."""
        from world import kinds as kinds_mod

        rulebooks.add(self.root, _summoning("earth"))
        self.summon("earth")
        self.summon("earth")
        self.assertIsNone(
            kinds_mod.admits(self.root, ["earth.n.01"], "summon"))

    def test_a_remembered_no_is_still_a_no(self):
        from world import kinds as kinds_mod

        rulebooks.add(self.root, _summoning("earth"))
        self.summon("earth")
        kinds_mod.admit(self.root, ["earth.n.01"], "summon", False)
        said = self.summon("earth")
        self.assertEqual(len(self.here("earth")), 1)
        self.assertIn("cannot", said)
