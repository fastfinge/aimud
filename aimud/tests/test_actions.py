"""
What a verb takes, declared once instead of guessed at every time.

The failure this exists to end is in the exported corpus and is worth stating
plainly: `search` is stored with no preconditions and an effect that sets
`searched` on `direct`. Typed bare it binds no direct object, the effect
resolves to nothing, and the attempt reports success having changed nothing at
all. A silent no-op is worse than a refusal, because a refusal can be read.
"""

from unittest import mock

from django.test import SimpleTestCase, tag
from evennia.utils.test_resources import EvenniaTest

from world import actions


class FakeRoot:
    def __init__(self, specs=None):
        self.db = mock.Mock(action_specs=dict(specs or {}))


@tag("unit")
class DeclaringAnAction(SimpleTestCase):

    def test_a_declaration_is_stored_and_read_back(self):
        root = FakeRoot()
        actions.declare(root, "power", [{"role": "direct"}])
        settled = actions.spec(root, "power")
        self.assertEqual(settled["action"], "power")
        self.assertEqual([r["role"] for r in settled["applies_to"]],
                         ["direct"])

    def test_a_sense_english_has_already_settled_needs_nobody_asked(self):
        root = FakeRoot()
        settled = actions.declare(root, "power", [{"role": "direct"}])
        self.assertEqual(settled["sense"], "power.v.01")
        self.assertIn("force", settled["means"])

    def test_a_sense_that_was_chosen_is_kept(self):
        root = FakeRoot()
        settled = actions.declare(root, "launch", [{"role": "direct"}],
                                  sense="launch.v.03")
        self.assertEqual(settled["sense"], "launch.v.03")
        self.assertIn("maiden voyage", settled["means"])

    def test_a_sense_that_does_not_exist_is_not_believed(self):
        root = FakeRoot()
        settled = actions.declare(root, "launch", [], sense="launch.v.99")
        self.assertNotEqual(settled["sense"], "launch.v.99")

    def test_a_verb_with_several_senses_and_no_choice_gets_none(self):
        root = FakeRoot()
        self.assertEqual(actions.declare(root, "launch", [])["sense"], "")

    def test_words_of_ones_own_beat_the_dictionary(self):
        root = FakeRoot()
        settled = actions.declare(root, "power", [], means="to wake a machine")
        self.assertEqual(settled["means"], "to wake a machine")

    def test_synonyms_declare_one_action(self):
        """`examine` folds to `look` long before this, and must stay folded."""
        root = FakeRoot()
        actions.declare(root, "examine", [{"role": "direct"}])
        self.assertIsNotNone(actions.spec(root, "look"))

    def test_the_first_answer_stands(self):
        root = FakeRoot()
        actions.declare(root, "power", [{"role": "direct"}])
        again = actions.declare(root, "power", [{"role": "target"}])
        self.assertEqual([r["role"] for r in again["applies_to"]], ["direct"])

    def test_nothing_is_not_an_action(self):
        root = FakeRoot()
        self.assertIsNone(actions.declare(root, "", []))
        self.assertIsNone(actions.spec(root, ""))


@tag("unit")
class WhatARoleMayBe(SimpleTestCase):
    """Closed on the way in: an untestable clause is one nothing can meet."""

    def test_a_role_nobody_can_bind_is_dropped(self):
        got = actions.clean_roles([{"role": "beneficiary"}, {"role": "direct"}])
        self.assertEqual([r["role"] for r in got], ["direct"])

    def test_an_access_nobody_can_test_falls_back(self):
        got = actions.clean_roles([{"role": "direct", "access": "nearby"}])
        self.assertEqual(got[0]["access"], actions.TOUCHABLE)

    def test_the_three_accesses_are_kept(self):
        for access in actions.ACCESS:
            got = actions.clean_roles([{"role": "direct", "access": access}])
            self.assertEqual(got[0]["access"], access)

    def test_a_role_named_twice_is_one_role(self):
        got = actions.clean_roles([{"role": "direct"}, {"role": "direct"}])
        self.assertEqual(len(got), 1)

    def test_required_is_the_default(self):
        self.assertFalse(actions.clean_roles([{"role": "direct"}])[0]["optional"])

    def test_nonsense_is_dropped_rather_than_raised(self):
        self.assertEqual(actions.clean_roles(["direct", None, 7]), [])
        self.assertEqual(actions.clean_roles(None), [])


