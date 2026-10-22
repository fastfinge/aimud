"""
Prepositions that mean something: "wave the phone" is not "wave at the phone".

Two things stood in the way. A verb was declared once, from whichever
sentence used it first, so "wave the phone" settled that waving takes
something to wave and "wave at the phone" was answered "wave what?" for
ever. And a rule could not tell "on the table" from "under the table", since
both are `target`: the parser kept the word and nothing a rule tests read it.
"""

from unittest import mock

from django.test import SimpleTestCase, tag

from tests.base import GameTest
from world import actions, conditions, verbs


class FakeRoot:
    def __init__(self, specs=None):
        self.db = mock.Mock(action_specs=dict(specs or {}))


def judged(condition, typed):
    """Whether a condition holds for a sentence, as the attempt reads it."""
    parsed = verbs.parse(typed)
    ctx = conditions.context(words=conditions.words_of(parsed),
                             action=parsed["verb"])
    return conditions.satisfied([condition], ctx)


@tag("unit")
class TheWordThatIntroducedARole(SimpleTestCase):

    def test_under_is_not_on(self):
        under = {"subject": "target", "preposition": ["under"]}
        self.assertTrue(judged(under, "put book under table"))
        self.assertFalse(judged(under, "put book on table"))

    def test_a_list_is_any_of_them(self):
        on = {"subject": "target", "preposition": ["on", "onto", "upon"]}
        self.assertTrue(judged(on, "put book onto table"))

    def test_and_its_opposite_is_none_of_them(self):
        not_under = {"subject": "target", "not_preposition": ["under"]}
        self.assertTrue(judged(not_under, "put book on table"))
        self.assertFalse(judged(not_under, "put book under table"))

    def test_a_role_nobody_named_was_said_with_nothing(self):
        at = {"subject": "target", "preposition": ["at"]}
        self.assertFalse(judged(at, "wave phone"))
        self.assertTrue(judged({"subject": "target",
                                "not_preposition": ["at"]}, "wave phone"))

    def test_waving_at_and_waving_are_two_roles_already(self):
        self.assertEqual(verbs.parse("wave at phone")["roles"],
                         {"target": "phone"})
        self.assertEqual(verbs.parse("wave phone")["roles"],
                         {"direct": "phone"})

    def test_the_two_are_each_others_opposite(self):
        self.assertEqual(
            conditions.negate({"subject": "target", "preposition": ["at"]}),
            {"subject": "target", "not_preposition": ["at"]})

    def test_a_word_that_is_no_preposition_cannot_be_stored(self):
        kept, refused = conditions.normalise_all(
            [{"subject": "target", "preposition": ["sideways"]}])
        self.assertEqual(kept, [])
        self.assertTrue(refused)

    def test_it_reads_as_a_sentence(self):
        said = conditions.describe({"subject": "target",
                                    "preposition": ["under"]},
                                   mood=conditions.ABSTRACT)
        self.assertIn('"under"', said)

    def test_a_context_without_words_knows_no_preposition(self):
        ctx = conditions.context(words={"target": "table"})
        self.assertEqual(ctx.prepositions, {})


