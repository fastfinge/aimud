"""
Learning a verb rule, with the model's answer coming from a script.

This is the test the plan calls phase 0's finish line: a generator driven end to
end, through the real prompt assembly, the real JSON repair, the real validation
and the real storage, without a network call and without a key. Everything it
exercises used to be reachable only by paying for a model, which is why none of
it was ever covered.
"""

from django.test import tag
from evennia.utils.test_resources import EvenniaTest

from tests.support import FakeSponsor, as_json, immediately, replying
from world import llm, verb_gen, verbs


@tag("world")
class LearningARule(EvenniaTest):

    def setUp(self):
        super().setUp()
        self.root = self.room1
        self.root.db.is_world_root = True
        self.account_stub = FakeSponsor()

    def learn(self, answer, verb="read", bound=None):
        """Drive `learn_rule` once and return (rule, error, recorder)."""
        got, failed = [], []
        with immediately(), replying(answer) as recorder:
            verb_gen.learn_rule(
                self.account_stub, self.root, verb,
                bound if bound is not None else {"direct": self.obj1},
                self.char1, f"{verb} obj",
                on_success=got.append,
                on_error=failed.append,
            )
        return (got[0] if got else None,
                failed[0] if failed else None,
                recorder)

    def test_a_rule_comes_back_parsed(self):
        rule, error, _ = self.learn(as_json({
            "valid": True,
            "requires": {"direct": {"has": ["read"]}},
            "effects": [{"type": "set_state", "role": "direct",
                         "add": ["read"]}],
            "repeatable": True,
        }))
        self.assertIsNone(error)
        self.assertTrue(rule["valid"])
        self.assertEqual(rule["requires"]["direct"]["has"], ["read"])

    def test_the_prompt_carries_the_objects_and_the_world(self):
        _rule, _error, recorder = self.learn(as_json({"valid": True,
                                                      "effects": []}))
        self.assertEqual(recorder.count, 1)
        sent = recorder.sent()
        self.assertIn("Obj", sent)
        self.assertIn("read obj", sent)

    def test_json_a_model_nearly_wrote_is_repaired_rather_than_lost(self):
        """model_json's whole purpose, never covered because it needed a model."""
        rule, error, _ = self.learn(
            '```json\n{"valid": true, // a note\n "effects": [],}\n```')
        self.assertIsNone(error)
        self.assertTrue(rule["valid"])

    def test_an_unrepairable_answer_is_an_error_and_not_a_crash(self):
        rule, error, _ = self.learn("I am afraid I cannot help with that.")
        self.assertIsNone(rule)
        self.assertTrue(error)

    def test_a_refusal_from_the_service_reaches_the_caller_in_words(self):
        rule, error, _ = self.learn(llm.LLMError("No credits left"))
        self.assertIsNone(rule)
        self.assertIn("No credits left", str(error))

    def test_a_new_state_is_registered_in_the_world_as_a_side_effect(self):
        """A rule may coin a word, and the world has to know it afterwards."""
        self.learn(as_json({
            "valid": True,
            "effects": [{"type": "set_state", "role": "direct",
                         "add": ["scorched"]}],
            "new_states": [{"slug": "scorched", "means": "burnt at the edges",
                            "group": "fire"}],
        }), verb="burn")
        vocabulary = verbs.vocabulary(self.root)
        self.assertIn("scorched", vocabulary)
        self.assertEqual(vocabulary["scorched"]["means"], "burnt at the edges")

    def test_a_rule_is_stored_and_found_again_without_a_second_call(self):
        answer = as_json({"valid": True, "effects": []})
        rule, _error, _ = self.learn(answer)
        key = verbs.rule_key("read", {"direct": self.obj1})
        verb_gen.store_rule(self.root, key, rule)

        with replying("this should never be asked for") as recorder:
            found = verb_gen.get_rule(self.root, key)
        self.assertEqual(recorder.count, 0)
        self.assertTrue(found["valid"])

    def test_a_stored_rule_comes_back_as_plain_python(self):
        """
        It has to, or it cannot go into a prompt.

        An Attribute hands back `_SaverDict`, which `json.dumps` refuses, and a
        rule is put in front of a model whenever a related verb is learned. This
        is the bug that class of problem always turns out to be.
        """
        import json

        key = verbs.rule_key("read", {"direct": self.obj1})
        verb_gen.store_rule(self.root, key, {
            "valid": True,
            "requires": {"direct": {"has": ["read"]}},
            "effects": [{"type": "set_state", "role": "direct",
                         "add": ["read"]}],
        })
        found = verb_gen.get_rule(self.root, key)
        json.dumps(found)          # would raise on a _SaverDict
        self.assertIsInstance(found, dict)
        self.assertIsInstance(found["requires"], dict)
        self.assertIsInstance(found["effects"], list)


