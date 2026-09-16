"""
Verb rules kept per world, and narration, with the model's answer coming from
a script.

This was phase 0's finish line: a generator driven end to end, through the real
prompt assembly, the real JSON repair and the real storage, without a network
call and without a key. The generator it first drove, `learn_rule`, has gone --
`rule_gen.learn` writes a world's rules now -- so what it proved is proved here
on `narrate`, which goes through the same door and the same repair.
"""

from django.test import tag

from tests.base import GameTest
from tests.support import (FakeSponsor, finishing, immediately, replying,
                           tool_reply)
from world import llm, verb_gen, verbs


@tag("world")
class KeepingARule(GameTest):
    """The per-world store `attempt` still reads and `ask_admission` writes out."""

    loose_objects = 1

    def setUp(self):
        super().setUp()
        self.root = self.room1
        self.root.db.is_world_root = True

    def test_a_rule_is_stored_and_found_again_without_a_call(self):
        key = verbs.rule_key("read", {"direct": self.obj1})
        verb_gen.store_rule(self.root, key, {"valid": True, "effects": []})

        with replying("this should never be asked for") as recorder:
            found = verb_gen.get_rule(self.root, key)
        self.assertEqual(recorder.count, 0)
        self.assertTrue(found["valid"])

    def test_a_stored_rule_comes_back_as_plain_python(self):
        """
        It has to, or it cannot go into a prompt.

        An Attribute hands back `_SaverDict`, which `json.dumps` refuses, and
        `ask_admission` puts the verb's rule in front of a model as JSON. This
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


def _narrating(sponsor, answer, bound, actor, raw="hand obj to char2",
               verb="hand"):
    """Drive `narrate` once and return (parts, error, recorder)."""
    got, failed = [], []
    with immediately(), replying(answer) as recorder:
        verb_gen.narrate(
            sponsor, verb, bound, actor, raw,
            on_success=lambda *parts: got.append(parts),
            on_error=failed.append)
    return (got[0] if got else None, failed[0] if failed else None, recorder)


@tag("world")
class TheDoorIsClosed(GameTest):
    """
    Without `immediately()`, nothing happens -- which is the point of having it.

    Recorded as a test because it is the reason the seam exists: a
    `deferToThread` callback does not fire in a test, so a generator driven
    without this helper asserts nothing at all while appearing to pass.
    """

    loose_objects = 1

    def test_a_callback_does_not_fire_on_its_own(self):
        got = []
        with replying(finishing(narrate={"actor": "You hand it over.",
                               "room": "{actor} $pconj(hand) {direct}."})):
            verb_gen.narrate(
                FakeSponsor(), "hand", {"direct": self.obj1}, self.char1,
                "hand obj",
                on_success=lambda *parts: got.append(parts),
                on_error=got.append,
            )
        self.assertEqual(got, [], "if this fires, the seam is no longer needed")


@tag("world")
class NarratingATemplate(GameTest):
    """
    What the narrator is asked for, since P4: a template with every
    participant as a placeholder and the verb as `$pconj(...)`, so that one
    cached reply can be read as "she", "you" or a name by whoever is
    watching. The prompt is the only place a model learns that, so what it
    says is held still here.
    """

    characters = 2
    loose_objects = 1

    def setUp(self):
        super().setUp()
        self.root = self.room1
        self.root.db.is_world_root = True
        self.root.db.world_root = self.root
        self.sponsor = FakeSponsor()

    def narrate(self, answer, bound=None):
        return _narrating(
            self.sponsor, answer,
            bound if bound is not None else {"direct": self.obj1,
                                             "target": self.char2},
            self.char1)

    def test_the_prompt_lists_every_placeholder(self):
        _got, _err, recorder = self.narrate(
            finishing(narrate={"actor": "You hand it over.",
                     "room": "{actor} $pconj(hand) {target} {direct}."}))
        sent = recorder.sent()
        self.assertIn("{direct}", sent)
        self.assertIn("{target}", sent)
        self.assertIn("$pconj(", sent)

    def test_the_prompt_carries_the_objects_and_what_was_typed(self):
        _got, _err, recorder = self.narrate(
            finishing(narrate={"actor": "You hand it over.",
                     "room": "{actor} $pconj(hand) {target} {direct}."}))
        self.assertEqual(recorder.count, 1)
        sent = recorder.sent()
        self.assertIn(self.obj1.key, sent)
        self.assertIn("hand obj to char2", sent)

    def test_the_template_comes_back_untouched(self):
        """
        Filled in per viewer at delivery, never here: a name substituted now
        would be shown to everybody for ever.
        """
        got, err, _ = self.narrate(
            finishing(narrate={"actor": "You hand it over.",
                     "room": "{actor} $pconj(hand) {target} {direct}."}))
        self.assertIsNone(err)
        self.assertEqual(got[1], "{actor} $pconj(hand) {target} {direct}.")

    def test_and_renders_for_each_watcher(self):
        """The whole point, end to end: one reply, three readings."""
        from world import events, pronouns

        got, _err, _ = self.narrate(
            finishing(narrate={"actor": "You hand it over.",
                     "room": "{actor} $pconj(hand) {target} {direct}."}))
        pronouns.give(self.char1, "they", self.root)
        event = events.Event(actor=self.char1, room=self.root, verb="hand",
                             roles={"direct": self.obj1, "target": self.char2},
                             room_template=got[1])
        # They/them, and named, so one person: "hands". Only "they" hand.
        self.assertEqual(events.render(got[1], self.char2, event),
                         f"{self.char1.key} hands you the {self.obj1.key}.")
        self.assertEqual(events.render(got[1], None, event),
                         f"{self.char1.key} hands {self.char2.key} "
                         f"the {self.obj1.key}.")

    def test_a_careless_reply_is_repaired_before_it_is_stored(self):
        """
        The template is stored and replayed, so a stray article or a
        conjugated actor verb is permanent rather than a one-off. `repair`
        runs on the way in for that reason -- paid once, not on every read.
        """
        from world import events

        got, err, _ = self.narrate(
            finishing(narrate={"actor": "You hand it over.",
                     "room": "{actor} hands {target} the {direct}."}))
        self.assertIsNone(err)
        self.assertEqual(events.repair(got[1]),
                         "{actor} $pconj(hand) {target} {direct}.")

    def test_json_a_model_nearly_wrote_is_repaired_rather_than_lost(self):
        """model_json's whole purpose, never covered because it needed a model."""
        got, err, _ = self.narrate(tool_reply({
            "id": "call_nearly", "type": "function",
            "function": {"name": "narrate", "arguments": (
                '{"actor": "You hand it over.", // a note\n'
                ' "room": "{actor} $pconj(hand) {target} {direct}.",}')}}))
        self.assertIsNone(err)
        self.assertEqual(got[0], "You hand it over.")

    def test_an_unrepairable_answer_is_an_error_and_not_a_crash(self):
        got, err, _ = self.narrate("I am afraid I cannot help with that.")
        self.assertIsNone(got)
        self.assertTrue(err)

    def test_a_refusal_from_the_service_reaches_the_caller_in_words(self):
        got, err, _ = self.narrate(llm.LLMError("No credits left"))
        self.assertIsNone(got)
        self.assertIn("No credits left", str(err))