@tag("unit")
class WaysToSayAVerb(SimpleTestCase):

    def test_a_verb_with_two_shapes_takes_either(self):
        root = FakeRoot()
        actions.declare(root, "wave", [{"role": "direct"}],
                        shapes=[["direct"], ["target"], []])
        self.assertEqual(actions.missing_role(root, "wave",
                                              {"target": object()}), "")
        self.assertEqual(actions.missing_role(root, "wave",
                                              {"direct": object()}), "")
        self.assertEqual(actions.missing_role(root, "wave", {}), "")

    def test_with_no_bare_shape_a_bare_verb_asks_for_the_first(self):
        root = FakeRoot()
        actions.declare(root, "wave", [], shapes=[["direct"], ["target"]])
        self.assertEqual(actions.missing_role(root, "wave", {}), "direct")

    def test_a_role_a_shape_names_is_taken(self):
        root = FakeRoot()
        settled = actions.declare(root, "wave", [{"role": "direct"}],
                                  shapes=[["direct"], ["target"]])
        self.assertEqual({entry["role"] for entry in settled["applies_to"]},
                         {"direct", "target"})

    def test_a_declaration_without_shapes_is_its_required_roles(self):
        root = FakeRoot()
        actions.declare(root, "wave", [{"role": "direct"}])
        self.assertEqual(actions.shapes_of(actions.spec(root, "wave")),
                         [["direct"]])
        self.assertEqual(actions.missing_role(root, "wave",
                                              {"target": object()}), "direct")

    def test_a_new_way_is_one_nobody_settled(self):
        root = FakeRoot()
        actions.declare(root, "wave", [{"role": "direct"}])
        self.assertEqual(actions.unsaid_shape(root, "wave",
                                              {"target": object()}),
                         ["target"])
        self.assertIsNone(actions.unsaid_shape(root, "wave", {}),
                          "a bare verb is unfinished, not a new way")
        self.assertIsNone(actions.unsaid_shape(root, "wave",
                                               {"direct": object()}))

    def test_adding_a_way_keeps_the_old_one(self):
        root = FakeRoot()
        actions.declare(root, "wave", [{"role": "direct"}])
        actions.add_shape(root, "wave", ["target"], {"target": "visible"})
        self.assertEqual(actions.missing_role(root, "wave",
                                              {"target": object()}), "")
        self.assertEqual(actions.missing_role(root, "wave",
                                              {"direct": object()}), "")
        self.assertEqual(actions.access_for(root, "wave", "target"),
                         "visible")

    def test_a_refused_way_is_never_asked_about_again(self):
        root = FakeRoot()
        actions.declare(root, "power", [{"role": "direct"}])
        actions.refuse_shape(root, "power", ["target"])
        self.assertIsNone(actions.unsaid_shape(root, "power",
                                               {"target": object()}))
        self.assertEqual(actions.missing_role(root, "power",
                                              {"target": object()}), "direct")


@tag("world")
class WavingAtThePhone(GameTest):
    """The case from playtesting, end to end through an attempt."""

    loose_objects = 1

    def setUp(self):
        super().setUp()
        self.root = self.room1
        self.root.db.is_world_root = True
        self.room1.db.world_root = self.root
        self.room1.db.is_ai_room = True
        actions.declare(self.root, "wave", [{"role": "direct"}])

    def attempt(self, raw, **answers):
        from tests.support import FakeSponsor, finishing, immediately, replying
        from world import attempt as attempt_mod

        said = []
        answers.setdefault("file_rules", {"rules": [
            {"phase": "carry_out", "scope": "world", "about": "target",
             "effects": [{"type": "narrate"}]}]})
        with immediately(), replying(finishing(**answers)) as script:
            attempt_mod.attempt(
                self.char1, raw, FakeSponsor(),
                on_message=lambda actor_text, room_text=None:
                    said.append(actor_text))
            self.asked = script.count
        return " ".join(s for s in said if s)

    def test_a_way_the_world_agrees_to_is_added_and_goes_on(self):
        said = self.attempt("wave at obj", declare_shape={"takes": True})
        self.assertNotIn("Wave what?", said)
        self.assertIn(["target"],
                      actions.shapes_of(actions.spec(self.root, "wave")))

    def test_a_way_it_refuses_is_answered_as_before_and_kept(self):
        said = self.attempt("wave at obj", declare_shape={"takes": False})
        self.assertIn("Wave what?", said)
        self.assertEqual(actions.spec(self.root, "wave")["refused_shapes"],
                         [["target"]])
        self.attempt("wave at obj", declare_shape={"takes": False})
        self.assertEqual(self.asked, 0, "asked once, never again")

    def test_the_rule_writer_is_told_how_it_was_said(self):
        from world import rule_gen

        words = conditions.words_of(verbs.parse("wave at obj"))
        said = rule_gen.prompt(self.root, "wave", {"target": self.obj1},
                               self.char1, rule_gen.menu(self.root),
                               words=words)
        self.assertIn('the target with "at"', said)