@tag("unit")
class DeclaringFromWhatWasTyped(SimpleTestCase):
    """The standing-in until a generator is asked, and it costs no call."""

    def test_a_verb_typed_with_a_noun_takes_one(self):
        root = FakeRoot()
        actions.observe(root, "power", {"direct": object()})
        self.assertEqual(
            [r["role"] for r in actions.spec(root, "power")["applies_to"]],
            ["direct"])

    def test_and_takes_it_as_required(self):
        """
        Deliberately, because the failure being fixed is the silent one: a
        verb first typed with a noun and later typed bare should ask what.
        """
        root = FakeRoot()
        actions.observe(root, "power", {"direct": object()})
        self.assertEqual(actions.missing_role(root, "power", {}), "direct")

    def test_a_verb_typed_bare_takes_nothing(self):
        root = FakeRoot()
        actions.observe(root, "shrug", {})
        self.assertEqual(actions.spec(root, "shrug")["applies_to"], [])
        self.assertEqual(actions.missing_role(root, "shrug", {}), "")

    def test_several_roles_are_all_taken(self):
        root = FakeRoot()
        actions.observe(root, "unlock",
                        {"direct": object(), "instrument": object()})
        self.assertEqual(
            {r["role"] for r in actions.spec(root, "unlock")["applies_to"]},
            {"direct", "instrument"})

    def test_an_action_already_declared_is_left_alone(self):
        root = FakeRoot()
        actions.declare(root, "power", [{"role": "direct", "optional": True}])
        actions.observe(root, "power", {"direct": object(),
                                        "target": object()})
        self.assertEqual(
            [r["role"] for r in actions.spec(root, "power")["applies_to"]],
            ["direct"])


@tag("unit")
class AskingWhat(SimpleTestCase):

    def test_a_missing_required_role_is_named(self):
        root = FakeRoot()
        actions.declare(root, "power", [{"role": "direct"}])
        self.assertEqual(actions.missing_role(root, "power", {}), "direct")

    def test_a_role_that_is_bound_is_not_missing(self):
        root = FakeRoot()
        actions.declare(root, "power", [{"role": "direct"}])
        self.assertEqual(
            actions.missing_role(root, "power", {"direct": object()}), "")

    def test_an_optional_role_is_never_missing(self):
        """
        Supplying it is an `instead` rule's job, not this one's: "launch"
        aboard a ship means the ship, and that is a rule rather than a
        refusal.
        """
        root = FakeRoot()
        actions.declare(root, "launch",
                        [{"role": "direct", "optional": True}])
        self.assertEqual(actions.missing_role(root, "launch", {}), "")

    def test_an_undeclared_action_asks_for_nothing(self):
        self.assertEqual(actions.missing_role(FakeRoot(), "power", {}), "")

    def test_the_question_reads_as_a_question(self):
        self.assertEqual(actions.asking_for("power", "direct"), "Power what?")
        self.assertEqual(actions.asking_for("unlock", "instrument"),
                         "Unlock with what?")
        self.assertEqual(actions.asking_for("pour", "container"),
                         "Pour in what?")


@tag("world")
class WhatMustBeInHand(EvenniaTest):
    """
    Inform's carrying requirements rule, as data.

    Nothing consults it until the cutover, where taking a thing is an act with
    a message and there is a phase for it to happen in. Tested now because it
    is what `access` is for, and a slot nothing reads is a slot that rots.
    """

    def setUp(self):
        super().setUp()
        self.root = self.room1
        self.root.db.is_world_root = True

    def test_a_carried_role_that_is_not_carried_wants_taking(self):
        actions.declare(self.root, "throw",
                        [{"role": "direct", "access": actions.CARRIED}])
        self.assertEqual(
            actions.to_take(self.root, "throw", {"direct": self.obj1},
                            self.char1),
            [self.obj1])

    def test_and_wants_nothing_once_it_is_in_hand(self):
        actions.declare(self.root, "throw",
                        [{"role": "direct", "access": actions.CARRIED}])
        self.obj1.move_to(self.char1, quiet=True)
        self.assertEqual(
            actions.to_take(self.root, "throw", {"direct": self.obj1},
                            self.char1), [])

    def test_a_touchable_role_is_never_taken(self):
        actions.declare(self.root, "read",
                        [{"role": "direct", "access": actions.TOUCHABLE}])
        self.assertEqual(
            actions.to_take(self.root, "read", {"direct": self.obj1},
                            self.char1), [])

    def test_an_undeclared_action_takes_nothing(self):
        self.assertEqual(
            actions.to_take(self.root, "read", {"direct": self.obj1},
                            self.char1), [])