@tag("world")
class TheDoorIsClosed(EvenniaTest):
    """
    Without `immediately()`, nothing happens -- which is the point of having it.

    Recorded as a test because it is the reason the seam exists: a
    `deferToThread` callback does not fire in a test, so a generator driven
    without this helper asserts nothing at all while appearing to pass.
    """

    def test_a_callback_does_not_fire_on_its_own(self):
        got = []
        with replying(as_json({"valid": True, "effects": []})):
            verb_gen.learn_rule(
                FakeSponsor(), self.room1, "read", {"direct": self.obj1},
                self.char1, "read obj",
                on_success=got.append, on_error=got.append,
            )
        self.assertEqual(got, [], "if this fires, the seam is no longer needed")


@tag("world")
class NarratingATemplate(EvenniaTest):
    """
    What the narrator is asked for, since P4: a template with every
    participant as a placeholder and the verb as `$pconj(...)`, so that one
    cached reply can be read as "she", "you" or a name by whoever is
    watching. The prompt is the only place a model learns that, so what it
    says is held still here.
    """

    def setUp(self):
        super().setUp()
        self.root = self.room1
        self.root.db.is_world_root = True
        self.root.db.world_root = self.root
        self.sponsor = FakeSponsor()

    def narrate(self, answer, bound=None):
        got, failed = [], []
        with immediately(), replying(answer) as recorder:
            verb_gen.narrate(
                self.sponsor, "hand",
                bound if bound is not None else {"direct": self.obj1,
                                                 "target": self.char2},
                self.char1, "hand obj to char2",
                on_success=lambda *parts: got.append(parts),
                on_error=failed.append)
        return (got[0] if got else None, failed[0] if failed else None,
                recorder)

    def test_the_prompt_lists_every_placeholder(self):
        _got, _err, recorder = self.narrate(
            as_json({"actor": "You hand it over.",
                     "room": "{actor} $pconj(hand) {target} {direct}."}))
        sent = recorder.sent()
        self.assertIn("{direct}", sent)
        self.assertIn("{target}", sent)
        self.assertIn("$pconj(", sent)

    def test_the_template_comes_back_untouched(self):
        """
        Filled in per viewer at delivery, never here: a name substituted now
        would be shown to everybody for ever.
        """
        got, err, _ = self.narrate(
            as_json({"actor": "You hand it over.",
                     "room": "{actor} $pconj(hand) {target} {direct}."}))
        self.assertIsNone(err)
        self.assertEqual(got[1], "{actor} $pconj(hand) {target} {direct}.")

    def test_and_renders_for_each_watcher(self):
        """The whole point, end to end: one reply, three readings."""
        from world import events, pronouns

        got, _err, _ = self.narrate(
            as_json({"actor": "You hand it over.",
                     "room": "{actor} $pconj(hand) {target} {direct}."}))
        pronouns.give(self.char1, "they", self.root)
        event = events.Event(actor=self.char1, room=self.root, verb="hand",
                             roles={"direct": self.obj1, "target": self.char2},
                             room_template=got[1])
        self.assertEqual(events.render(got[1], self.char2, event),
                         f"{self.char1.key} hand you the {self.obj1.key}.")
        self.assertEqual(events.render(got[1], None, event),
                         f"{self.char1.key} hand {self.char2.key} "
                         f"the {self.obj1.key}.")

    def test_a_careless_reply_is_repaired_before_it_is_stored(self):
        """
        The template is stored and replayed, so a stray article or a
        conjugated actor verb is permanent rather than a one-off. `repair`
        runs on the way in for that reason -- paid once, not on every read.
        """
        from world import events

        got, err, _ = self.narrate(
            as_json({"actor": "You hand it over.",
                     "room": "{actor} hands {target} the {direct}."}))
        self.assertIsNone(err)
        self.assertEqual(events.repair(got[1]),
                         "{actor} $pconj(hand) {target} {direct}.")