@tag("world")
class TheSilentNoOpIsGone(EvenniaTest):
    """
    The whole point of phase 5, end to end through the attempt pipeline.

    `search` typed with a noun teaches the world that searching takes one.
    Typed bare afterwards it used to reach a rule whose effects named a role
    nobody had bound, change nothing, and report success.
    """

    def setUp(self):
        super().setUp()
        self.root = self.room1
        self.root.db.is_world_root = True
        self.room1.db.world_root = self.root
        self.room1.db.is_ai_room = True

    def attempt(self, raw):
        from tests.support import FakeSponsor, immediately, replying
        from world import attempt as attempt_mod

        said = []
        with immediately(), replying('{"valid": true, "effects": []}'):
            attempt_mod.attempt(
                self.char1, raw, FakeSponsor(),
                on_message=lambda actor_text, room_text=None:
                    said.append(actor_text))
        return " ".join(s for s in said if s)

    def test_a_verb_learned_with_a_noun_asks_what_when_typed_bare(self):
        self.attempt("search obj")
        self.assertIsNotNone(actions.spec(self.root, "search"))
        self.assertEqual(actions.missing_role(self.root, "search", {}),
                         "direct")

    def test_and_the_question_reaches_the_player(self):
        self.attempt("search obj")
        self.assertIn("Search what?", self.attempt("search"))


@tag("world")
class AskingWhatAnActionTakes(EvenniaTest):
    """
    The first of the two questions a new verb costs, and the cheaper one.

    It comes first because its answer changes the second: a `direct` declared
    optional is what lets `power` typed bare reach an `instead` rule rather
    than being told "power what?".
    """

    def setUp(self):
        super().setUp()
        self.root = self.room1
        self.root.db.is_world_root = True
        self.room1.db.world_root = self.root
        self.room1.db.is_ai_room = True

    def ask(self, reply, bound=None):
        from tests.support import FakeSponsor, as_json, immediately, replying

        got = []
        with immediately(), replying(
                as_json(reply) if isinstance(reply, dict) else reply):
            actions.learn(FakeSponsor(), self.root, "power",
                          bound if bound is not None else {},
                          self.char1,
                          on_success=got.append,
                          on_error=lambda err: self.fail(err))
        return got[0] if got else None

    def test_a_declaration_is_taken_as_given(self):
        spec = self.ask({"applies_to": [
            {"role": "direct", "access": "touchable", "optional": True}]})
        self.assertEqual(len(spec["applies_to"]), 1)
        self.assertTrue(spec["applies_to"][0]["optional"])
        self.assertEqual(spec["applies_to"][0]["access"], "touchable")

    def test_an_optional_role_is_not_asked_about_when_unsaid(self):
        """The whole reason Q1 runs before Q2."""
        self.ask({"applies_to": [
            {"role": "direct", "access": "touchable", "optional": True}]})
        self.assertEqual(actions.missing_role(self.root, "power", {}), "")

    def test_a_required_one_is(self):
        self.ask({"applies_to": [
            {"role": "direct", "access": "touchable", "optional": False}]})
        self.assertEqual(actions.missing_role(self.root, "power", {}), "direct")

    def test_a_verb_that_takes_nothing_may_say_so(self):
        spec = self.ask({"applies_to": []})
        self.assertEqual(spec["applies_to"], [])
        self.assertEqual(actions.missing_role(self.root, "power", {}), "")

    def test_but_a_reply_that_is_not_a_declaration_falls_back(self):
        """
        Not the same thing. Taking a non-answer for "it takes nothing" would
        settle that permanently, on no evidence, and a declaration is settled
        once.
        """
        spec = self.ask({"valid": True, "effects": []},
                        bound={"direct": self.obj1})
        self.assertEqual([r["role"] for r in spec["applies_to"]], ["direct"])

    def test_and_so_does_a_reply_that_is_not_json(self):
        spec = self.ask("I am afraid I cannot help with that.",
                        bound={"direct": self.obj1})
        self.assertEqual([r["role"] for r in spec["applies_to"]], ["direct"])

    def test_an_action_already_declared_is_not_asked_about_again(self):
        actions.declare(self.root, "power",
                        [{"role": "direct", "optional": True}])
        from tests.support import FakeSponsor, immediately, replying

        got = []
        with immediately(), replying("{}") as script:
            actions.learn(FakeSponsor(), self.root, "power", {}, self.char1,
                          on_success=got.append,
                          on_error=lambda err: self.fail(err))
            self.assertEqual(script.count, 0, "nothing should have been asked")
        self.assertTrue(got[0]["applies_to"][0]["optional"])

    def test_a_sense_from_the_dictionary_fills_in_what_it_means(self):
        """`power` has one sense, so nobody has to be asked which."""
        spec = self.ask({"applies_to": []})
        self.assertTrue(spec["sense"])
        self.assertTrue(spec["means"])

